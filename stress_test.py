"""Stress test: scripted classroom scenes run through the real EqualEd pipeline.

Builds scenes from real photos of people (bus.jpg, zidane.jpg): one student in the middle,
others crowding in, lingering, rushing at them, moving fast, plus flicker, a loud noise,
an overload and the student being blocked for a moment. Checks that every trigger
reaches the teacher. Run:  .venv/bin/python stress_test.py
Frames from each scene go to stress_out/ so you can see what the app drew.
"""
import json, os, sys, time
import numpy as np
import cv2

os.environ.setdefault("EQUALED_PORT", "8791")
import sensory_demo as sd
from ultralytics import YOLO

OUT = "stress_out"
FPS = 10
os.makedirs(OUT, exist_ok=True)


def people_crops():
    m = YOLO("yolo11n.pt")
    crops = []
    for f in ("bus.jpg", "zidane.jpg"):
        img = cv2.imread(f)
        for b, c in zip(m.predict(img, classes=[0], conf=0.5, verbose=False)[0].boxes.xyxy.cpu().numpy(),
                        m.predict(img, classes=[0], conf=0.5, verbose=False)[0].boxes.conf.cpu().numpy()):
            x1, y1, x2, y2 = map(int, b)
            if (y2 - y1) > 150:
                crops.append(img[max(y1 - 10, 0):y2 + 5, max(x1 - 10, 0):x2 + 10].copy())
    return crops


CROPS = people_crops()
BG = np.full((540, 960, 3), (176, 168, 160), np.uint8)
cv2.rectangle(BG, (0, 380), (960, 540), (120, 135, 150), -1)   # floor


def paste(canvas, crop, cx, bottom, height):
    h, w = crop.shape[:2]
    s = height / h
    c = cv2.resize(crop, (max(1, int(w * s)), max(1, int(h * s))))
    ch, cw = c.shape[:2]
    x1, y1 = int(cx - cw / 2), int(bottom - ch)
    X1, Y1, X2, Y2 = max(x1, 0), max(y1, 0), min(x1 + cw, canvas.shape[1]), min(y1 + ch, canvas.shape[0])
    if X2 > X1 and Y2 > Y1:
        canvas[Y1:Y2, X1:X2] = c[Y1 - y1:Y2 - y1, X1 - x1:X2 - x1]


STUDENT = 0   # crop index used for the student


def scene(t, others, student=True, bright=1.0):
    """others: list of (crop index, cx, bottom, height)."""
    f = BG.copy()
    for ci, cx, bottom, h in sorted(others, key=lambda o: o[3]):      # far (small) first
        if h < 300:
            paste(f, CROPS[ci % len(CROPS)], cx, bottom, h)
    if student:
        paste(f, CROPS[STUDENT], 480, 520, 330)
    for ci, cx, bottom, h in sorted(others, key=lambda o: o[3]):
        if h >= 300:
            paste(f, CROPS[ci % len(CROPS)], cx, bottom, h)
    if bright != 1.0:
        f = np.clip(f.astype(np.float32) * bright, 0, 255).astype(np.uint8)
    return f


class Clock:
    t = 10000.0


def reset(demo):
    demo._max_hectic = 0
    demo.tracks.clear()
    demo.trig = {k: sd.Trigger(k, l, live, h) for k, l, live, h in sd.TRIGGER_DEFS}
    demo.resp = {k: sd.Trigger(k, l, True, h, cooldown=5.0) for k, l, h in sd.RESPONSE_DEFS}
    demo.teacher_sent, demo.hectic, demo.hectic_since, demo.hectic_alert_at = {}, 0.0, None, -1e9
    demo.hectic_hist.clear()
    demo.stand_events.clear(); demo.recent.clear(); demo.light.clear(); demo.prev_small = None
    demo.episode_at, demo.mode, demo.target_id, demo.locked_box = -1e9, "auto", None, None
    demo.seat = None
    demo.pose.predictor = None          # fresh tracker
    Clock.t += 100


def lock_student(demo):
    """What the hands-up gesture does: lock onto the person sitting in the student's seat (x = 480)."""
    live = [(tid, tr.hist[-1][3]) for tid, tr in demo.tracks.items() if tr.hist and Clock.t - tr.seen < 0.2]
    tid, box = min(live, key=lambda p: abs(sd.center(p[1])[0] - 480) + abs(sd.bh(p[1]) - 330))
    demo.mode, demo.target_id, demo.locked_box, demo.seat = "locked", tid, box.copy(), None


def run(demo, name, seconds, frame_fn, every=None, lock=False):
    reset(demo)
    n0 = len(demo.server.alerts)
    seen_trig = set()
    shots = []
    for i in range(int(seconds * FPS)):
        t = i / FPS
        Clock.t += 1 / FPS
        if every:
            every(demo, t)
        canvas = demo.process(frame_fn(t), Clock.t)
        if lock and i == 5:
            lock_student(demo)
        seen_trig |= {k for k, tr in demo.trig.items() if tr.alerting(Clock.t)}
        demo._max_hectic = max(getattr(demo, "_max_hectic", 0), demo.hectic)
        if i in (int(seconds * FPS * 0.5), int(seconds * FPS) - 1):
            shots.append(canvas)
    cv2.imwrite(os.path.join(OUT, f"{name}.jpg"), np.hstack([cv2.resize(s, (640, 493)) for s in shots]))
    alerts = demo.server.alerts[n0:]
    return seen_trig, alerts


def main():
    print(f"{len(CROPS)} people crops")
    demo = sd.Demo(event_dir="events_stress", use_audio=False)
    demo.profile, demo.profile_path = {}, os.path.join("events_stress", "profile.json")
    results = []

    def check(name, trig, alerts, want_trig=(), want_kinds=(), want_texts=()):
        kinds = {a["kind"] for a in alerts}
        texts = " ".join(a["reason"] for a in alerts)
        miss = [f"trigger:{k}" for k in want_trig if k not in trig] + [f"alert:{k}" for k in want_kinds if k not in kinds] \
             + [f"text:{x}" for x in want_texts if x.lower() not in texts.lower()]
        results.append((name + f"  [busy meter peaked at {demo._max_hectic:.0f}/100]", not miss, sorted(trig),
                        [f"{a['kind']}: {a['reason'][:80]}" for a in alerts], miss))

    # 1) three people walk up and stay close for 12 s -> crowding, personal space, staying close
    def crowd(t):
        k = min(1.0, max(0.0, (t - 1) / 2))          # walk in over 2 s, then stay
        jit = 4 * np.sin(t * 3)
        return scene(t, [(1, 40 + 230 * k + jit, 500, 300),            # from the left edge to beside the student
                         (4, 920 - 230 * k - jit, 500, 300),           # from the right edge to beside the student
                         (5, 900 - 100 * k, 510, 290)])                # a third one, further right
    check("crowding + someone staying close", *run(demo, "1_crowding", 14, crowd, lock=True),
          want_trig=("crowd", "dwell"), want_kinds=("trigger", "dwell"), want_texts=("stayed close", "Crowding"))

    # 2) someone rushes at the student from the back of the room
    def rush(t):
        k = min(1.0, max(0.0, (t - 1.5) / 1.2))     # back of the room to right beside the student in 1.2 s
        return scene(t, [(4, 820 - 140 * k, 330 + 190 * k, 150 + 220 * k)])
    check("someone rushing toward the student", *run(demo, "2_rush", 6, rush, lock=True),
          want_trig=("approach",), want_kinds=("trigger",))

    # 3) commotion: four people moving fast around the student -> busy meter -> teacher help alert
    def commotion(t):
        return scene(t, [(1 + i, 480 + (230 + 40 * i) * np.sin(t * 5 + i * 1.7) * (1 if i % 2 else -1),
                          500, 280 + 25 * np.cos(t * 4 + i)) for i in range(4)])
    check("commotion around the student", *run(demo, "3_commotion", 12, commotion, lock=True),
          want_trig=("rapid",), want_kinds=("hectic", "trigger"))

    # 4) flickering lights
    check("flickering light", *run(demo, "4_flicker", 5, lambda t: scene(t, [], bright=0.45 if int(t * 10) % 2 and t > 1.5 else 1.0)),
          want_trig=("light",), want_kinds=("trigger",))

    # 5) sudden loud noise (microphone faked: a 'Siren' at t=2 s)
    def fake_noise(demo, t):
        demo.audio.loud_event = (lambda now, fire=(2.0 <= t < 2.2): (True, "Siren (88%)") if fire else (False, ""))
    check("sudden loud noise", *run(demo, "5_noise", 4, lambda t: scene(t, []), every=fake_noise),
          want_trig=("noise",), want_kinds=("trigger",), want_texts=("Siren",))

    # 6) overload moment (simulated reaction) -> overload alert
    check("student overload", *run(demo, "6_overload", 3, lambda t: scene(t, []),
                                   every=lambda d, t: d.simulate("overload") if abs(t - 1.0) < 0.05 else None),
          want_kinds=("overload",))

    # 7) locked student is blocked for 1 s by someone walking past, lock must come back to them
    reset(demo)
    for i in range(60):
        t = i / FPS
        Clock.t += 1 / FPS
        blocker = [(2, 480, 535, 420)] if 2.0 <= t < 3.0 else []
        demo.process(scene(t, blocker), Clock.t)
        if i == 5:
            lock_student(demo)
    tb = demo.tracks.get(demo.target_id)
    ok = demo.mode == "locked" and tb is not None and abs(sd.center(tb.hist[-1][3])[0] - 480) < 80
    results.append(("lock survives someone walking in front", ok, [], [], [] if ok else ["lock lost or moved"]))

    print()
    for name, ok, trig, alerts, miss in results:
        print(("PASS " if ok else "FAIL ") + name)
        if trig: print("     triggers seen:", ", ".join(trig))
        for a in alerts[:6]: print("     teacher got ->", a)
        if miss: print("     MISSING:", ", ".join(miss))
    print(f"\n{sum(r[1] for r in results)}/{len(results)} passed. Frames in {OUT}/")
    json.dump(demo.server.alerts, open(os.path.join(OUT, "alerts.json"), "w"), indent=2)
    return demo


if __name__ == "__main__":
    demo = main()
    if "--serve" in sys.argv:
        print("professor page:", demo.server.prof_url.replace(sd.Server.__module__, ""), flush=True)
        time.sleep(600)
