"""Classroom support demo: autism sensory shield, ADHD lecture rewind, dyslexia read-aloud.

One camera + one microphone feed every mode:
  * YOLO pose        joints + face points, every person, tracked over time
  * YOLOE            finds loud things by name (blender, drill, ...) BEFORE they make noise
  * Microphone       loudness reflex + YAMNet sound classifier confirm the prediction
  * Whisper          live lecture transcript for the ADHD rewind
Web pages on the same Wi-Fi: student dashboard + professor alerts.

ORIGINAL NOTES:

A YOLO pose model finds every person's body joints and face points, tracks
them over time, and simple rules turn that motion into 10 classroom triggers.
It also watches the student for reactions (hands over ears, head down,
rocking) and links each reaction to the triggers that came just before it.
Everything stays on this Mac. Events go to events/events.jsonl.

Keys (click the video window first):
  click a person   make them "the student"
  click empty spot solo test mode: the camera is the student, everyone counts
  a                auto mode: the largest person is the student
  s                simulate an overload moment (for demos)
  m                stop the calming sound
  c                switch camera
  q                quit

Other ways to run:
  .venv/bin/python sensory_demo.py --video classroom.mp4   run on a recording
  .venv/bin/python sensory_demo.py --selftest              offline crash test
"""
import collections, json, os, queue, sys, time
import numpy as np
import cv2
from ultralytics import YOLO

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
from camaccess import request_camera_access, request_mic_access, camera_names, raise_window
from calming import Calming
from server import Server
from audio import AudioMonitor, NoAudio
from loudobjects import LoudObjects, LOUD_THINGS, held_by_someone, closeness
from adhd import Attention, Transcriber, ask as adhd_ask, clock

POSE_MODEL = "yolo11n-pose.pt"   # joints + face points
DEVICE = "mps"
FRAME_W = 960
PANEL_W = 400
CHAIR_CLS = 56
KP_OK = 0.5
WIN = "Sensory trigger demo (q to quit)"
EPISODE_COOLDOWN = 60.0         # seconds before another overload alert
PREARM_AT = 0.6                 # risk level that starts the calming sound early
PREARM_COOLDOWN = 20.0
PREDICTION_WINDOW = 15.0        # a loud sound within this many seconds counts as "predicted"
STRIP_H = 200                   # info strip under the video
TRIGGER_RISK = {"stand": 0.5, "rapid": 0.5, "commotion": 0.45, "approach": 0.4,
                "crowd": 0.35, "rush": 0.6, "chair": 0.4, "too_close": 0.35, "light": 0.3}


def load_config():
    cfg = {"student_name": "Demo student", "camera_url": "", "allow_speakers": False, "adhd_away_seconds": 6}
    try:
        cfg.update(json.load(open(os.path.join(HERE, "config.json"))))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        json.dump(cfg, open(os.path.join(HERE, "config.json"), "w"), indent=2)
    except Exception:
        pass

NOSE, L_EYE, R_EYE, L_EAR, R_EAR = 0, 1, 2, 3, 4
L_SH, R_SH, L_EL, R_EL, L_WR, R_WR = 5, 6, 7, 8, 9, 10
L_HIP, R_HIP, L_KN, R_KN = 11, 12, 13, 14

# key, label shown on screen, works now?, seconds it must last before alerting
TRIGGER_DEFS = [
    ("crowd", "Crowding around the student", True, 0.5),
    ("too_close", "Someone in personal space", True, 0.3),
    ("approach", "Someone approaching fast", True, 0.0),
    ("rapid", "Rapid movement nearby", True, 0.15),
    ("commotion", "Commotion: lots of movement", True, 0.5),
    ("stand", "Person standing up", True, 0.0),
    ("rush", "Several people getting up", True, 0.0),
    ("chair", "Chair moved or tucked in", True, 0.0),
    ("light", "Flicker or sudden light change", True, 0.0),
    ("noise", "Sudden loud noise", True, 0.0),
]
RESPONSE_DEFS = [
    ("ears", "Covering ears", 0.4),
    ("head_down", "Head down", 1.0),
    ("rocking", "Rocking", 0.0),
]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- geometry
def center(b):
    return np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2])


def bh(b):
    return max(float(b[3] - b[1]), 1.0)


def bw(b):
    return max(float(b[2] - b[0]), 1.0)


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = bw(a) * bh(a) + bw(b) * bh(b) - inter
    return inter / union if union > 0 else 0.0


def sample_ago(hist, now, dt):
    """Newest history item that is at least dt seconds old."""
    for item in reversed(hist):
        if now - item[0] >= dt:
            return item
    return None


def mean_pt(k, c, idxs):
    pts = [k[i] for i in idxs if c[i] > KP_OK]
    return np.mean(pts, axis=0) if pts else None


def shoulder_w(k, c, box):
    if c[L_SH] > KP_OK and c[R_SH] > KP_OK:
        return max(float(np.linalg.norm(k[L_SH] - k[R_SH])), 10.0)
    return bh(box) * 0.25


def face_box(k, c):
    pts = [k[i] for i in (NOSE, L_EYE, R_EYE, L_EAR, R_EAR) if c[i] > KP_OK]
    if len(pts) < 3:
        return None
    pts = np.array(pts)
    x1, y1 = pts.min(0); x2, y2 = pts.max(0)
    w = max(x2 - x1, 10)
    return (int(x1 - 0.25 * w), int(y1 - 0.6 * w), int(x2 + 0.25 * w), int(y2 + 0.7 * w))


def face_width(k, c):
    if c[L_EAR] > KP_OK and c[R_EAR] > KP_OK:
        return float(np.linalg.norm(k[L_EAR] - k[R_EAR]))
    if c[L_EYE] > KP_OK and c[R_EYE] > KP_OK:
        return 2.2 * float(np.linalg.norm(k[L_EYE] - k[R_EYE]))
    return 0.0


def brighten(frame, mean):
    g = float(np.clip(np.log(110 / 255) / np.log(max(mean, 1) / 255), 0.3, 1.0))
    lut = (np.power(np.arange(256) / 255.0, g) * 255).astype(np.uint8)
    return cv2.LUT(frame, lut)


# ---------------------------------------------------------------- per-person
class Track:
    def __init__(self):
        self.hist = collections.deque(maxlen=150)  # (t, keypoints, conf, box)
        self.sat_at = -1e9
        self.last_stand = -1e9
        self.seen = 0.0


def kp_speed(tr, now, dt=0.3):
    """How fast the person's joints move, in body-heights per second."""
    old = sample_ago(tr.hist, now, dt)
    if old is None:
        return 0.0
    t0, k0, c0, b0 = old
    t1, k1, c1, b1 = tr.hist[-1]
    m = (c0 > KP_OK) & (c1 > KP_OK)
    if m.sum() >= 3:
        d = float(np.percentile(np.linalg.norm(k1[m] - k0[m], axis=1), 90))
    else:
        d = float(np.linalg.norm(center(b1) - center(b0)))
    return d / bh(b1) / max(t1 - t0, 1e-3)


def growth(tr, now, dt=0.5):
    """How fast the person is getting bigger on screen (walking toward us)."""
    old = sample_ago(tr.hist, now, dt)
    if old is None:
        return 0.0
    t0, _, _, b0 = old
    t1, _, _, b1 = tr.hist[-1]
    ratio = min(bh(b1) / bh(b0), bw(b1) / bw(b0))
    return (ratio - 1) / max(t1 - t0, 1e-3)


def posture(k, c):
    sh = mean_pt(k, c, (L_SH, R_SH)); hip = mean_pt(k, c, (L_HIP, R_HIP)); kn = mean_pt(k, c, (L_KN, R_KN))
    if sh is None or hip is None or kn is None:
        return None
    torso = hip[1] - sh[1]
    if torso <= 5:
        return None
    r = (kn[1] - hip[1]) / torso   # thighs flat = sitting, thighs vertical = standing
    return "stand" if r > 0.6 else "sit" if r < 0.35 else None


def rocking_score(tr, now, window=4.0):
    xs, ys, ss = [], [], []
    for t, k, c, b in tr.hist:
        if now - t <= window and c[L_SH] > KP_OK and c[R_SH] > KP_OK:
            m = (k[L_SH] + k[R_SH]) / 2
            xs.append(m[0]); ys.append(m[1]); ss.append(max(np.linalg.norm(k[L_SH] - k[R_SH]), 10))
    if len(xs) < 20:
        return 0
    sw = float(np.median(ss))
    best = 0
    for sig in (np.array(xs) / sw, np.array(ys) / sw, np.array(ss) / sw):
        d = np.convolve(sig - sig.mean(), np.ones(3) / 3, mode="same")
        p2p = np.percentile(d, 90) - np.percentile(d, 10)
        if p2p < 0.12:
            continue
        th, state, flips = 0.25 * p2p, 0, 0
        for v in d:
            s = 1 if v > th else -1 if v < -th else 0
            if s and s != state:
                if state:
                    flips += 1
                state = s
        best = max(best, flips)
    return best


# ---------------------------------------------------------------- alerts
class Trigger:
    def __init__(self, key, label, live, hold, cooldown=3.0):
        self.key, self.label, self.live, self.hold, self.cooldown = key, label, live, hold, cooldown
        self.on_since = None
        self.alert_until = 0.0
        self.last_fire = -1e9
        self.value = "" if live else "planned"
        self.count = 0

    def update(self, active, now, value=""):
        self.value = value
        if not active:
            self.on_since = None
            return False
        if self.on_since is None:
            self.on_since = now
        if now - self.on_since >= self.hold:
            self.alert_until = now + 2.5
            if now - self.last_fire > self.cooldown:
                self.last_fire = now
                self.count += 1
                return True
        return False

    def alerting(self, now):
        return now < self.alert_until


class Chairs:
    """Remembers chair boxes and reports chairs that slid between checks."""
    def __init__(self):
        self.prev = []

    def update(self, boxes, now):
        moved = []
        for b in boxes:
            best, bd = None, 1e9
            for t0, p in self.prev:
                size = bh(b) / bh(p)
                d = float(np.linalg.norm(center(b) - center(p)))
                if 0.75 < size < 1.33 and d < bh(p) and d < bd:
                    best, bd = (t0, p), d
            if best and bd > 0.2 * bh(best[1]) and now - best[0] < 1.0:
                moved.append(b)
        self.prev = [(now, b) for b in boxes]
        return moved


def put(img, text, org, scale=0.5, color=(230, 230, 230), th=1):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, th, cv2.LINE_AA)


# ---------------------------------------------------------------- the demo
class Demo:
    def __init__(self, event_dir="events", use_audio=True):
        self.cfg = load_config()
        self.pose = YOLO(POSE_MODEL)
        self.loud = LoudObjects(DEVICE)
        self.tracks = {}
        self.trig = {k: Trigger(k, l, live, h) for k, l, live, h in TRIGGER_DEFS}
        self.resp = {k: Trigger(k, l, True, h, cooldown=5.0) for k, l, h in RESPONSE_DEFS}
        self.mode, self.target_id, self.click = "auto", None, None
        self.chairs, self.chair_boxes, self.moved_chairs = Chairs(), [], []
        self.objects, self.obj_seen = [], collections.defaultdict(lambda: collections.deque(maxlen=10))
        self.frame_i, self.fps = 0, 0.0
        self.light = collections.deque(maxlen=120)
        self.prev_small = None
        self.stand_events = collections.deque(maxlen=30)
        self.recent = collections.deque(maxlen=100)        # (t, trigger label)
        self.last_link = "none yet"
        self.event_dir = event_dir
        os.makedirs(event_dir, exist_ok=True)
        self.evf = open(os.path.join(event_dir, "events.jsonl"), "a")
        self.events = collections.deque(maxlen=40)
        self.next_event_id = 1
        self.fw = FRAME_W
        # sound out, microphone, ADHD
        self.calm = Calming()
        self.calm.allow_speakers = bool(self.cfg.get("allow_speakers"))
        self.audio = AudioMonitor() if use_audio else NoAudio()
        if self.audio.error:
            log("audio:", self.audio.error)
        self.attention = Attention(float(self.cfg.get("adhd_away_seconds", 6)))
        self.session_start = time.time()
        self.transcriber = Transcriber(self.audio)
        # risk + predictions
        self.risk, self.risk_reason, self.risk_parts = 0.0, "", []
        self.prearm_at, self.prearm_reason = -1e9, ""
        self.pred_open, self.hits, self.misses, self.leads, self.last_pred = [], 0, 0, [], ""
        # overload
        self.episode, self.episode_at, self.episode_count = None, -1e9, 0
        # reading (dyslexia)
        self.reading, self.lean_count, self.face_base, self.lean_since, self.last_lean = False, 0, None, None, -1e9
        # feedback profile
        self.profile_path = os.path.join(HERE, "profile.json")
        try:
            self.profile = json.load(open(self.profile_path))
        except Exception:
            self.profile = {}
        self.inbox = queue.Queue()
        self.recording = False
        self._state = "{}"
        self.last_publish = 0.0
        self.server = Server(self.cfg.get("student_name", "Demo student"), self)

    # ------------------------------------------------------------ bridge (web)
    def state_json(self):
        return self._state

    def feedback(self, eid, verdict):
        self.inbox.put(("feedback", eid, verdict))

    def ask(self, q):
        return adhd_ask(q, self.transcriber.recent(400), [dict(d) for d in self.attention.drops])

    def say(self, text):
        return self.calm.say(text)

    def settings(self, d):
        if "allow_speakers" in d:
            self.calm.allow_speakers = bool(d["allow_speakers"])
            self.cfg["allow_speakers"] = self.calm.allow_speakers
            save_config(self.cfg)
        if "reading" in d:
            self.reading = bool(d["reading"])

    def simulate(self, what):
        self.inbox.put(("simulate", what, None))

    def on_click(self, x, y):
        if x < self.fw and y < getattr(self, "fh", 10 ** 6):
            self.click = (x, y)

    # ------------------------------------------------------------ profile
    def mult(self, pkey):
        p = self.profile.get(pkey)
        if not p:
            return 1.0
        return float(np.clip((1 + p["bothered"]) / (1 + p["fine"]), 0.5, 2.0))

    def apply_feedback(self, eid, verdict):
        ev = next((e for e in self.events if e["id"] == eid), None)
        if ev is None or not ev.get("pkey") or verdict not in ("bothered", "fine"):
            return
        ev["feedback"] = verdict
        p = self.profile.setdefault(ev["pkey"], {"label": ev["plabel"], "bothered": 0, "fine": 0})
        p[verdict] += 1
        json.dump(self.profile, open(self.profile_path, "w"), indent=2)
        self.write_event({"kind": "feedback", "key": ev["pkey"], "label": ev["plabel"], "verdict": verdict})
        log("FEEDBACK", ev["plabel"], verdict, f"-> sensitivity x{self.mult(ev['pkey']):.1f}")

    def latest_feedback_target(self):
        return next((e for e in reversed(self.events) if e.get("pkey") and not e.get("feedback")), None)

    # ------------------------------------------------------------ events
    def write_event(self, ev):
        ev = dict(ev, time=time.strftime("%Y-%m-%d %H:%M:%S"))
        self.evf.write(json.dumps(ev) + "\n"); self.evf.flush()

    def log_event(self, kind, key, label, frame, extra=None, pkey=None, plabel=None, detail=""):
        ev = {"kind": kind, "key": key, "label": label}
        if extra:
            ev.update(extra)
        if frame is not None and kind in ("trigger", "overload", "prediction", "loud sound"):
            fn = os.path.join(self.event_dir, f"{time.strftime('%Y%m%d-%H%M%S')}-{key}.jpg".replace(":", "-").replace(" ", "_"))
            cv2.imwrite(fn, frame)
            ev["snapshot"] = fn
        self.write_event(ev)
        self.events.append({"id": self.next_event_id, "t": time.time(), "time": clock(time.time()), "kind": kind,
                            "label": label, "detail": detail, "pkey": pkey, "plabel": plabel or label, "feedback": None})
        self.next_event_id += 1
        log("EVENT", kind, label, detail)

    # ------------------------------------------------------------ main step
    def process(self, frame, now):
        H, W = frame.shape[:2]
        self.fw, self.fh = W, H
        self.frame_i += 1
        gray_raw = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        raw_mean = float(gray_raw.mean())
        if raw_mean < 70:
            frame = brighten(frame, raw_mean)

        while not self.inbox.empty():
            kind, a, b = self.inbox.get()
            if kind == "feedback":
                self.apply_feedback(a, b)
            elif kind == "simulate" and a == "overload":
                self.force = True
            elif kind == "simulate" and a == "stop":
                self.calm.stop()
            elif kind == "simulate" and a == "lean":
                self.lean_count += 1

        # 1) people, joints, face points, stable ids
        res = self.pose.track(frame, persist=True, device=DEVICE, conf=0.35, verbose=False)[0]
        people = []
        if res.boxes is not None and len(res.boxes):
            boxes = res.boxes.xyxy.cpu().numpy()
            ids = (res.boxes.id.cpu().numpy().astype(int) if res.boxes.id is not None
                   else np.arange(len(boxes)) + 100000)
            kxy = res.keypoints.xy.cpu().numpy()
            kc = (res.keypoints.conf.cpu().numpy() if res.keypoints.conf is not None
                  else np.ones(kxy.shape[:2]))
            for i in range(len(boxes)):
                tid = int(ids[i])
                tr = self.tracks.setdefault(tid, Track())
                tr.hist.append((now, kxy[i], kc[i], boxes[i]))
                tr.seen = now
                people.append((tid, boxes[i], kxy[i], kc[i], tr))
        for tid in [t for t, tr in self.tracks.items() if now - tr.seen > 3.0]:
            del self.tracks[tid]

        # 2) who is "the student"
        if self.click is not None:
            x, y = self.click; self.click = None
            hit = [p for p in people if p[1][0] <= x <= p[1][2] and p[1][1] <= y <= p[1][3]]
            if hit:
                self.mode, self.target_id = "pick", min(hit, key=lambda p: bw(p[1]) * bh(p[1]))[0]
            else:
                self.mode, self.target_id = "solo", None
        if self.mode == "pick" and self.target_id not in self.tracks:
            self.mode = "auto"
        if self.mode == "auto":
            self.target_id = max(people, key=lambda p: bw(p[1]) * bh(p[1]))[0] if people else None
        if self.mode == "solo":
            self.target_id = None
        target = next((p for p in people if p[0] == self.target_id), None)
        others = [p for p in people if target is None or p[0] != target[0]]
        subject = target if target is not None else (
            max(people, key=lambda p: bw(p[1]) * bh(p[1])) if people else None)

        # 3) measure every other person
        th = bh(target[1]) if target is not None else H
        tc = center(target[1]) if target is not None else np.array([W / 2, H])
        near, too_close, vicinity, closest = [], [], [], None
        speeds, grows, stood_now = {}, {}, []
        for tid, b, k, c, tr in others:
            speeds[tid] = kp_speed(tr, now)
            grows[tid] = growth(tr, now)
            if target is not None:
                d = float(np.linalg.norm(center(b) - tc)) / th
                # a flat image has no depth: someone far behind the student looks
                # small, so only people at least half the student's size count as close
                depth_ok = bh(b) >= 0.5 * th
                if depth_ok:
                    closest = d if closest is None else min(closest, d)
                if depth_ok and (d < 1.3 or iou(b, target[1]) > 0.05): near.append(tid)
                if depth_ok and (d < 0.7 or iou(b, target[1]) > 0.15): too_close.append(tid)
                if d < 2.5 and bh(b) >= 0.3 * th: vicinity.append(tid)
            else:
                frac = bh(b) / H
                closest = frac if closest is None else max(closest, frac)
                if frac > 0.5: near.append(tid)
                if face_width(k, c) > 0.4 * W or (frac > 0.95 and bw(b) > 0.85 * W): too_close.append(tid)
                vicinity.append(tid)
            if self.check_stand(tr, k, c, b, now, H) and tid in vicinity:
                stood_now.append(tid)
                self.stand_events.append((now, tid))

        # 4) whole-scene motion and light
        small = cv2.GaussianBlur(cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90)), (5, 5), 0)
        motion = 0.0
        if self.prev_small is not None:
            mask = cv2.absdiff(small, self.prev_small) > 25
            if target is not None:
                x1, y1, x2, y2 = (target[1] * [160 / W, 90 / H, 160 / W, 90 / H]).astype(int)
                mask[max(y1, 0):y2, max(x1, 0):x2] = False
            motion = float(mask.mean())
        self.prev_small = small
        self.light.append((now, raw_mean))
        old = sample_ago(self.light, now, 0.3)
        sudden = old is not None and abs(raw_mean - old[1]) > 35
        win = [v for t, v in self.light if now - t <= 1.0]
        diffs = [d for d in np.diff(win) if abs(d) > 6] if len(win) > 3 else []
        flips = sum(1 for a, b2 in zip(diffs, diffs[1:]) if a * b2 < 0)
        flicker = flips >= 3 and (max(win) - min(win)) > 20

        # 5) loud things, chairs, phones (YOLOE every 2nd frame)
        moved = []
        if self.frame_i % 2 == 0:
            dets = self.loud.detect(frame)
            self.objects = []
            for name, conf, box in dets:
                self.obj_seen[name].append(now)
                held = held_by_someone(box, people) if name in LOUD_THINGS else False
                self.objects.append((name, conf, box, held))
            self.chair_boxes = [b for n, c, b, h in self.objects if n == "chair"]
            moved = self.chairs.update(list(self.chair_boxes), now)
            if target is not None:
                moved = [b for b in moved if np.linalg.norm(center(b) - tc) / th < 3.0]
            self.moved_chairs = moved

        def present(name):
            return sum(1 for t in self.obj_seen[name] if now - t <= 1.2) >= 2

        # 6) the 10 triggers
        vic_speeds = [speeds[t] for t in vicinity]
        fastest = max(vic_speeds, default=0.0)
        movers = sum(1 for s in vic_speeds if s > 0.6)
        fastest_grow = max([grows[t] for t in vicinity], default=0.0)
        recent_standers = {tid for t, tid in self.stand_events if now - t <= 6.0}
        close_txt = ("closest: --" if closest is None else
                     f"closest: {closest:.1f} body-lengths" if target is not None else f"biggest: {closest:.0%} of screen")
        noise, noise_desc = self.audio.loud_event(now)
        checks = {
            "crowd": (len(near) >= 3, f"people close: {len(near)} (alert at 3)"),
            "too_close": (len(too_close) > 0, close_txt),
            "approach": (fastest_grow > 0.6, f"fastest approach: {fastest_grow:.1f}"),
            "rapid": (fastest > 1.5, f"fastest move: {fastest:.1f} (alert at 1.5)"),
            "commotion": (movers >= 3 or motion > 0.3, f"moving: {movers}, scene motion {motion:.0%}"),
            "stand": (len(stood_now) > 0, f"stand-ups last 6s: {len(recent_standers)}"),
            "rush": (len(stood_now) > 0 and len(recent_standers) >= 2, f"people up in 6s: {len(recent_standers)}"),
            "chair": (len(moved) > 0, f"chairs seen: {len(self.chair_boxes)}"),
            "light": (sudden or flicker, f"brightness: {raw_mean:.0f}"),
            "noise": (noise, (noise_desc or f"{self.audio.db:.0f} dB, {self.audio.label or 'quiet'}") if self.audio.ok
                      else "microphone off"),
        }
        for key, (active, val) in checks.items():
            t = self.trig[key]
            if t.update(active, now, val):
                self.recent.append((now, t.label))
                if key == "noise":
                    self.on_loud_sound(now, noise_desc, frame)
                else:
                    self.log_event("trigger", key, t.label, frame, {"detail": val}, pkey=key, detail=val)

        # 7) risk meter: what is likely to get loud or overwhelming in the next few seconds
        parts = []
        for name, conf, box, held in self.objects:
            if name in LOUD_THINGS and present(name):
                r = (LOUD_THINGS[name] * min(1.0, conf / 0.6) * closeness(box, H)
                     * (1.25 if held else 1.0) * self.mult("object:" + name))
                parts.append((min(r, 0.98), f"{name} {'in someone' + chr(39) + 's hand' if held else 'in view'}", "object:" + name))
        for key, base in TRIGGER_RISK.items():
            if self.trig[key].alerting(now):
                parts.append((min(base * self.mult(key), 0.95), self.trig[key].label.lower(), key))
        raw = 1 - float(np.prod([1 - r for r, _, _ in parts])) if parts else 0.0
        self.risk = 0.6 * self.risk + 0.4 * raw if raw > self.risk else 0.97 * self.risk + 0.03 * raw
        parts.sort(key=lambda p: -p[0])
        self.risk_parts = parts
        self.risk_reason = parts[0][1] if parts else ""
        if self.risk >= PREARM_AT and now - self.prearm_at > PREARM_COOLDOWN:
            self.prearm(now, frame)
        self.pred_open = [p for p in self.pred_open if now - p["t"] <= PREDICTION_WINDOW]

        # 8) student reactions, linked to recent triggers
        resp_state = {"ears": (False, ""), "head_down": (False, ""), "rocking": (False, "")}
        if subject is not None:
            _, b, k, c, tr = subject
            sw = shoulder_w(k, c, b)
            hands = 0
            for wr in (L_WR, R_WR):
                if c[wr] > 0.4:
                    spots = [k[i] for i in (L_EAR, R_EAR, L_EYE, R_EYE) if c[i] > 0.4]
                    if spots and min(np.linalg.norm(k[wr] - s) for s in spots) < 0.6 * sw:
                        hands += 1
            resp_state["ears"] = (hands >= 1, f"hands at ears: {hands}")
            shm = mean_pt(k, c, (L_SH, R_SH))
            if shm is not None and c[NOSE] > KP_OK:
                gap = (shm[1] - k[NOSE][1]) / sw
                resp_state["head_down"] = (gap < 0.15, f"nose above shoulders: {gap:.2f}")
            rs = rocking_score(tr, now)
            resp_state["rocking"] = (rs >= 4, f"back-and-forth swings: {rs}")
        for key, (active, val) in resp_state.items():
            r = self.resp[key]
            if r.update(active, now, val):
                causes = sorted({lbl for t, lbl in self.recent if now - t <= 20})
                self.last_link = f"{r.label} <- " + (", ".join(causes) if causes else "no trigger seen")
                self.log_event("reaction", key, r.label, frame, {"linked_triggers": causes},
                               detail=("after: " + ", ".join(causes)) if causes else "")

        # 9) overload moment: calming sound + tell the professor
        firing = [t.label for t in self.trig.values() if t.alerting(now)]
        reacting = [self.resp[k].label for k in ("ears", "rocking") if self.resp[k].alerting(now)]
        if self.resp["head_down"].alerting(now) and firing:
            reacting.append("Head down")
        if getattr(self, "force", False):
            reacting, self.force, self.episode_at = ["demo (simulated)"], False, -1e9
        if reacting and now - self.episode_at > EPISODE_COOLDOWN:
            self.start_episode(reacting, frame, now)

        # 10) ADHD attention
        phone_near = False
        if subject is not None:
            sb = subject[1]
            ex1, ey1, ex2, ey2 = sb[0] - 0.3 * bw(sb), sb[1] - 0.3 * bh(sb), sb[2] + 0.3 * bw(sb), sb[3] + 0.3 * bh(sb)
            for name, conf, box, held in self.objects:
                cx, cy = center(box)
                if name == "cell phone" and ex1 <= cx <= ex2 and ey1 <= cy <= ey2:
                    phone_near = True
        drop = self.attention.update(now, subject, phone_near)
        if drop:
            self.log_event("attention drop", "attention", f"Attention drop: {drop['reason']}", None, detail="ADHD rewind will mark this")

        # 11) dyslexia: lean in toward the screen = "this is hard, read it to me"
        if self.reading and subject is not None:
            fwid = face_width(subject[2], subject[3])
            if fwid > 0:
                if self.face_base is None:
                    self.face_base = fwid
                leaning = fwid > 1.3 * self.face_base
                if not leaning:
                    self.face_base = 0.97 * self.face_base + 0.03 * fwid
                    self.lean_since = None
                elif self.lean_since is None:
                    self.lean_since = now
                elif now - self.lean_since > 1.0 and now - self.last_lean > 6.0:
                    self.lean_count += 1
                    self.last_lean = now
                    self.log_event("reading help", "lean", "Leaned in: reading paragraph aloud", None)

        if now - self.last_publish > 0.5:
            self.publish(now)
            self.last_publish = now
        return self.draw(res, frame, people, target, too_close, raw_mean, now)

    # ------------------------------------------------------------ actions
    def prearm(self, now, frame):
        self.prearm_at, self.prearm_reason = now, self.risk_reason
        where = self.calm.play()
        self.pred_open.append({"t": now, "reason": self.risk_reason})
        top = self.risk_parts[0] if self.risk_parts else (0, self.risk_reason, None)
        self.log_event("prediction", "prediction", f"Heads up: {self.risk_reason}", frame,
                       {"risk": round(self.risk, 2), "sound": where}, pkey=top[2],
                       plabel=(top[2] or "").replace("object:", "").capitalize() or self.risk_reason,
                       detail=f"risk {self.risk:.0%}, calming sound " + (f"on {where}" if where else "held back (no AirPods)"))

    def on_loud_sound(self, now, desc, frame):
        label = desc.split(" (")[0]
        if self.pred_open:
            first = min(self.pred_open, key=lambda p: p["t"])
            lead = now - first["t"]
            self.hits += 1
            self.leads.append(lead)
            self.last_pred = f"Last: {first['reason']} predicted {label} {lead:.1f} s early"
            self.pred_open = []
            detail = f"predicted {lead:.1f} s early from: {first['reason']}"
        else:
            self.misses += 1
            self.last_pred = f"Last: {label} with no warning"
            detail = "no early warning"
            self.calm.play()     # react anyway
        self.log_event("loud sound", "noise", label.capitalize(), frame, {"detail": desc}, pkey="sound:" + label,
                       plabel=label.capitalize() + " sound", detail=detail)

    def start_episode(self, reacting, frame, now):
        causes = sorted({lbl for t, lbl in self.recent if now - t <= 20})
        where = self.calm.play()
        sound = (f"Calming sound playing on {where}" if where else
                 f"Calming sound held back: no AirPods connected (sound output is {self.calm.output_name})")
        reason = "Signs of overload: " + ", ".join(r.lower() for r in reacting)
        aid = self.server.notify(reason, causes, sound)
        self.episode = {"at": now, "id": aid, "where": where, "reason": reason, "sound": sound}
        self.episode_at = now
        self.episode_count += 1
        self.log_event("overload", "overload", reason, frame, {"linked_triggers": causes, "sound": sound},
                       detail="professor notified" + (f" · after: {', '.join(causes)}" if causes else ""))

    def check_stand(self, tr, k, c, b, now, H):
        p = posture(k, c)
        if p == "sit":
            tr.sat_at = now
        stood = p == "stand" and now - tr.sat_at < 2.0
        old = sample_ago(tr.hist, now, 1.0)
        if old is not None and bh(b) / bh(old[3]) < 1.3:
            t0, k0, c0, b0 = old
            for idxs in ((L_SH, R_SH), (NOSE,)):
                a, z = mean_pt(k0, c0, idxs), mean_pt(k, c, idxs)
                if a is not None and z is not None:
                    rise = a[1] - z[1]
                    if rise > 0.22 * bh(b0) and rise > 0.08 * H:
                        stood = True
                    break
        if stood and now - tr.last_stand > 3.0:
            tr.last_stand = now
            return True
        return False

    # ------------------------------------------------------------ dashboard state
    def publish(self, now):
        ep = self.episode
        active = bool(ep and (now - ep["at"] < 45 or self.calm.playing()))
        drops = self.attention.drops
        segs = self.transcriber.recent(80)
        st = {
            "t": now, "student": self.cfg.get("student_name", "Demo student"), "fps": round(self.fps),
            "mode": {"auto": "biggest person", "pick": f"person {self.target_id}", "solo": "solo test"}[self.mode],
            "mic": {"ok": self.audio.ok, "error": self.audio.error, "db": self.audio.db,
                    "label": self.audio.label},
            "sound_out": {"name": self.calm.output_name, "headphones": self.calm.headphones,
                          "allow_speakers": self.calm.allow_speakers, "playing": self.calm.playing()},
            "risk": {"value": self.risk, "reason": self.risk_reason,
                     "prearmed": now - self.prearm_at < 8, "prearm_reason": self.prearm_reason},
            "predictions": {"hits": self.hits, "misses": self.misses,
                            "avg_lead": float(np.mean(self.leads)) if self.leads else 0.0, "last": self.last_pred},
            "triggers": [{"key": t.key, "label": t.label, "live": t.live, "alerting": t.alerting(now),
                          "count": t.count, "value": t.value} for t in self.trig.values()],
            "reactions": [{"label": r.label, "alerting": r.alerting(now), "count": r.count} for r in self.resp.values()],
            "overload": {"active": active, "reason": ep["reason"] if ep else "", "sound": ep["sound"] if ep else "",
                         "acked": self.server.acked(ep["id"]) if ep else False, "count": self.episode_count},
            "events": [dict(e, fb=bool(e.get("pkey"))) for e in reversed(self.events)][:25],
            "profile": sorted([{"key": k, "label": v["label"], "bothered": v["bothered"], "fine": v["fine"],
                                "mult": self.mult(k)} for k, v in self.profile.items()], key=lambda p: -p["mult"]),
            "attention": {"state": self.attention.state, "reason": self.attention.reason,
                          "focused_pct": self.attention.focused_pct(), "session_start": self.session_start,
                          "drops": [{"start": d["start"], "end": d["end"],
                                     "label": f"{clock(d['start'])} for {((d['end'] or now) - d['start']):.0f} s, {d['reason']}"}
                                    for d in drops]},
            "transcriber": self.transcriber.status,
            "transcript": [{"time": clock(s["t"]), "text": s["text"],
                            "missed": any(d["start"] <= s["t"] <= (d["end"] or now) for d in drops)} for s in segs],
            "reading": {"active": self.reading, "lean_count": self.lean_count},
            "recording": self.recording, "professor_url": self.server.prof_url,
            "objects": [[n, round(c, 2), bool(h)] for n, c, b, h in self.objects],
        }
        self._state = json.dumps(st)

    # ------------------------------------------------------------ drawing
    def draw(self, res, frame, people, target, too_close, raw_mean, now):
        H, W = frame.shape[:2]
        vis = res.plot(conf=False, line_width=2, font_size=0.5) if people else frame.copy()
        for name, conf, box, held in self.objects:
            x1, y1, x2, y2 = map(int, box)
            if name == "chair":
                moved = any(np.allclose(box, m) for m in self.moved_chairs)
                col, txt = ((0, 140, 255), "chair MOVED") if moved else ((255, 120, 0), "chair")
            elif name == "cell phone":
                col, txt = (200, 80, 200), "phone"
            else:
                col, txt = (0, 90, 255), f"LOUD: {name}" + (" (held)" if held else "")
            cv2.rectangle(vis, (x1, y1), (x2, y2), col, 2)
            put(vis, txt, (x1, max(y1 - 5, 12)), 0.5, col, 2 if name in LOUD_THINGS else 1)
        for tid, b, k, c, tr in people:
            fb = face_box(k, c)
            if fb:
                cv2.rectangle(vis, fb[:2], fb[2:], (255, 255, 0), 1)
            if tid in too_close:
                x1, y1, x2, y2 = map(int, b)
                cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 0, 255), 4)
        if target is not None:
            x1, y1, x2, y2 = map(int, target[1])
            cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 230, 255), 4)
            put(vis, "STUDENT", (x1 + 6, y1 + 24), 0.8, (0, 230, 255), 2)
        if raw_mean < 5:
            put(vis, "Camera image is black: lens covered or wrong camera. Press C.", (10, H - 60), 0.6, (0, 0, 255), 2)
        firing = [t.label for t in self.trig.values() if t.alerting(now)]
        y_ban = 0
        if firing:
            cv2.rectangle(vis, (0, 0), (W, 34), (0, 0, 200), -1)
            put(vis, "TRIGGER: " + " | ".join(firing)[:95], (10, 23), 0.6, (255, 255, 255), 2)
            y_ban = 34
        if now - self.prearm_at < 8:
            cv2.rectangle(vis, (0, y_ban), (W, y_ban + 34), (0, 120, 230), -1)
            put(vis, f"HEADS UP: {self.prearm_reason} - may get loud. Calming sound started early.", (10, y_ban + 23), 0.6, (255, 255, 255), 2)
        ep = self.episode
        if ep and (now - ep["at"] < 45 or self.calm.playing()):
            cv2.rectangle(vis, (0, H - 40), (W, H), (140, 60, 20), -1)
            msg = ("calming sound on " + ep["where"]) if ep["where"] else "no AirPods: sound held back"
            ok = self.server.acked(ep["id"])
            put(vis, f"OVERLOAD SUPPORT: {msg} | professor {'ON THE WAY' if ok else 'notified'}", (10, H - 14), 0.6, (255, 255, 255), 2)

        strip = np.full((STRIP_H, W, 3), 32, np.uint8)
        cw = W // 3
        # column 1: triggers
        put(strip, "10 SENSORY TRIGGERS", (12, 20), 0.5, (255, 255, 255), 1)
        for i, t in enumerate(self.trig.values()):
            y = 38 + i * 16
            col = (90, 90, 90) if not t.live else (0, 0, 255) if t.alerting(now) else (0, 170, 0)
            cv2.circle(strip, (18, y - 4), 5, col, -1)
            put(strip, t.label + (f" x{t.count}" if t.count else ""), (30, y), 0.4)
        # column 2: risk, predictions, sound, reactions
        x = cw + 10
        put(strip, "LOUD-MOMENT RISK", (x, 20), 0.5, (255, 255, 255), 1)
        cv2.rectangle(strip, (x, 30), (x + cw - 30, 44), (70, 70, 70), -1)
        rc = (0, 0, 230) if self.risk >= PREARM_AT else (0, 150, 255) if self.risk >= 0.35 else (0, 170, 0)
        cv2.rectangle(strip, (x, 30), (x + int((cw - 30) * min(self.risk, 1)), 44), rc, -1)
        put(strip, f"{self.risk:.0%}  {self.risk_reason}"[:44], (x, 62), 0.42)
        put(strip, f"Predicted early: {self.hits}   missed: {self.misses}" +
            (f"   avg {np.mean(self.leads):.1f}s" if self.leads else ""), (x, 82), 0.42, (0, 230, 255))
        snd = f"Mic: {self.audio.db:.0f} dB  {self.audio.label}"[:44] if self.audio.ok else "Mic: off"
        put(strip, snd, (x, 102), 0.42, (200, 200, 200))
        put(strip, "STUDENT REACTIONS", (x, 126), 0.5, (255, 255, 255), 1)
        for i, r in enumerate(self.resp.values()):
            y = 144 + i * 16
            cv2.circle(strip, (x + 6, y - 4), 5, (0, 0, 255) if r.alerting(now) else (0, 170, 0), -1)
            put(strip, r.label + (f" x{r.count}" if r.count else ""), (x + 18, y), 0.4)
        # column 3: overload, professor, attention, keys
        x = 2 * cw + 10
        put(strip, "SUPPORT", (x, 20), 0.5, (255, 255, 255), 1)
        if self.calm.playing():
            s, col = f"Calming sound: on {self.calm.output_name}", (255, 200, 120)
        elif self.calm.can_play():
            s, col = f"Sound ready: {self.calm.output_name}", (0, 200, 0)
        else:
            s, col = "Sound: put in AirPods", (0, 165, 255)
        put(strip, s[:40], (x, 40), 0.42, col)
        if ep:
            ok = self.server.acked(ep["id"])
            put(strip, "Professor: " + ("ON THE WAY" if ok else "notified, waiting"), (x, 58), 0.42,
                (0, 220, 0) if ok else (0, 200, 255))
        else:
            put(strip, "Professor: no alerts yet", (x, 58), 0.42, (170, 170, 170))
        a = self.attention
        put(strip, f"Attention (ADHD): {'focused' if a.state == 'focused' else 'away - ' + a.reason}"[:42], (x, 80), 0.42,
            (0, 200, 0) if a.state == "focused" else (0, 165, 255))
        put(strip, f"Drops: {len(a.drops)}   focused {a.focused_pct():.0f}%", (x, 98), 0.42, (200, 200, 200))
        put(strip, ("Linked: " + self.last_link)[:44], (x, 118), 0.38, (0, 230, 255))
        if self.recording:
            cv2.circle(strip, (x + 6, 136), 6, (0, 0, 255), -1)
            put(strip, "Recording backup video (r to stop)", (x + 18, 140), 0.4, (0, 0, 255))
        put(strip, "Dashboard: see run.log / browser", (x, 160), 0.38, (150, 150, 150))
        put(strip, "s=overload m=mute b/f=bothered/fine", (x, 178), 0.38, (150, 150, 150))
        put(strip, "l=lean r=record a=auto c=cam q=quit", (x, 194), 0.38, (150, 150, 150))
        return np.vstack([vis, strip])


# ---------------------------------------------------------------- camera
def fit(frame):
    h, w = frame.shape[:2]
    if w == FRAME_W:
        return frame
    return cv2.resize(frame, (FRAME_W, int(h * FRAME_W / w)))


def probe_cameras():
    """Open each camera, measure brightness, and keep the one that shows a real picture."""
    log("cameras macOS reports:", camera_names())
    found = []
    for idx in range(3):
        cap = cv2.VideoCapture(idx, cv2.CAP_AVFOUNDATION)
        if not cap.isOpened():
            cap.release()
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        vals, t0 = [], time.time()
        while time.time() - t0 < 1.5:
            ok, f = cap.read()
            if ok:
                vals.append(float(f.mean()))
        b = float(np.mean(vals[-10:])) if vals else -1.0
        log(f"camera index {idx}: {len(vals)} frames, brightness {b:.1f}")
        found.append([idx, b, cap])
    if not found:
        return [], None, None
    best = max(found, key=lambda f: f[1])
    for f in found:
        if f is not best:
            f[2].release()
    log(f"using camera index {best[0]}")
    return [f[0] for f in found], best[2], best[0]


def selftest():
    demo = Demo(event_dir="events_selftest", use_audio=False)
    demo.profile, demo.profile_path = {}, os.path.join("events_selftest", "profile.json")
    img = fit(cv2.imread("bus.jpg"))
    canvas = None
    for i in range(60):
        f = np.roll(img, i * 4, axis=1)
        if 30 <= i < 40 and i % 2:
            f = (f * 0.3).astype(np.uint8)  # flicker
        if i == 45:
            demo.simulate("overload")
        canvas = demo.process(f, 1000 + i * 0.05)
    demo.publish(1003)
    st = json.loads(demo.state_json())
    if st["events"]:
        demo.apply_feedback(next(e["id"] for e in st["events"] if e["fb"]), "bothered")
    # risk -> early warning -> loud sound = "predicted early"
    demo.risk_parts = [(0.9, "blender in someone's hand", "object:blender")]
    demo.risk, demo.risk_reason = 0.9, "blender in someone's hand"
    demo.prearm(time.time() - 2.0, None)
    demo.on_loud_sound(time.time(), "Blender (91%)", None)
    demo.on_loud_sound(time.time(), "Dog (80%)", None)
    print("predictions: hits", demo.hits, "misses", demo.misses, "|", demo.last_pred)
    cv2.imwrite("selftest.png", canvas)
    print("people tracked:", len(demo.tracks), "| objects:", [(n, round(c, 2)) for n, c, b, h in demo.objects])
    for t in demo.trig.values():
        print(f"  {t.label:34s} fired {t.count}x  [{t.value}]")
    print("risk", round(demo.risk, 2), demo.risk_reason, "| overloads", demo.episode_count, "| profile", demo.profile)
    print("state keys:", sorted(st))
    print("selftest ok -> selftest.png")


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest()
    cfg = load_config()
    video = args[args.index("--video") + 1] if "--video" in args else (cfg.get("camera_url") or None)
    if video:
        log("video source:", video)
        cap, cams, cur = cv2.VideoCapture(video), [], None
    else:
        if not request_camera_access():
            sys.exit("Camera access was denied. Allow it in System Settings > Privacy & Security > Camera.")
        cams, cap, cur = probe_cameras()
        if cap is None:
            sys.exit("No camera could be opened.")
    mic_ok = request_mic_access()
    log("microphone permission:", "granted" if mic_ok else "denied")
    demo = Demo(use_audio=mic_ok)
    log("student dashboard:", demo.server.student_url)
    log("professor page:", demo.server.prof_url)
    cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
    raise_window(WIN)
    cv2.setMouseCallback(WIN, lambda e, x, y, fl, p: demo.on_click(x, y) if e == cv2.EVENT_LBUTTONDOWN else None)
    log("running. click the window, press q to quit")
    prev, writer = time.time(), None
    os.makedirs("recordings", exist_ok=True)
    while True:
        ok, frame = cap.read()
        if not ok:
            if video and not str(video).startswith("http"):
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0); continue
            if video:
                time.sleep(0.5); cap = cv2.VideoCapture(video); continue
            break
        now = time.time()
        canvas = demo.process(fit(frame), now)
        fps = 1.0 / max(now - prev, 1e-6); prev = now
        demo.fps = 0.9 * demo.fps + 0.1 * fps
        put(canvas, f"{demo.fps:.0f} FPS", (FRAME_W - 80, 20), 0.5, (0, 255, 0), 1)
        cv2.imshow(WIN, canvas)
        if writer is not None:
            writer.write(canvas)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("a"):
            demo.mode = "auto"
        elif key == ord("s"):
            demo.simulate("overload")
        elif key == ord("m"):
            demo.calm.stop()
        elif key == ord("l"):
            demo.simulate("lean")
        elif key in (ord("b"), ord("f")):
            ev = demo.latest_feedback_target()
            if ev:
                demo.feedback(ev["id"], "bothered" if key == ord("b") else "fine")
        elif key == ord("r"):
            if writer is None:
                fn = os.path.join("recordings", time.strftime("demo-%Y%m%d-%H%M%S.mp4"))
                writer = cv2.VideoWriter(fn, cv2.VideoWriter_fourcc(*"mp4v"), 12, (canvas.shape[1], canvas.shape[0]))
                demo.recording = True
                log("recording to", fn)
            else:
                writer.release(); writer = None; demo.recording = False
                log("recording saved")
        elif key == ord("c") and len(cams) > 1:
            cap.release()
            cur = cams[(cams.index(cur) + 1) % len(cams)]
            cap = cv2.VideoCapture(cur, cv2.CAP_AVFOUNDATION)
            log(f"switched to camera index {cur}")
    if writer is not None:
        writer.release()
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
