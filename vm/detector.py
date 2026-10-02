"""Warehouse robot detector: personal space + sudden movement (phases 1–2).

Detects:
  * people (YOLO11)
  * humanoid robots (person boxes with teal/cyan chassis)
  * mobile platforms / AGVs (YOLOE open-vocab)

Per humanoid robot: personal-space invasion (people or AGVs inside its bubble).
AGVs can intrude on a humanoid but have no personal space of their own, so they
are never "invaded". Every track gets a sudden-movement flag (box center speed in
body-lengths/sec).
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
# sudden movement (body-lengths of subject size per second)
SPEED_DT = 0.35
SUDDEN_SPEED = 1.35            # fire when speed exceeds this
SUDDEN_HOLD = 0.15
SUDDEN_CLEAR = 0.5
SUDDEN_COOLDOWN = 2.5
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


def _sample_ago(hist, now, dt):
    """Newest history item that is at least dt seconds old. Items are (t, box)."""
    for item in reversed(hist):
        if now - item[0] >= dt:
            return item
    return None


def _box_speed(hist, now, dt=SPEED_DT):
    """How fast the box center moves, in subject-sizes per second."""
    if not hist:
        return 0.0
    old = _sample_ago(hist, now, dt)
    if old is None:
        return 0.0
    t0, b0 = old
    t1, b1 = hist[-1]
    d = float(np.linalg.norm(_center(b1) - _center(b0)))
    return d / _size(b1) / max(t1 - t0, 1e-3)


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
    speed: float = 0.0
    sudden: bool = False
    sudden_since: float | None = None
    sudden_clear_since: float | None = None
    sudden_count: int = 0
    last_sudden_fire: float = -1e9
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
        humanoids = [t for t in self.tracks.values() if t.kind == "robot" and t.subtype != "agv"]
        people = [t for t in self.tracks.values() if t.kind == "person"]
        agvs = [t for t in self.tracks.values() if t.kind == "robot" and t.subtype == "agv"]
        intruders = people + agvs

        for agv in agvs:
            agv.invaded, agv.invaded_since, agv.clear_since = False, None, None
            agv.closest, agv.closest_label = None, ""

        for rob in humanoids:
            th = _size(rob.box)
            rc = _center(rob.box)
            closest, closest_label = None, ""
            invaded_raw = False
            for p in intruders:
                # same physical body tracked twice — ignore
                if _iou(rob.box, p.box) > 0.4:
                    continue
                # depth proxy: skip tiny far people relative to this robot
                if _size(p.box) < DEPTH_SIZE_MIN * th:
                    continue
                d = float(np.linalg.norm(_center(p.box) - rc)) / th
                if closest is None or d < closest:
                    closest, closest_label = d, (f"agv-{p.tid}" if p.subtype == "agv" else f"person-{p.tid}")
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
                    "detail": f"{closest_label} got too close"
                              + (f" ({closest:.2f} body-lengths)" if closest is not None else ""),
                })
            elif was and not rob.invaded:
                self.events.appendleft({
                    "t": round(self.video_t, 2),
                    "wall": time.strftime("%H:%M:%S"),
                    "robot": f"R{rob.tid}",
                    "subtype": rob.subtype,
                    "kind": "clear",
                    "detail": "has space again",
                })

    def _update_motion(self, now):
        """Sudden movement for every track (robots + people)."""
        for tr in self.tracks.values():
            tr.speed = _box_speed(tr.hist, now)
            raw = tr.speed >= SUDDEN_SPEED
            was = tr.sudden
            if raw:
                tr.sudden_clear_since = None
                if tr.sudden_since is None:
                    tr.sudden_since = now
                if now - tr.sudden_since >= SUDDEN_HOLD:
                    tr.sudden = True
            else:
                tr.sudden_since = None
                if tr.sudden_clear_since is None:
                    tr.sudden_clear_since = now
                if now - tr.sudden_clear_since >= SUDDEN_CLEAR:
                    tr.sudden = False
            if tr.sudden and not was and now - tr.last_sudden_fire > SUDDEN_COOLDOWN:
                tr.last_sudden_fire = now
                tr.sudden_count += 1
                who = f"{'R' if tr.kind == 'robot' else 'P'}{tr.tid}"
                self.events.appendleft({
                    "t": round(self.video_t, 2),
                    "wall": time.strftime("%H:%M:%S"),
                    "robot": who if tr.kind == "robot" else who,
                    "agent": who,
                    "subtype": tr.subtype,
                    "kind": "sudden",
                    "detail": f"moving fast ({tr.speed:.1f} body-lengths/s)",
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
        self._update_motion(now)
        return self.state()

    def state(self):
        robots, people = [], []
        for tr in sorted(self.tracks.values(), key=lambda t: t.tid):
            is_agv = tr.kind == "robot" and tr.subtype == "agv"
            if tr.kind != "robot":
                status = "person"
            elif is_agv:
                status = "agv"
            else:
                status = "invaded" if tr.invaded else "clear"
            item = {
                "id": tr.tid,
                "label": f"{'R' if tr.kind == 'robot' else 'P'}{tr.tid}",
                "kind": tr.kind,
                "subtype": tr.subtype,
                "conf": round(tr.conf, 2),
                "box": [round(float(x), 1) for x in tr.box.tolist()],
                "invaded": bool(tr.invaded) if tr.kind == "robot" and not is_agv else None,
                "status": status,
                "closest": None if tr.closest is None else round(tr.closest, 2),
                "closest_label": tr.closest_label,
                "invasion_count": tr.invasion_count,
                "speed": round(tr.speed, 2),
                "sudden": bool(tr.sudden),
                "sudden_count": tr.sudden_count,
            }
            (robots if tr.kind == "robot" else people).append(item)
        invaded_n = sum(1 for r in robots if r["invaded"])
        humanoid_n = sum(1 for r in robots if r["status"] != "agv")
        sudden_n = sum(1 for a in robots + people if a["sudden"])
        return {
            "video_t": round(self.video_t, 2),
            "frame": self.frame_i,
            "robots": robots,
            "people": people,
            "summary": {
                "robots": len(robots),
                "people": len(people),
                "agvs": len(robots) - humanoid_n,
                "invaded": invaded_n,
                "clear": humanoid_n - invaded_n,
                "sudden": sudden_n,
            },
            "events": list(self.events)[:40],
            "thresholds": {
                "personal_space_body_lengths": PERSONAL_SPACE,
                "hold_s": HOLD_S,
                "sudden_speed": SUDDEN_SPEED,
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
            sudden = bool(info.get("sudden"))
            is_agv = tr.kind == "robot" and tr.subtype == "agv"
            if is_agv:
                col = (0, 140, 255) if sudden else (0, 200, 230)
                tag = f"R{tr.tid} agv" + (" · RUSHING" if sudden else "")
                thick = 3 if sudden else 2
            elif tr.kind == "robot":
                invaded = bool(info.get("invaded"))
                col = (0, 0, 230) if invaded else (0, 200, 80)
                tag = f"R{tr.tid} {tr.subtype} · {'TOO CLOSE' if invaded else 'has space'}"
                if info.get("closest") is not None:
                    tag += f" ({info['closest']:.1f}bl)"
                if sudden:
                    tag += " · RUSHING"
                    col = (0, 140, 255) if not invaded else col
                thick = 3 if invaded or sudden else 2
            else:
                col = (0, 140, 255) if sudden else (220, 180, 60)
                tag = f"P{tr.tid}" + (" · RUSHING" if sudden else "")
                thick = 3 if sudden else 2
            cv2.rectangle(vis, (x1, y1), (x2, y2), col, thick)
            cv2.putText(vis, tag, (x1, max(y1 - 8, 16)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 2, cv2.LINE_AA)
            if tr.kind == "robot" and not is_agv:
                cx, cy = map(int, _center(tr.box))
                rad = int(PERSONAL_SPACE * _size(tr.box) / 2)
                cv2.circle(vis, (cx, cy), max(rad, 8), col, 1)
        banner = (f"too close {st['summary']['invaded']}  "
                  f"rushing {st['summary'].get('sudden', 0)}  "
                  f"people {st['summary']['people']}  "
                  f"robots {st['summary']['robots']} (agv {st['summary'].get('agvs', 0)})  "
                  f"t={st['video_t']:.1f}s")
        cv2.rectangle(vis, (0, 0), (vis.shape[1], 36), (20, 20, 20), -1)
        cv2.putText(vis, banner, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                    (240, 240, 240), 2, cv2.LINE_AA)
        return vis
