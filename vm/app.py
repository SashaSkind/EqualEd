#!/usr/bin/env python3
"""EqualEd VM app — spotting sensory overload before it happens, on recorded video.

Plays a clip (local file or VAST archive chunk), tracks people and robots, flags things
closing in ("too close"), rushing and loud moments, asks Cosmos3-Reason for a sensory risk
every 2 s, and serves a dashboard (Live / Search the archive / Sensory map) on
http://0.0.0.0:8765/

Usage:
  python app.py                         # auto-find video, loop, serve dashboard
  python app.py --video /path/to.mp4
  python app.py --once --max-seconds 30 # smoke test, print summary JSON
  python app.py --selftest              # synthetic frames, no video needed
  python app.py --mic                   # also try microphone if file has no audio
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import clips  # noqa: E402
from audio_watch import AudioWatch, LoudnessEngine  # noqa: E402
from cosmos_watch import CosmosWatch, lead_times, parse_reply  # noqa: E402
from detector import RobotSpaceDetector, SUDDEN_SPEED, Track  # noqa: E402
from ui import PAGE  # noqa: E402

PORT = int(os.environ.get("PORT", "8765"))
VIDEO_PREFIX = "20261001_080730_test_Wherehouse_017_Camera_chunck_00"
SEARCH_DIRS = [
    HERE / "data",
    HERE.parent / "data",
    Path("/workspace/data"),
    Path("/data"),
    Path("/videos"),
    Path.home() / "videos",
    Path.cwd(),
    Path.cwd() / "data",
]
VIDEO_DIRS: list[Path] = []


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def find_video(explicit: str | None = None) -> Path:
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.exists():
            raise SystemExit(f"video not found: {p}")
        return p
    env = os.environ.get("EQUALED_VIDEO")
    if env:
        p = Path(env).expanduser().resolve()
        if p.exists():
            return p
    hits = []
    for d in SEARCH_DIRS:
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            name = p.name
            if name.startswith(VIDEO_PREFIX) and p.suffix.lower() in (".mp4", ".mov", ".mkv", ".avi"):
                hits.append(p)
            elif VIDEO_PREFIX in name and p.suffix.lower() in (".mp4", ".mov", ".mkv", ".avi"):
                hits.append(p)
    if hits:
        hits.sort(key=lambda p: p.stat().st_size, reverse=True)
        return hits[0]
    raise SystemExit(
        "Could not find warehouse video.\n"
        f"Place a file whose name starts with:\n  {VIDEO_PREFIX}\n"
        "under /workspace/data/ (or pass --video PATH).\n"
        "Source used in this environment: NVIDIA PhysicalAI-SmartSpaces "
        "MTMC_Tracking_2025/test/Warehouse_017/videos/Camera.mp4"
    )


class AppState:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {
            "video_t": 0, "frame": 0, "robots": [], "people": [],
            "summary": {"robots": 0, "people": 0, "invaded": 0, "clear": 0, "sudden": 0},
            "events": [], "audio": {"has_audio": False, "reason": "starting"},
            "cosmos": {"enabled": False, "reason": "starting"},
            "fps": 0, "playing": False, "video": "",
        }
        self.jpeg = self._placeholder_jpeg("starting…")
        self.switch_to: Path | None = None
        self.clip_status = ""

    def request_switch(self, path: Path):
        with self.lock:
            self.switch_to = Path(path)
            self.clip_status = f"switching to {Path(path).name}…"

    def take_switch(self) -> Path | None:
        with self.lock:
            p, self.switch_to = self.switch_to, None
            return p

    def switch_pending(self) -> bool:
        return self.switch_to is not None

    def set_status(self, msg: str):
        with self.lock:
            self.clip_status = msg

    @staticmethod
    def _placeholder_jpeg(msg: str) -> bytes:
        img = np.zeros((360, 640, 3), np.uint8)
        img[:] = (18, 28, 24)
        cv2.putText(img, msg, (40, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (180, 220, 200), 2)
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return buf.tobytes() if ok else b""

    def publish(self, state: dict, frame_bgr, video_name: str, fps: float, playing: bool):
        ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        with self.lock:
            self.state = dict(state, fps=round(fps, 1), playing=playing, video=video_name)
            if ok:
                self.jpeg = buf.tobytes()

    def get_state(self) -> dict:
        with self.lock:
            return dict(self.state, clip_status=self.clip_status)

    def get_jpeg(self) -> bytes:
        with self.lock:
            return self.jpeg


SHARED = AppState()


_VSS = None


def vss():
    global _VSS
    if _VSS is None:
        import archive
        _VSS = archive.VSS()
    return _VSS


def clip_dirs() -> list[Path]:
    """Folders offered in the clip picker (not the working directory, which holds scratch files)."""
    return VIDEO_DIRS + [d for d in SEARCH_DIRS if d not in (Path.cwd(), Path.cwd() / "data")]


def services() -> dict:
    """Connection status for the header chips (no network calls)."""
    import archive
    if not (archive.VSS_USER and archive.VSS_PASS):
        arch = "add login"
    elif _VSS is not None and _VSS._token:
        arch = "connected"
    else:
        arch = "not used yet"
    return {"archive": arch,
            "wandb": "ready" if os.environ.get("WANDB_API_KEY") else "add key",
            "weave": (f"tracing to {archive.WANDB_PROJECT}" if archive._weave_ready
                      else "starts on first summary" if archive.weave else "not installed")}


def switch_clip(body: dict) -> tuple[int, dict]:
    """Play a local file (must be in the clip list) or download + play an archive chunk."""
    if body.get("path"):
        p = Path(str(body["path"])).resolve()
        if p not in clips.local_clips(clip_dirs()):
            return 400, {"error": "not a known clip"}
        SHARED.request_switch(p)
        return 200, {"ok": True, "switching": p.name}
    src = str(body.get("source") or "")
    if not src.startswith(clips.ALLOWED_PREFIXES):
        return 400, {"error": "unknown source"}
    clips.fetch(src, lambda s: vss().stream(s), SHARED.request_switch, SHARED.set_status)
    return 200, {"ok": True, "fetching": src.rsplit("/", 1)[-1]}


def start_server(port: int):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code, obj):
            return self._send(code, json.dumps(obj), "application/json")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _clip(self, source: str):
            if not source.startswith("s3://"):
                return self._send(400, "bad source", "text/plain")
            r = vss().stream(source, self.headers.get("Range"))
            try:
                self.send_response(r.status_code)
                self.send_header("Content-Type", "video/mp4")
                for h in ("Content-Length", "Content-Range", "Accept-Ranges"):
                    if r.headers.get(h):
                        self.send_header(h, r.headers[h])
                self.send_header("Cache-Control", "private, max-age=600")
                self.end_headers()
                for chunk in r.iter_content(64 * 1024):
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                r.close()

        def do_POST(self):
            path = self.path.split("?")[0]
            try:
                body = self._body()
                if path == "/api/search":
                    return self._json(200, vss().search(str(body.get("query", ""))[:300]))
                if path == "/api/summarize":
                    import archive
                    return self._json(200, archive.summarize(str(body.get("query", ""))[:300],
                                                             list(body.get("hits") or [])[:12]))
                if path == "/api/switch":
                    return self._json(*switch_clip(body))
            except Exception as e:
                log("api error", path, type(e).__name__, str(e)[:200])
                msg = str(e) if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}"
                return self._json(502, {"error": msg[:300]})
            self._send(404, "not found", "text/plain")

        def _send(self, code, body, ctype):
            if isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html", "/dashboard", "/search"):
                return self._send(200, PAGE, "text/html; charset=utf-8")
            if path == "/api/state":
                return self._send(200, json.dumps(dict(SHARED.get_state(), services=services())),
                                  "application/json")
            if path == "/api/frame.jpg":
                return self._send(200, SHARED.get_jpeg(), "image/jpeg")
            if path == "/health":
                return self._send(200, '{"ok":true}', "application/json")
            if path == "/api/clips":
                return self._json(200, clips.listing(clip_dirs(), SHARED.get_state().get("video", "")))
            if path == "/api/presets":
                import archive
                return self._json(200, archive.PRESETS)
            if path == "/api/sensory_map":
                import archive
                return self._json(200, archive.sensory_map())
            if path == "/api/clip":
                from urllib.parse import parse_qs, urlsplit
                src = (parse_qs(urlsplit(self.path).query).get("source") or [""])[0]
                try:
                    return self._clip(src)
                except Exception as e:
                    return self._json(502, {"error": f"{type(e).__name__}: {str(e)[:200]}"})
            self._send(404, "not found", "text/plain")

    threading.Thread(target=lambda: __import__("archive"), daemon=True).start()   # weave import is slow
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"dashboard http://127.0.0.1:{port}/")
    return srv


# ------------------------------------------------------------------ runners
def pick_device():
    try:
        import torch
        if torch.cuda.is_available():
            return "0"
    except Exception:
        pass
    return "cpu"


def merge_events(det_events, audio_events):
    """Interleave detector + audio events by video timestamp (newest first)."""
    merged = list(det_events) + list(audio_events)
    merged.sort(key=lambda e: float(e.get("t", 0)), reverse=True)
    return merged[:40]


_DET: RobotSpaceDetector | None = None
_COSMOS: dict[str, CosmosWatch] = {}    # per clip, so switching back reuses scored windows


def run_video(path: Path, *, loop=True, max_seconds=None, stride=2, show=False, use_mic=False):
    global _DET
    if _DET is None:
        device = pick_device()
        log("device:", device)
        log("loading models (first run downloads weights)…")
        _DET = RobotSpaceDetector(device=device)
    det = _DET
    det.reset()
    log("probing audio…")
    audio = AudioWatch(path, use_mic=use_mic)
    log("audio:", audio.state()["source"], audio.state()["reason"] or "ok")
    cosmos = _COSMOS.get(str(path))
    if cosmos is None:
        cosmos = _COSMOS[str(path)] = CosmosWatch(path)
    cosmos.restart()
    log("cosmos:", "on" if cosmos.enabled else f"off ({cosmos.reason})")
    history: dict[tuple, dict] = {}     # every detector event of this pass, for lead times
    cstate = cosmos.state([])
    log("video:", path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        SHARED.set_status(f"could not open {path.name}")
        raise SystemExit(f"could not open video: {path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    log(f"source fps={src_fps:.1f} frames={n_frames} duration~{n_frames/src_fps:.1f}s stride={stride}")
    SHARED.set_status(f"playing {path.name} ({n_frames / src_fps:.0f} s)")

    playing = True
    fps_ema = 0.0
    t_wall0 = time.time()
    processed = 0
    while True:
        if SHARED.switch_pending():
            break
        ok, frame = cap.read()
        if not ok:
            if loop and max_seconds is None:
                log("looping video")
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                det.reset()
                cosmos.restart()
                history.clear()
                continue
            break
        frame_idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        if stride > 1 and (frame_idx % stride) != 0:
            continue
        video_t = frame_idx / src_fps
        if max_seconds is not None and video_t > max_seconds:
            break

        t0 = time.time()
        h, w = frame.shape[:2]
        if w > 1280:
            scale = 1280 / w
            frame = cv2.resize(frame, (1280, int(h * scale)))
        st = det.process(frame, video_t=video_t)
        audio.update(video_t)
        cosmos.update(video_t)
        astate = audio.state()
        st["audio"] = astate
        st["events"] = merge_events(st.get("events", []), astate.get("events", []))
        for e in st["events"]:
            history.setdefault((e["kind"], e["t"], e.get("robot") or e.get("agent")), e)
        if processed % 5 == 0:
            cstate = cosmos.state(list(history.values()))
        st["cosmos"] = cstate
        vis = det.annotate(frame, st)
        # audio banner strip
        if not astate.get("has_audio"):
            cv2.putText(vis, "AUDIO: no track", (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (0, 180, 255), 2, cv2.LINE_AA)
        elif astate.get("alerting"):
            cv2.putText(vis, f"LOUD: {astate.get('last_event') or astate.get('db')}", (12, 58),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2, cv2.LINE_AA)
        dt = time.time() - t0
        inst = 1.0 / max(dt, 1e-6)
        fps_ema = inst if processed == 0 else (0.9 * fps_ema + 0.1 * inst)
        processed += 1
        SHARED.publish(st, vis, path.name, fps_ema, playing)
        if processed % 20 == 0:
            inv = [r["label"] for r in st["robots"] if r["invaded"]]
            sud = [a["label"] for a in st["robots"] + st["people"] if a.get("sudden")]
            log(f"t={video_t:6.1f}s robots={st['summary']['robots']} "
                f"invaded={st['summary']['invaded']}{(' '+str(inv)) if inv else ''} "
                f"sudden={st['summary'].get('sudden',0)}{(' '+str(sud)) if sud else ''} "
                f"audio={'yes' if astate.get('has_audio') else 'none'} fps={fps_ema:.1f}")
        if show:
            cv2.imshow("equalEd warehouse", vis)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cap.release()
    st = det.state()
    deadline = time.time() + 30
    while (cosmos.enabled and cosmos.state([])["pending"] and time.time() < deadline
           and not SHARED.switch_pending()):
        time.sleep(0.5)
    st["cosmos"] = cosmos.state(list(history.values()))
    astate = audio.state()
    st["audio"] = astate
    st["events"] = merge_events(st.get("events", []), astate.get("events", []))
    with SHARED.lock:
        SHARED.state = dict(st, fps=round(fps_ema, 1), playing=False, video=path.name)
    audio.close()
    log(f"done. processed={processed} wall={time.time()-t_wall0:.1f}s")
    return st


def selftest():
    """Synthetic: personal space (people + AGVs intrude) + sudden movement + loudness baseline + no-audio state."""
    det = RobotSpaceDetector.__new__(RobotSpaceDetector)
    det.device = "cpu"
    det.tracks = {}
    det.next_id = 1
    det.frame_i = 0
    det.events = __import__("collections").deque(maxlen=80)
    det.video_t = 1.0
    det.fps_est = 0.0
    now = time.time()

    det.tracks[1] = Track(1, "robot", "humanoid-teal", np.array([100, 100, 160, 280], float), 0.9, now)
    det.tracks[2] = Track(2, "robot", "agv", np.array([500, 200, 620, 280], float), 0.8, now)
    det.tracks[3] = Track(3, "person", "person", np.array([400, 180, 460, 320], float), 0.9, now)
    for tr in det.tracks.values():
        tr.hist.append((now, tr.box.copy()))
    det._update_space(now)
    # invade — close but not overlapping the robot box (IoU would look like same body)
    det.tracks[3].box = np.array([175, 110, 235, 290], float)
    det.tracks[3].hist.append((now + 0.1, det.tracks[3].box.copy()))
    det._update_space(now + 0.1)
    det._update_space(now + 0.5)
    assert any(r["invaded"] for r in det.state()["robots"]), det.state()
    # sudden move: jump person far in short time
    det.tracks[3].box = np.array([500, 120, 560, 300], float)
    det.tracks[3].hist.append((now + 0.6, det.tracks[3].box.copy()))
    det.video_t = 2.0
    det._update_motion(now + 0.6)
    det._update_motion(now + 0.85)
    st = det.state()
    assert any(e["kind"] == "invasion" for e in st["events"]), st
    assert st["summary"].get("sudden", 0) >= 1 or any(e["kind"] == "sudden" for e in st["events"]), st

    # AGV next to the humanoid invades it; person right next to the AGV does not invade the AGV
    det.tracks[2].box = np.array([190, 230, 290, 290], float)
    det.tracks[3].box = np.array([300, 200, 360, 340], float)
    det._update_space(now + 1.0)
    det._update_space(now + 1.5)
    st = det.state()
    r1 = next(r for r in st["robots"] if r["id"] == 1)
    r2 = next(r for r in st["robots"] if r["id"] == 2)
    assert r1["invaded"] and r1["closest_label"] == "agv-2", r1
    assert r2["status"] == "agv" and r2["invaded"] is None and r2["invasion_count"] == 0, r2
    assert st["summary"]["agvs"] == 1 and st["summary"]["clear"] + st["summary"]["invaded"] == 1, st["summary"]

    # steady street noise (~-24 dB) must not alert; a sharp burst on top of it must
    rng = np.random.default_rng(0)
    eng = LoudnessEngine()
    for i in range(40):
        eng.feed(rng.normal(0, 0.063, 4000).astype(np.float32), now=now + i * 0.1)
    assert not eng.loud_event(now + 4.0)[0], (eng.db, eng.baseline)
    eng.feed(rng.normal(0, 0.7, 4000).astype(np.float32), now=now + 4.1)
    assert eng.loud_event(now + 4.15)[0], (eng.db, eng.baseline)

    # Cosmos reply parsing (prose and scored-list styles) and lead time from answer arrival
    assert parse_reply("People walk calmly. Nothing loud. RISK: 2") == (2, "People walk calmly.")
    r, why = parse_reply("Crowding around a person: 0.9\nRapid movement: 0.8\nCommotion: 0.3\n\nRISK: 8")
    assert r == 8 and why.startswith("triggers: crowding around a person 0.9"), why
    wins = [{"t0": t, "t1": t + 2, "risk": k, "latency": 1.0} for t, k in
            [(0, 2), (2, 2), (4, 7), (6, 8), (8, 2), (10, 2)]]
    evs = [{"kind": "invasion", "t": 11.0, "robot": "R1"}, {"kind": "invasion", "t": 11.5, "robot": "R2"},
           {"kind": "sudden", "t": 3.5, "agent": "P3"}, {"kind": "loud", "t": 0.2}]
    lt = {m["t"]: m for m in lead_times(wins, evs)}
    assert lt[11.0]["lead"] == 4.0 and lt[11.0]["events"] == 2 and lt[11.0]["rise_t"] == 6, lt
    assert lt[3.5]["lead"] is None and lt[3.5]["predictable"], lt
    assert lt[0.2]["kinds"] == ["loud"] and not lt[0.2]["predictable"], lt

    aw = AudioWatch(video_path=None, use_mic=False)
    # pretend probing a known no-audio path
    aw.has_audio = False
    aw.source = "none"
    aw.reason = "no audio track"
    a = aw.state()
    assert a["has_audio"] is False and "no audio" in a["reason"]

    print(json.dumps({
        "summary": st["summary"],
        "robots": st["robots"],
        "events": st["events"][:5],
        "audio": a,
    }, indent=2))
    print("selftest ok")
    return st


def main():
    ap = argparse.ArgumentParser(description="EqualEd VM warehouse dashboard")
    ap.add_argument("--video", help="path to warehouse mp4")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--once", action="store_true", help="do not loop the video")
    ap.add_argument("--max-seconds", type=float, default=None, help="stop after N video seconds")
    ap.add_argument("--stride", type=int, default=2, help="process every Nth frame")
    ap.add_argument("--no-server", action="store_true")
    ap.add_argument("--show", action="store_true", help="OpenCV window (needs display)")
    ap.add_argument("--mic", action="store_true", help="use microphone if file has no audio")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--download-sample", action="store_true",
                    help="fetch Warehouse_017 Camera.mp4 into /workspace/data/")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if args.download_sample:
        dest_dir = Path("/workspace/data")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{VIDEO_PREFIX}.mp4"
        if not dest.exists():
            url = ("https://huggingface.co/datasets/nvidia/PhysicalAI-SmartSpaces/resolve/main/"
                   "MTMC_Tracking_2025/test/Warehouse_017/videos/Camera.mp4")
            log("downloading", url)
            import urllib.request
            urllib.request.urlretrieve(url, dest)
        log("saved", dest)
        return

    if not args.no_server:
        start_server(args.port)

    if args.video:
        VIDEO_DIRS.append(Path(args.video).expanduser().resolve().parent)
        SEARCH_DIRS.insert(0, VIDEO_DIRS[-1])
    try:
        path = find_video(args.video)
    except SystemExit:
        if args.video or args.no_server:
            raise
        first = clips.ARCHIVE_CLIPS[0]["source"]
        log("no local video; fetching", first.rsplit("/", 1)[-1], "from the archive")
        switch_clip({"source": first})
        while not SHARED.switch_pending():
            time.sleep(0.5)
        path = SHARED.take_switch()
    while True:
        st = run_video(path, loop=not args.once, max_seconds=args.max_seconds,
                       stride=max(1, args.stride), show=args.show, use_mic=args.mic)
        nxt = SHARED.take_switch()
        if nxt is None:
            break
        log("switching to", nxt)
        path = nxt
    if args.once or args.max_seconds:
        print(json.dumps({
            "video": str(path),
            "summary": st["summary"],
            "audio": st.get("audio"),
            "cosmos": {k: v for k, v in (st.get("cosmos") or {}).items() if k != "timeline"},
            "cosmos_timeline": [(w["t0"], w["risk"], w["latency"]) for w in (st.get("cosmos") or {}).get("timeline", [])],
            "robots": st["robots"],
            "events_head": st["events"][:12],
        }, indent=2))
        return

    log("idle — dashboard still serving last state; pick a clip to play again. Ctrl+C to quit.")
    while True:
        time.sleep(0.5)
        nxt = SHARED.take_switch()
        if nxt is not None:
            path = nxt
            while path is not None:
                run_video(path, loop=True, stride=max(1, args.stride), use_mic=args.mic)
                path = SHARED.take_switch()


if __name__ == "__main__":
    main()
