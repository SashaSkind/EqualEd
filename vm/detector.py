"""Warehouse robot + personal-space detector (phase 1).

Detects:
  * people (YOLO11)
  * humanoid robots (person boxes with teal/cyan chassis or thin dark metal body)
  * mobile platforms / AGVs (YOLOE open-vocab)

For every robot, reports whether a person (or another agent) is inside its
personal-space bubble. Distance is estimated in "body-heights" of the robot
box — same flat-camera trick as the laptop sensory demo.
"""
from __future__ import annotations

import collections
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

# personal space: center-to-center distance / robot height
PERSONAL_SPACE = 1.15          # invaded when closer than this
DEPTH_SIZE_MIN = 0.35          # other box must be >= this * robot height (depth proxy)
HOLD_S = 0.25                  # must stay invaded this long before flipping status
CLEAR_HOLD_S = 0.4
TEAL_FRAC = 0.16               # cyan chest plate (upper-box score)
DARK_FRAC = 0.40
TRACK_IOU = 0.12
TRACK_TTL = 3.0
AGV_CONF = 0.40
AGV_NAMES = [
    "yellow AGV",
    "yellow robot platform",
    "mobile robot",
    "wheeled robot",
    "autonomous pallet jack",
]


def _center(b):
    return np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2], dtype=np.float64)


def _bh(b):
    return max(float(b[3] - b[1]), 1.0)


def _bw(b):
    return max(float(b[2] - b[0]), 1.0)


def _size(b):
    """Scale for personal-space math. AGVs are short/wide — use the longer side."""
    return max(_bh(b), _bw(b) * 0.75, 1.0)


def _iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = _bw(a) * _bh(a) + _bw(b) * _bh(b) - inter
    return inter / union if union > 0 else 0.0


def _teal_frac(crop_bgr):
    if crop_bgr.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (80, 60, 60), (110, 255, 255))
    return float(mask.mean()) / 255.0


def _upper_teal_frac(crop_bgr):
    """Teal humanoids have a cyan chest plate — score the upper 55% of the box."""
    if crop_bgr.size == 0:
        return 0.0
    h = crop_bgr.shape[0]
    return _teal_frac(crop_bgr[: max(1, int(h * 0.55))])


def _dark_frac(crop_bgr):
    if crop_bgr.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 0), (180, 90, 75))
    return float(mask.mean()) / 255.0


@dataclass
class Track:
    tid: int
    kind: str                          # "robot" | "person"
    subtype: str                       # humanoid / agv / person
    box: np.ndarray
    conf: float
    last_seen: float
    invaded: bool = False
    invaded_since: float | None = None
    clear_since: float | None = None
    closest: float | None = None
    closest_label: str = ""
    invasion_count: int = 0
    hist: collections.deque = field(default_factory=lambda: collections.deque(maxlen=40))


class RobotSpaceDetector:
    def __init__(self, device="cpu"):
        from ultralytics import YOLO, YOLOE

        self.device = device
        self.people = YOLO("yolo11n.pt")
        self.agv = YOLOE("yoloe-11s-seg.pt")
        self.agv.set_classes(AGV_NAMES, self.agv.get_text_pe(AGV_NAMES))
        self.tracks: dict[int, Track] = {}
        self.next_id = 1
        self.frame_i = 0
        self.events: collections.deque = collections.deque(maxlen=80)
        self.video_t = 0.0
        self.fps_est = 0.0

    def reset(self):
        self.tracks.clear()
        self.next_id = 1
        self.frame_i = 0
        self.events.clear()
        self.video_t = 0.0

    # -------------------------------------------------------------- detect
    def _detect_people_boxes(self, frame):
        r = self.people.predict(frame, conf=0.35, verbose=False, classes=[0], device=self.device)[0]
        if r.boxes is None or len(r.boxes) == 0:
            return []
        out = []
        for conf, box in zip(r.boxes.conf.cpu().numpy(), r.boxes.xyxy.cpu().numpy()):
            out.append(("person_cand", float(conf), box.astype(np.float64)))
        return out

    def _detect_agvs(self, frame):
        # YOLOE every other frame is enough — AGVs move slowly
        if self.frame_i % 2 != 0 and hasattr(self, "_agv_cache"):
            return self._agv_cache
        r = self.agv.predict(frame, conf=AGV_CONF, verbose=False, device=self.device)[0]
        out = []
        if r.boxes is not None:
            for c, conf, box in zip(
                r.boxes.cls.cpu().numpy(),
                r.boxes.conf.cpu().numpy(),
                r.boxes.xyxy.cpu().numpy(),
            ):
                name = AGV_NAMES[int(c)]
                out.append((name, float(conf), box.astype(np.float64)))
        # NMS-ish: drop heavy overlaps, keep highest conf
        out.sort(key=lambda x: -x[1])
        kept = []
        for item in out:
            if any(_iou(item[2], k[2]) > 0.35 for k in kept):
                continue
            # reject very thin horizontal slivers at the image edge
            if _bh(item[2]) < 18 and item[2][1] < 5:
                continue
            kept.append(item)
        self._agv_cache = kept
        return kept

    def _classify_person_cand(self, frame, box, conf):
        x1, y1, x2, y2 = map(int, box)
        crop = frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
        teal = _upper_teal_frac(crop)
        aspect = _bh(box) / _bw(box)
        # teal/cyan humanoid chassis (safety-vest wearers usually score lower on upper box)
        if teal >= TEAL_FRAC and aspect >= 1.8:
            return "robot", "humanoid-teal", conf
        return "person", "person", conf

    def _raw_detections(self, frame):
        dets = []
        for _, conf, box in self._detect_people_boxes(frame):
            kind, subtype, c = self._classify_person_cand(frame, box, conf)
            dets.append((kind, subtype, c, box))
        for name, conf, box in self._detect_agvs(frame):
            # skip AGV boxes that mostly overlap an already-found humanoid
            if any(_iou(box, d[3]) > 0.4 and d[0] == "robot" and d[1].startswith("humanoid") for d in dets):
                continue
            dets.append(("robot", "agv", conf, box))
        # Dedupe overlapping boxes (same body classified twice across frames' residue)
        dets.sort(key=lambda d: (0 if d[0] == "robot" else 1, -d[2]))
        kept = []
        for d in dets:
            if any(_iou(d[3], k[3]) > 0.45 for k in kept):
                continue
            kept.append(d)
        return kept

    # -------------------------------------------------------------- track
    def _match(self, dets, now):
        """Greedy IoU match. Kind can flip person↔robot; keep the track id stable."""
        unused = set(self.tracks)
        assigned = []
        pairs = []
        for di, (kind, subtype, conf, box) in enumerate(dets):
            best_tid, best_iou = None, TRACK_IOU
            for tid in unused:
                tr = self.tracks[tid]
                score = _iou(tr.box, box)
                # prefer same-kind matches slightly
                if tr.kind == kind:
                    score += 0.05
                if score > best_iou:
                    best_tid, best_iou = tid, score
            if best_tid is not None:
                unused.remove(best_tid)
                pairs.append((best_tid, di, best_iou))
            else:
                assigned.append(di)

        for tid, di, _ in pairs:
            kind, subtype, conf, box = dets[di]
            tr = self.tracks[tid]
            tr.box, tr.conf, tr.last_seen = box, conf, now
            # Sticky robot: once a track is a robot, don't demote on a single weak frame
            if tr.kind == "robot" and kind == "person":
                # only demote after the robot cue has been gone a while
                if now - getattr(tr, "robot_cue_at", tr.last_seen) < 1.0:
                    kind, subtype = "robot", tr.subtype
                else:
                    tr.kind, tr.subtype = kind, subtype
            else:
                if kind == "robot":
                    tr.robot_cue_at = now
                tr.kind, tr.subtype = kind, subtype
            tr.hist.append((now, box.copy()))

        for di in assigned:
            kind, subtype, conf, box = dets[di]
            tid = self.next_id
            self.next_id += 1
            tr = Track(
                tid=tid, kind=kind, subtype=subtype, box=box, conf=conf,
                last_seen=now, hist=collections.deque([(now, box.copy())], maxlen=40),
            )
            if kind == "robot":
                tr.robot_cue_at = now
            self.tracks[tid] = tr

        for tid in list(unused):
            if now - self.tracks[tid].last_seen > TRACK_TTL:
                del self.tracks[tid]

    # -------------------------------------------------------------- space
    def _update_space(self, now):
        robots = [t for t in self.tracks.values() if t.kind == "robot"]
        people = [t for t in self.tracks.values() if t.kind == "person"]
        # Phase 1: personal space is invaded by people (not other robots).
        others_by_robot = people

        for rob in robots:
            th = _size(rob.box)
            rc = _center(rob.box)
            closest, closest_label = None, ""
            invaded_raw = False
            for p in others_by_robot:
                # same physical body tracked twice — ignore
                if _iou(rob.box, p.box) > 0.4:
                    continue
                # depth proxy: skip tiny far people relative to this robot
                if _size(p.box) < DEPTH_SIZE_MIN * th:
                    continue
                d = float(np.linalg.norm(_center(p.box) - rc)) / th
                if closest is None or d < closest:
                    closest, closest_label = d, f"person-{p.tid}"
                if d < PERSONAL_SPACE:
                    invaded_raw = True

            rob.closest = closest
            rob.closest_label = closest_label
            was = rob.invaded
            if invaded_raw:
                rob.clear_since = None
                if rob.invaded_since is None:
                    rob.invaded_since = now
                if now - rob.invaded_since >= HOLD_S:
                    rob.invaded = True
            else:
                rob.invaded_since = None
                if rob.clear_since is None:
                    rob.clear_since = now
                if now - rob.clear_since >= CLEAR_HOLD_S:
                    rob.invaded = False

            if rob.invaded and not was:
                rob.invasion_count += 1
                self.events.appendleft({
                    "t": round(self.video_t, 2),
                    "wall": time.strftime("%H:%M:%S"),
                    "robot": f"R{rob.tid}",
                    "subtype": rob.subtype,
                    "kind": "invasion",
                    "detail": f"personal space invaded by {closest_label}"
                              + (f" ({closest:.2f} body-lengths)" if closest is not None else ""),
                })
            elif was and not rob.invaded:
                self.events.appendleft({
                    "t": round(self.video_t, 2),
                    "wall": time.strftime("%H:%M:%S"),
                    "robot": f"R{rob.tid}",
                    "subtype": rob.subtype,
                    "kind": "clear",
                    "detail": "personal space clear again",
                })

    # -------------------------------------------------------------- public
    def process(self, frame, video_t=None, now=None):
        self.frame_i += 1
        if video_t is not None:
            self.video_t = float(video_t)
        if now is None:
            now = time.time()
        dets = self._raw_detections(frame)
        self._match(dets, now)
        self._update_space(now)
        return self.state()

    def state(self):
        robots, people = [], []
        for tr in sorted(self.tracks.values(), key=lambda t: t.tid):
            item = {
                "id": tr.tid,
                "label": f"{'R' if tr.kind == 'robot' else 'P'}{tr.tid}",
                "kind": tr.kind,
                "subtype": tr.subtype,
                "conf": round(tr.conf, 2),
                "box": [round(float(x), 1) for x in tr.box.tolist()],
                "invaded": bool(tr.invaded) if tr.kind == "robot" else None,
                "status": ("invaded" if tr.invaded else "clear") if tr.kind == "robot" else "person",
                "closest": None if tr.closest is None else round(tr.closest, 2),
                "closest_label": tr.closest_label,
                "invasion_count": tr.invasion_count,
            }
            (robots if tr.kind == "robot" else people).append(item)
        invaded_n = sum(1 for r in robots if r["invaded"])
        return {
            "video_t": round(self.video_t, 2),
            "frame": self.frame_i,
            "robots": robots,
            "people": people,
            "summary": {
                "robots": len(robots),
                "people": len(people),
                "invaded": invaded_n,
                "clear": len(robots) - invaded_n,
            },
            "events": list(self.events)[:40],
            "thresholds": {
                "personal_space_body_lengths": PERSONAL_SPACE,
                "hold_s": HOLD_S,
            },
        }

    def annotate(self, frame, state=None):
        """Draw boxes + status on a copy of the frame."""
        st = state or self.state()
        vis = frame.copy()
        lookup = {a["id"]: a for a in st["robots"] + st["people"]}
        for tr in self.tracks.values():
            info = lookup.get(tr.tid, {})
            x1, y1, x2, y2 = map(int, tr.box)
            if tr.kind == "robot":
                invaded = bool(info.get("invaded"))
                col = (0, 0, 230) if invaded else (0, 200, 80)
                tag = f"R{tr.tid} {tr.subtype} · {'INVADED' if invaded else 'CLEAR'}"
                if info.get("closest") is not None:
                    tag += f" ({info['closest']:.1f}bl)"
                thick = 3 if invaded else 2
            else:
                col, tag, thick = (220, 180, 60), f"P{tr.tid}", 2
            cv2.rectangle(vis, (x1, y1), (x2, y2), col, thick)
            cv2.putText(vis, tag, (x1, max(y1 - 8, 16)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 2, cv2.LINE_AA)
            if tr.kind == "robot":
                # personal-space radius sketch (ellipse approx)
                cx, cy = map(int, _center(tr.box))
                rad = int(PERSONAL_SPACE * _size(tr.box) / 2)
                cv2.circle(vis, (cx, cy), max(rad, 8), col, 1)
        banner = (f"robots {st['summary']['robots']}  "
                  f"invaded {st['summary']['invaded']}  "
                  f"clear {st['summary']['clear']}  "
                  f"people {st['summary']['people']}  "
                  f"t={st['video_t']:.1f}s")
        cv2.rectangle(vis, (0, 0), (vis.shape[1], 36), (20, 20, 20), -1)
        cv2.putText(vis, banner, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (240, 240, 240), 2, cv2.LINE_AA)
        return vis
