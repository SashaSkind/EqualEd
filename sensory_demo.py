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
from vast import Vast, CosmosWatcher, SENSORY_INGEST_PROMPT

POSE_MODEL = "yolo11n-pose.pt"   # joints + face points
DEVICE = "mps"
FRAME_W = 960
PANEL_W = 400
CHAIR_CLS = 56
KP_OK = 0.5
WIN = "EqualEd - classroom support (q to quit)"
EPISODE_COOLDOWN = 60.0         # seconds before another overload alert
LOCK_HOLD = 1.0                 # seconds with both hands up to lock onto a student
HECTIC_ALERT_AT = 55            # "busy around the student" level (0-100) that alerts the teacher
HECTIC_HOLD = 3.0               # ... if it is that high for this many of the last HECTIC_WINDOW seconds
HECTIC_WINDOW = 5.0             # (brief dips, e.g. someone blocking the view, don't reset it)
HECTIC_COOLDOWN = 60.0
DWELL_ALERT = 8.0               # someone inside the student's bubble this long -> teacher alert
TEACHER_TRIGGER_COOLDOWN = 30.0 # per trigger, so the teacher isn't spammed
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
    ("dwell", "Someone staying close", True, 0.0),
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
        self.hands_up_since = None
        self.near_since = None


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


def _flips(sig, min_p2p):
    """How many times a signal swings back and forth (after removing slow drift)."""
    sig = np.asarray(sig, float)
    if len(sig) < 12:
        return 0, 0.0
    w = max(9, (len(sig) // 3) | 1)                               # ~1.5 s: removes slow leaning, keeps rocking
    trend = np.convolve(np.pad(sig, w // 2, mode="edge"), np.ones(w) / w, mode="valid")
    d = np.convolve(sig - trend, np.ones(3) / 3, mode="same")[2:-2]
    if len(d) < 8:
        return 0, 0.0
    p2p = float(np.percentile(d, 90) - np.percentile(d, 10))
    if p2p < min_p2p:
        return 0, p2p
    th, state, flips = 0.25 * p2p, 0, 0
    for v in d:
        s = 1 if v > th else -1 if v < -th else 0
        if s and s != state:
            if state:
                flips += 1
            state = s
    return flips, p2p


def rocking_score(tr, now, window=5.0):
    """Back-and-forth swings of the head (side to side, up and down, toward/away from the
    camera) and of the shoulders. Returns (best swing count, details)."""
    head = {"x": [], "y": [], "size": []}
    sh = {"x": [], "y": []}
    for t, k, c, b in tr.hist:
        if now - t > window:
            continue
        if c[L_EYE] > 0.4 and c[R_EYE] > 0.4 and c[NOSE] > 0.4:
            eye_d = max(float(np.linalg.norm(k[L_EYE] - k[R_EYE])), 4.0)
            head["x"].append(k[NOSE][0]); head["y"].append(k[NOSE][1]); head["size"].append(eye_d)
        if c[L_SH] > 0.5 and c[R_SH] > 0.5:
            m = (k[L_SH] + k[R_SH]) / 2
            sh["x"].append(m[0]); sh["y"].append(m[1])
    best, info = 0, {}
    if len(head["size"]) >= 12:
        scale = float(np.median(head["size"]))
        for name, sig, mp in (("head side-to-side", np.array(head["x"]) / scale, 0.2),
                              ("head up-and-down", np.array(head["y"]) / scale, 0.2),
                              ("toward/away", np.array(head["size"]) / scale, 0.05)):
            f, p = _flips(sig, mp)
            info[name] = (f, round(p, 2))
            best = max(best, f)
    if len(sh["x"]) >= 12:
        sw = max(float(np.median([abs(v) for v in np.diff(sh["x"])] + [1.0])), 1.0)
        span = max(float(np.ptp(sh["x"])), 1.0)
        for name, sig in (("shoulders side-to-side", sh["x"]), ("shoulders up-and-down", sh["y"])):
            f, p = _flips(np.array(sig) / max(span, 20.0), 0.3)
            info[name] = (f, round(p, 2))
            best = max(best, f)
    return best, info


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
        # hackathon stack: Cosmos3-Reason + Canary-1B on CoreWeave, VSS archive, W&B inference
        self.vast = Vast()
        self.cosmos = CosmosWatcher(self.vast, start=use_audio)   # self-test makes no network calls
        self.archive, self.archive_error = self.load_archive_labels(), ""
        self.transcriber = Transcriber(self.audio, vast=self.vast)
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
        self.one_hand_since = None
        self.locked_box, self.locked_lost_at, self.lock_flash = None, None, -1e9
        self.hectic, self.hectic_since, self.hectic_alert_at, self.hectic_parts = 0.0, None, -1e9, []
        self.ring_motion = 0.0
        self.hectic_hist = collections.deque(maxlen=400)   # (t, above line?)
        self.teacher_sent = {}          # trigger key -> last time the teacher was told
        self.marks = []                 # (box, text, color) drawn on the people causing triggers
        self.requested_source, self.source_label = None, "webcam"
        self._state = "{}"
        self.last_publish = 0.0
        self.server = Server(self.cfg.get("student_name", "Demo student"), self)

    # ------------------------------------------------------------ bridge (web)
    def state_json(self):
        return self._state

    def feedback(self, eid, verdict):
        self.inbox.put(("feedback", eid, verdict))

    def ask(self, q):
        return adhd_ask(q, self.transcriber.recent(400), [dict(d) for d in self.attention.drops], vast=self.vast)

    def archive_scan(self):
        if not self.vast.archive_on:
            return {"error": "Add INGRESS_URL, USERNAME and PASSWORD to vast.env to search the VAST archive."}
        try:
            self.archive, self.archive_error = self.vast.sensory_map(), ""
            self.log_event("archive scan", "archive", f"Sensory map: {len(self.archive['places'])} places ranked", None)
            return self.archive
        except Exception as e:
            self.archive_error = f"{type(e).__name__}: {str(e)[:160]}"
            return {"error": self.archive_error}

    def load_archive_labels(self):
        """Saved sensory labels of the team's VAST archive (Cosmos captions + YOLO counts)."""
        try:
            a = json.load(open(os.path.join(HERE, "archive_sensory_labels.json")))
        except Exception:
            return None
        places = [{"place": f"{p['location']} · {p['camera_id']}", "score": p["avg_load"],
                   "top": f"{p['main_triggers']} · {p['high_pct']}% high load, {p['calm_pct']}% calm"} for p in a["places"]]
        clips = [{"trigger": c["triggers"], "place": f"{c['location']} · {c['camera_id']} @ {c['start_sec']}s",
                  "similarity": c["load"], "caption": c["caption"]} for c in a["top_clips"]]
        return {"places": places, "clips": clips,
                "time": f"{a['labeled_at']} ({a['clips_labeled']} clips: {a['levels']['high']} high, "
                        f"{a['levels']['moderate']} moderate, {a['levels']['calm']} calm)"}

    def footage_list(self):
        p = os.path.join(HERE, "archive_clips", "index.json")
        try:
            return [r for r in json.load(open(p)) if r.get("file") and os.path.exists(r["file"])]
        except Exception:
            return []

    def footage_find(self):
        if not self.vast.archive_on:
            return {"error": "Add INGRESS_URL, USERNAME and PASSWORD to vast.env to search the hackathon footage."}
        try:
            import find_footage
            rows = find_footage.run(top=12, log=lambda *a: None)
            self.log_event("archive footage", "footage", f"Found {len(rows)} crowding clips in the archive", None)
            return {"clips": self.footage_list()}
        except SystemExit as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {str(e)[:160]}"}

    def play_source(self, what):
        clips = {r["file"] for r in self.footage_list()}
        if what == "webcam" or what in clips:
            self.requested_source = what
            return {"ok": True}
        return {"error": "unknown clip"}

    def archive_ask(self, q):
        if not self.vast.archive_on:
            return {"answer": "Add INGRESS_URL, USERNAME and PASSWORD to vast.env first."}
        try:
            r = self.vast.archive_ask(q)
            return {"answer": r.get("answer", ""), "evidence": r.get("evidence")}
        except Exception as e:
            return {"answer": f"Archive question failed: {type(e).__name__}: {str(e)[:160]}"}

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
        if frame is not None and kind in ("trigger", "overload", "prediction", "loud sound", "reaction"):
            fn = os.path.join(self.event_dir, f"{time.strftime('%Y%m%d-%H%M%S')}-{key}.jpg".replace(":", "-").replace(" ", "_"))
            cv2.imwrite(fn, frame)
            ev["snapshot"] = fn
            snaps = sorted(f for f in os.listdir(self.event_dir) if f.endswith(".jpg"))
            for old_f in snaps[:-300]:
                try:
                    os.remove(os.path.join(self.event_dir, old_f))
                except OSError:
                    pass
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

        self.cosmos.push(now, frame)

        # 1) people, joints, face points, stable ids
        res = self.pose.track(frame, persist=True, device=DEVICE, conf=0.35, verbose=False)[0]
        people = []
        if res.boxes is not None and len(res.boxes):
            boxes = res.boxes.xyxy.cpu().numpy()
            if res.boxes.id is not None:
                ids = res.boxes.id.cpu().numpy().astype(int)
            else:   # tracker gave no ids this frame: reuse the track each box overlaps most
                ids, used = [], set()
                for bb in boxes:
                    best = max(((iou(bb, tr.hist[-1][3]), tid) for tid, tr in self.tracks.items()
                                if tid not in used and tr.hist and now - tr.seen < 1.0), default=(0, None))
                    if best[0] > 0.3:
                        ids.append(best[1]); used.add(best[1])
                    else:
                        self.next_free_id = getattr(self, "next_free_id", 500000) + 1
                        ids.append(self.next_free_id)
                ids = np.array(ids)
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
        # Lock-on gesture: both hands raised above the head for LOCK_HOLD seconds = "track me"
        for tid, b, k, c, tr in people:
            sw_ = shoulder_w(k, c, b)
            if c[NOSE] > KP_OK:
                top = k[NOSE][1]
            else:
                shp = mean_pt(k, c, (L_SH, R_SH))
                top = (shp[1] if shp is not None else b[1] + 0.3 * bh(b)) - 0.8 * sw_
            up = c[L_WR] > 0.5 and c[R_WR] > 0.5 and k[L_WR][1] < top - 0.15 * sw_ and k[R_WR][1] < top - 0.15 * sw_
            if up:
                tr.hands_up_since = tr.hands_up_since or now
                if now - tr.hands_up_since >= LOCK_HOLD and not (self.mode == "locked" and self.target_id == tid):
                    self.mode, self.target_id, self.locked_box = "locked", tid, b.copy()
                    self.seat = (center(b), bh(b))
                    self.locked_lost_at, self.lock_flash = None, now
                    self.log_event("locked", "lock", f"Now tracking {self.cfg.get('student_name', 'the student')} (hands-up gesture)", None)
            else:
                tr.hands_up_since = None
        if self.mode == "locked":
            # The student is anchored to their SEAT (where they raised their hands), not to whoever
            # is nearest the last box, so people walking in front can't steal the lock.
            if getattr(self, "seat", None) is None and self.locked_box is not None:
                self.seat = (center(self.locked_box), bh(self.locked_box))
            sc, sh = self.seat
            def seat_dist(p):
                return np.linalg.norm(center(p[1]) - sc) / sh + abs(np.log(bh(p[1]) / sh))
            in_seat = [p for p in people if seat_dist(p) < 0.45]
            cur = next((p for p in people if p[0] == self.target_id), None)
            best = min(in_seat, key=seat_dist) if in_seat else None
            if cur is not None and seat_dist(cur) < 0.45 and (best is None or seat_dist(cur) <= seat_dist(best) + 0.1):
                pick = cur
            else:
                pick = best
            if pick is not None:
                self.target_id, self.locked_box, self.locked_lost_at = pick[0], pick[1].copy(), None
                # follow small shifts in posture slowly (leaning, sitting back)
                self.seat = (0.97 * sc + 0.03 * center(pick[1]), 0.97 * sh + 0.03 * bh(pick[1]))
            else:
                self.target_id = None if cur is None or seat_dist(cur) >= 0.45 else self.target_id
                self.locked_lost_at = self.locked_lost_at or now
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

        # 3b) who is causing what, and how long anyone has stayed close
        self.marks, dwellers = [], []
        for tid, b, k, c, tr in others:
            if tid in near:
                tr.near_since = tr.near_since or now
                stay = now - tr.near_since
                if stay >= DWELL_ALERT:
                    dwellers.append((tid, stay))
            else:
                tr.near_since = None
            tags = []
            if tid in too_close:
                tags.append("TOO CLOSE")
            if speeds.get(tid, 0) > 1.5 and tid in vicinity:
                tags.append("FAST")
            if grows.get(tid, 0) > 0.6 and tid in vicinity:
                tags.append("APPROACHING")
            if tr.near_since and now - tr.near_since >= 3:
                tags.append(f"STAYING CLOSE {now - tr.near_since:.0f}s")
            if not tags and tid in near:
                tags.append("close")
            if tags:
                self.marks.append((b, " | ".join(tags), (0, 0, 255) if tags != ["close"] else (0, 165, 255)))
        longest = max((s for _, s in dwellers), default=0.0)

        # 4) whole-scene motion and light
        small = cv2.GaussianBlur(cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90)), (5, 5), 0)
        motion = 0.0
        if self.prev_small is not None:
            mask = cv2.absdiff(small, self.prev_small) > 25
            if target is not None:
                x1, y1, x2, y2 = (target[1] * [160 / W, 90 / H, 160 / W, 90 / H]).astype(int)
                mask[max(y1, 0):y2, max(x1, 0):x2] = False
            motion = float(mask.mean())
            if target is not None:
                bx = target[1] * [160 / W, 90 / H, 160 / W, 90 / H]
                cx_, cy_, hw, hh = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2, (bx[2] - bx[0]), (bx[3] - bx[1])
                rx1, ry1 = int(max(cx_ - 1.5 * hw, 0)), int(max(cy_ - 1.0 * hh, 0))
                rx2, ry2 = int(min(cx_ + 1.5 * hw, 160)), int(min(cy_ + 1.0 * hh, 90))
                ring = mask[ry1:ry2, rx1:rx2]
                self.ring_motion = float(ring.mean()) if ring.size else 0.0
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
            "dwell": (len(dwellers) > 0, f"longest stay close: {longest:.0f}s (alert at {DWELL_ALERT:.0f}s)" if longest
                      else f"nobody lingering (alert at {DWELL_ALERT:.0f}s)"),
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
                self.tell_teacher(key, t.label, val if key != "noise" else noise_desc, now)

        # 6b) "busy around the student" meter (no sound in it): people, movement and approaches
        #     inside the student's personal bubble only
        if target is not None:
            movers_near = sum(1 for t in vicinity if speeds.get(t, 0) > 0.6)
            hp = [(min(1.0, len(near) / 3) * 30, f"{len(near)} people close"),
                  (min(1.0, movers_near / 2) * 25, f"{movers_near} moving around"),
                  (min(1.0, self.ring_motion / 0.2) * 25, "lots of motion around"),
                  (10 if fastest_grow > 0.6 else 0, "someone approaching fast"),
                  (10 if self.trig["rapid"].alerting(now) else 0, "rapid movement"),
                  (10 if self.trig["commotion"].alerting(now) else 0, "commotion"),
                  (10 if any(self.trig[k].alerting(now) for k in ("stand", "rush", "chair")) else 0, "people getting up / chairs"),
                  (10 if self.trig["too_close"].alerting(now) else 0, "someone in personal space")]
            raw_h = min(100.0, sum(v for v, _ in hp))
            self.hectic_parts = [n for v, n in sorted(hp, key=lambda x: -x[0]) if v > 0][:3]
            if self.hectic_parts:
                self.last_hectic_parts = self.hectic_parts
        else:
            raw_h, self.hectic_parts = 0.0, []
        self.hectic = 0.7 * self.hectic + 0.3 * raw_h if raw_h > self.hectic else 0.95 * self.hectic + 0.05 * raw_h
        self.hectic_hist.append((now, self.hectic >= HECTIC_ALERT_AT))
        recent_h = [(t, a) for t, a in self.hectic_hist if now - t <= HECTIC_WINDOW]
        above = sum(t2 - t1 for (t1, a), (t2, _) in zip(recent_h, recent_h[1:]) if a)
        self.hectic_since = now - above if above > 0 else None
        if above >= HECTIC_HOLD and now - self.hectic_alert_at > HECTIC_COOLDOWN:
            self.hectic_alert(now, frame)

        # 7) risk meter: what is likely to get loud or overwhelming in the next few seconds
        parts = []
        for name, conf, box, held in self.objects:
            if name in LOUD_THINGS and present(name):
                r = (LOUD_THINGS[name] * min(1.0, conf / 0.6) * closeness(box, H)
                     * (1.25 if held else 1.0) * self.mult("object:" + name))
                parts.append((min(r, 0.98), f"{name} {'in someone' + chr(39) + 's hand' if held else 'in view'}", "object:" + name))
        cz = self.cosmos.fresh(now)
        if cz and cz["risk"] >= 0.2:
            parts.append((min(cz["risk"] * 0.9 * self.mult("cosmos"), 0.95), f"Cosmos: {cz['what'] or 'scene may get overwhelming'}", "cosmos"))
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
        # Reactions are judged only for someone close to the camera (the student at this laptop).
        # A small figure across the room is too far to tell ear-covering or rocking from normal gestures.
        close_enough = subject is not None and (self.mode in ("pick", "locked") or bh(subject[1]) >= 0.35 * H)
        if not close_enough:
            resp_state = {k: (False, "no student close to the camera") for k in resp_state}
        if close_enough:
            _, b, k, c, tr = subject
            sw = shoulder_w(k, c, b)
            # Covering ears: a hand at the side of the head, roughly at ear height. Covering the ears
            # hides the ear points, so ear positions are estimated from the eyes/nose when needed.
            # Both hands -> counts right away; one hand -> only if it stays 2.5 s (scratching, glasses).
            hands = 0
            ear_pts = [k[i] for i in (L_EAR, R_EAR) if c[i] > 0.3]
            if len(ear_pts) < 2 and c[L_EYE] > 0.3 and c[R_EYE] > 0.3:
                mid = (k[L_EYE] + k[R_EYE]) / 2
                half = 1.7 * (k[L_EYE] - k[R_EYE]) / 2
                ear_pts = [mid + half + [0, 0.15 * sw], mid - half + [0, 0.15 * sw]]
            elif not ear_pts and c[NOSE] > 0.3:
                ear_pts = [k[NOSE] + [0.55 * sw, 0], k[NOSE] - [0.55 * sw, 0]]
            sh_y = mean_pt(k, c, (L_SH, R_SH))
            wrist_info = []
            for wr in (L_WR, R_WR):
                ok_w = c[wr] > 0.3 and ear_pts
                dist = min(np.linalg.norm(k[wr] - e) for e in ear_pts) / sw if ok_w else None
                raised = sh_y is None or k[wr][1] < sh_y[1] - 0.05 * sw
                if ok_w and ((raised and dist < 0.75) or dist < 0.45):
                    hands += 1
                wrist_info.append({"conf": round(float(c[wr]), 2), "dist_to_ear": None if dist is None else round(float(dist), 2),
                                   "raised": bool(raised)})
            self.ear_debug = {"hands": hands, "wrists": wrist_info, "ears_seen": int(sum(c[i] > 0.3 for i in (L_EAR, R_EAR)))}
            if hands == 1:
                self.one_hand_since = self.one_hand_since or now
            else:
                self.one_hand_since = None
            ears = hands >= 2 or (hands == 1 and now - self.one_hand_since >= 2.5)
            resp_state["ears"] = (ears, f"hands at ears: {hands}")
            shm = mean_pt(k, c, (L_SH, R_SH))
            if shm is not None and c[NOSE] > KP_OK:
                gap = (shm[1] - k[NOSE][1]) / sw
                resp_state["head_down"] = (gap < 0.15, f"nose above shoulders: {gap:.2f}")
            rs, rinfo = rocking_score(tr, now)
            self.rock_debug = rinfo
            resp_state["rocking"] = (rs >= 4, f"back-and-forth swings: {rs}")
        for key, (active, val) in resp_state.items():
            r = self.resp[key]
            if r.update(active, now, val):
                causes = sorted({lbl for t, lbl in self.recent if now - t <= 20})
                self.last_link = f"{r.label} <- " + (", ".join(causes) if causes else "no trigger seen")
                self.log_event("reaction", key, r.label, frame, {"linked_triggers": causes, "debug": getattr(self, "ear_debug", None) if key == "ears" else None},
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

    def tell_teacher(self, key, label, detail, now):
        """On-screen notification for the teacher whenever a trigger fires (rate-limited per trigger)."""
        if now - self.teacher_sent.get(key, -1e9) < TEACHER_TRIGGER_COOLDOWN:
            return
        self.teacher_sent[key] = now
        name = self.cfg.get("student_name", "The student")
        if key == "dwell":
            msg, kind = f"Someone has stayed close to {name} for {DWELL_ALERT:.0f}+ seconds. Please check in.", "dwell"
        elif key == "noise":
            msg, kind = f"Sudden loud noise near {name}: {detail}", "trigger"
        else:
            msg, kind = f"{label} near {name}", "trigger"
        self.server.notify(msg, [detail] if detail else [], "", kind=kind)

    def hectic_alert(self, now, frame):
        self.hectic_alert_at = now
        name = self.cfg.get("student_name", "The student")
        where = self.calm.play()
        sound = (f"Calming sound playing on {where}" if where else "Calming sound held back: no AirPods connected")
        why = ", ".join(self.hectic_parts or getattr(self, "last_hectic_parts", [])) or "a lot going on"
        aid = self.server.notify(f"Very busy around {name}: {why}. Please check in.",
                                 sorted({lbl for t, lbl in self.recent if now - t <= 20}), sound, kind="hectic")
        self.episode = {"at": now, "id": aid, "where": where, "reason": f"Busy around {name}: {why}", "sound": sound}
        self.episode_count += 1
        self.log_event("busy alert", "hectic", f"Teacher alerted: busy around {name} ({self.hectic:.0f}/100)", frame,
                       detail=why, pkey="hectic", plabel="Busy around me")

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

        def explained(text, aid=aid, ep=self.episode):
            ep["cosmos"] = text
            self.server.update_alert(aid, cosmos=text)
            self.write_event({"kind": "cosmos explanation", "key": "overload", "label": text})
            log("COSMOS", text)
        self.cosmos.explain_async(reason, explained)

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
            "mode": {"auto": "biggest person", "pick": f"person {self.target_id}", "solo": "solo test",
                     "locked": f"locked on {self.cfg.get('student_name', 'student')}"}[self.mode],
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
            "ear_debug": getattr(self, "ear_debug", None),
            "rock_debug": getattr(self, "rock_debug", None),
            "reaction_values": {k: r.value for k, r in self.resp.items()},
            "hectic": {"value": round(self.hectic), "parts": self.hectic_parts, "locked": self.mode == "locked",
                       "name": self.cfg.get("student_name", "Demo student"),
                       "lost": bool(self.mode == "locked" and self.locked_lost_at)},
            "vast": {"status": self.vast.status, "gpu": self.vast.gpu_on, "archive": self.vast.archive_on,
                     "wandb": self.vast.wandb_on, "cosmos": self.cosmos.latest, "cosmos_error": self.cosmos.error,
                     "cosmos_calls": self.cosmos.calls, "cosmos_video": self.vast.video_mode,
                     "ingest_prompt": SENSORY_INGEST_PROMPT},
            "archive": self.archive, "archive_error": self.archive_error,
            "source": self.source_label, "footage": self.footage_list() if self.frame_i % 20 == 0 or not hasattr(self, "_fl") else self._fl,
            "overload_cosmos": (ep or {}).get("cosmos", ""),
        }
        self._fl = st["footage"]
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
        tc_ = tuple(map(int, center(target[1]))) if target is not None else None
        for b, txt, col in self.marks:
            bx1, by1, bx2, by2 = map(int, b)
            cv2.rectangle(vis, (bx1, by1), (bx2, by2), col, 3)
            (tw, th_), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(vis, (bx1, max(by1 - th_ - 10, 0)), (bx1 + tw + 8, max(by1, th_ + 10)), col, -1)
            put(vis, txt, (bx1 + 4, max(by1 - 6, th_ + 4)), 0.6, (255, 255, 255), 2)
            if tc_ and col == (0, 0, 255):
                cv2.line(vis, tc_, tuple(map(int, center(b))), col, 2)
        if target is not None:
            x1, y1, x2, y2 = map(int, target[1])
            hc = (0, 0, 230) if self.hectic >= HECTIC_ALERT_AT else (0, 150, 255) if self.hectic >= 35 else (0, 200, 0)
            cv2.ellipse(vis, ((x1 + x2) // 2, (y1 + y2) // 2), (int(1.5 * (x2 - x1)), int(1.0 * (y2 - y1))), 0, 0, 360, hc, 2)
            cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 230, 255), 4)
            label = f"LOCKED: {self.cfg.get('student_name', 'STUDENT')}" if self.mode == "locked" else "STUDENT"
            put(vis, label, (x1 + 6, y1 + 24), 0.8, (0, 230, 255), 2)
            put(vis, f"busy around: {self.hectic:.0f}/100", (x1 + 6, y1 + 50), 0.6, hc, 2)
        if self.mode == "locked" and self.locked_lost_at:
            put(vis, f"Looking for {self.cfg.get('student_name', 'the student')}... raise both hands to re-lock", (10, H - 50), 0.6, (0, 200, 255), 2)
        elif self.mode != "locked":
            put(vis, "Raise both hands for 1 second to lock onto a student", (10, H - 50), 0.6, (255, 255, 255), 2)
        if now - self.lock_flash < 2.5:
            cv2.rectangle(vis, (0, H // 2 - 30), (W, H // 2 + 20), (0, 160, 0), -1)
            put(vis, f"LOCKED ON: tracking {self.cfg.get('student_name', 'this student')} only", (20, H // 2 + 2), 0.9, (255, 255, 255), 2)
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
        put(strip, "SENSORY TRIGGERS (red = teacher told)", (12, 20), 0.45, (255, 255, 255), 1)
        for i, t in enumerate(self.trig.values()):
            y = 36 + i * 15
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
        put(strip, f"Busy around student: {self.hectic:.0f}/100 (alert at {HECTIC_ALERT_AT})", (x, 98), 0.42,
            (0, 0, 255) if self.hectic >= HECTIC_ALERT_AT else (200, 200, 200))
        put(strip, ("Linked: " + self.last_link)[:44], (x, 118), 0.38, (0, 230, 255))
        if self.recording:
            cv2.circle(strip, (x + 6, 136), 6, (0, 0, 255), -1)
            put(strip, "Recording backup video (r to stop)", (x + 18, 140), 0.4, (0, 0, 255))
        cz = self.cosmos.fresh(now, 20)
        if cz:
            put(strip, f"Cosmos: {cz['what']} ({cz['risk']:.0%})"[:46], (x, 160), 0.38, (120, 255, 120))
        elif self.vast.gpu_on:
            put(strip, ("Cosmos: " + (self.cosmos.error or "watching..."))[:46], (x, 160), 0.38, (150, 150, 150))
        else:
            put(strip, "Cosmos: add key in vast.env", (x, 160), 0.38, (150, 150, 150))
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
    if cfg.get("open_dashboard", True) and demo.server.student_url.startswith("http"):
        import subprocess
        subprocess.Popen(["open", demo.server.student_url])
    log("professor page:", demo.server.prof_url)
    cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
    raise_window(WIN)
    cv2.setMouseCallback(WIN, lambda e, x, y, fl, p: demo.on_click(x, y) if e == cv2.EVENT_LBUTTONDOWN else None)
    log("running. click the window, press q to quit")
    prev, writer = time.time(), None
    os.makedirs("recordings", exist_ok=True)
    webcam_cap = None
    while True:
        if demo.requested_source:
            want, demo.requested_source = demo.requested_source, None
            if want == "webcam":
                if video is not None and cams:
                    cap.release()
                    cap = cv2.VideoCapture(cur, cv2.CAP_AVFOUNDATION)
                video, demo.source_label = (None if cams else video), "webcam"
            else:
                if video is None:
                    cap.release()
                else:
                    cap.release()
                cap, video = cv2.VideoCapture(want), want
                demo.source_label = "archive clip: " + os.path.basename(want)
                demo.tracks.clear()
            log("video source ->", demo.source_label)
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
        elif key in (ord("a"), ord("u")):
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
