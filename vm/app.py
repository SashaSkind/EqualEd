#!/usr/bin/env python3
"""EqualEd VM app — warehouse robot personal-space dashboard (phase 1).

Processes the Warehouse_017 camera clip, tracks robots, flags personal-space
invasions, and serves a live status dashboard on http://0.0.0.0:8765/

Usage:
  python app.py                         # auto-find video, loop, serve dashboard
  python app.py --video /path/to.mp4
  python app.py --once --max-seconds 30 # smoke test, print summary JSON
  python app.py --selftest              # synthetic frames, no video needed
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
from detector import RobotSpaceDetector  # noqa: E402

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


# ------------------------------------------------------------------ dashboard
DASHBOARD = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EqualEd · Robot personal space</title>
<style>
:root{
  --bg:#0e1412; --panel:#15201c; --ink:#e8f0ea; --muted:#8aa396;
  --line:#24352e; --ok:#3dbe7a; --bad:#e4574d; --warn:#e0a23a; --accent:#5ec4a2;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
  --sans:"IBM Plex Sans",system-ui,sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:
  radial-gradient(1200px 600px at 10% -10%,#1a3a2e 0%,transparent 55%),
  radial-gradient(900px 500px at 100% 0%,#2a2418 0%,transparent 50%),
  var(--bg);color:var(--ink);font:15px/1.45 var(--sans);min-height:100vh}
header{padding:18px 22px 8px;display:flex;flex-wrap:wrap;gap:12px;align-items:end;justify-content:space-between}
.brand{font-size:28px;font-weight:700;letter-spacing:-.02em}
.brand span{color:var(--accent)}
.sub{color:var(--muted);font-size:13px;margin-top:4px}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 12px;font:12.5px var(--mono)}
.chip b{color:var(--accent)}
.chip.bad b{color:var(--bad)}.chip.ok b{color:var(--ok)}
main{padding:8px 22px 28px;display:grid;grid-template-columns:1.3fr .9fr;gap:16px}
@media(max-width:960px){main{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.panel h2{margin:0;padding:12px 14px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--line)}
.stage{position:relative;background:#0a0f0d;aspect-ratio:16/9}
.stage img{width:100%;height:100%;object-fit:contain;display:block;background:#000}
.meta{padding:10px 14px;font:12px var(--mono);color:var(--muted);border-top:1px solid var(--line)}
.list{padding:8px 10px;max-height:420px;overflow:auto}
.row{display:grid;grid-template-columns:72px 1fr auto;gap:10px;align-items:center;
  padding:10px 8px;border-bottom:1px solid var(--line)}
.row:last-child{border:0}
.badge{font:11px var(--mono);padding:4px 8px;border-radius:6px;text-transform:uppercase;letter-spacing:.04em}
.badge.invaded{background:color-mix(in srgb,var(--bad) 22%,transparent);color:var(--bad)}
.badge.clear{background:color-mix(in srgb,var(--ok) 18%,transparent);color:var(--ok)}
.badge.person{background:color-mix(in srgb,var(--warn) 16%,transparent);color:var(--warn)}
.name{font-weight:600}.detail{font-size:12.5px;color:var(--muted);margin-top:2px}
.ev{padding:8px 14px;border-bottom:1px solid var(--line);font-size:13px}
.ev .t{font:11.5px var(--mono);color:var(--muted)}
.ev .tag{display:inline-block;font:10.5px var(--mono);padding:1px 6px;border-radius:4px;margin-right:6px}
.ev .tag.invasion{background:color-mix(in srgb,var(--bad) 25%,transparent);color:var(--bad)}
.ev .tag.clear{background:color-mix(in srgb,var(--ok) 20%,transparent);color:var(--ok)}
.empty{padding:18px;color:var(--muted)}
footer{padding:0 22px 24px;color:var(--muted);font-size:12.5px}
</style></head><body>
<header>
  <div>
    <div class="brand">equal<span>Ed</span> · warehouse shield</div>
    <div class="sub">Phase 1 — live personal-space status per robot</div>
  </div>
  <div class="chips" id="chips"></div>
</header>
<main>
  <section class="panel">
    <h2>Annotated camera</h2>
    <div class="stage"><img id="frame" alt="live frame"></div>
    <div class="meta" id="meta">waiting for frames…</div>
  </section>
  <div style="display:flex;flex-direction:column;gap:16px">
    <section class="panel">
      <h2>Robots</h2>
      <div class="list" id="robots"><div class="empty">No robots yet</div></div>
    </section>
    <section class="panel">
      <h2>Recent events</h2>
      <div class="list" id="events" style="max-height:220px"><div class="empty">Nothing yet</div></div>
    </section>
  </div>
</main>
<footer>Personal space = center distance &lt; 1.15× robot height (flat-camera estimate). Phase 2 will add sudden movement + loud-noise alerts.</footer>
<script>
const $ = id => document.getElementById(id);
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));}
function chips(S){
  const s=S.summary||{};
  $('chips').innerHTML = `
    <div class="chip">t <b>${esc(S.video_t)}s</b></div>
    <div class="chip">robots <b>${s.robots||0}</b></div>
    <div class="chip bad">invaded <b>${s.invaded||0}</b></div>
    <div class="chip ok">clear <b>${s.clear||0}</b></div>
    <div class="chip">people <b>${s.people||0}</b></div>
    <div class="chip">fps <b>${esc(S.fps||0)}</b></div>`;
}
function robots(S){
  const rows=(S.robots||[]);
  if(!rows.length){$('robots').innerHTML='<div class="empty">No robots in view</div>';return;}
  $('robots').innerHTML = rows.map(r=>{
    const st=r.invaded?'invaded':'clear';
    const near=r.closest!=null?`nearest ${esc(r.closest_label)} · ${r.closest} body-lengths`:'no neighbour measured';
    return `<div class="row"><div class="badge ${st}">${st}</div>
      <div><div class="name">${esc(r.label)} · ${esc(r.subtype)}</div>
      <div class="detail">${near} · invasions ×${r.invasion_count}</div></div>
      <div class="detail">${Math.round((r.conf||0)*100)}%</div></div>`;
  }).join('');
}
function events(S){
  const ev=S.events||[];
  if(!ev.length){$('events').innerHTML='<div class="empty">No invasions yet</div>';return;}
  $('events').innerHTML = ev.slice(0,25).map(e=>`<div class="ev">
    <div class="t">${esc(e.wall)} · video ${esc(e.t)}s</div>
    <div><span class="tag ${esc(e.kind)}">${esc(e.kind)}</span>
      <b>${esc(e.robot)}</b> ${esc(e.detail)}</div></div>`).join('');
}
async function tick(){
  try{
    const r=await fetch('/api/state',{cache:'no-store'});
    const S=await r.json();
    chips(S); robots(S); events(S);
    $('meta').textContent = `${S.video||''} · frame ${S.frame} · playing=${S.playing}`;
    $('frame').src = '/api/frame.jpg?ts='+Date.now();
  }catch(e){}
}
tick(); setInterval(tick, 700);
</script></body></html>
"""


class AppState:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {
            "video_t": 0, "frame": 0, "robots": [], "people": [],
            "summary": {"robots": 0, "people": 0, "invaded": 0, "clear": 0},
            "events": [], "fps": 0, "playing": False, "video": "",
        }
        self.jpeg = self._placeholder_jpeg("starting…")

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
            return dict(self.state)

    def get_jpeg(self) -> bytes:
        with self.lock:
            return self.jpeg


SHARED = AppState()


def start_server(port: int):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

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
            if path in ("/", "/index.html", "/dashboard"):
                return self._send(200, DASHBOARD, "text/html; charset=utf-8")
            if path == "/api/state":
                return self._send(200, json.dumps(SHARED.get_state()), "application/json")
            if path == "/api/frame.jpg":
                return self._send(200, SHARED.get_jpeg(), "image/jpeg")
            if path == "/health":
                return self._send(200, '{"ok":true}', "application/json")
            self._send(404, "not found", "text/plain")

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


def run_video(path: Path, *, loop=True, max_seconds=None, stride=2, show=False):
    device = pick_device()
    log("device:", device)
    log("loading models (first run downloads weights)…")
    det = RobotSpaceDetector(device=device)
    log("video:", path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"could not open video: {path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    log(f"source fps={src_fps:.1f} frames={n_frames} duration~{n_frames/src_fps:.1f}s stride={stride}")

    playing = True
    fps_ema = 0.0
    t_wall0 = time.time()
    processed = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            if loop and max_seconds is None:
                log("looping video")
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                det.reset()
                continue
            break
        frame_idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        if stride > 1 and (frame_idx % stride) != 0:
            continue
        video_t = frame_idx / src_fps
        if max_seconds is not None and video_t > max_seconds:
            break

        t0 = time.time()
        # downscale for speed on CPU
        h, w = frame.shape[:2]
        if w > 1280:
            scale = 1280 / w
            frame = cv2.resize(frame, (1280, int(h * scale)))
        st = det.process(frame, video_t=video_t)
        vis = det.annotate(frame, st)
        dt = time.time() - t0
        inst = 1.0 / max(dt, 1e-6)
        fps_ema = inst if processed == 0 else (0.9 * fps_ema + 0.1 * inst)
        processed += 1
        SHARED.publish(st, vis, path.name, fps_ema, playing)
        if processed % 20 == 0:
            inv = [r["label"] for r in st["robots"] if r["invaded"]]
            log(f"t={video_t:6.1f}s robots={st['summary']['robots']} "
                f"invaded={st['summary']['invaded']}{(' '+str(inv)) if inv else ''} "
                f"people={st['summary']['people']} fps={fps_ema:.1f}")
        if show:
            cv2.imshow("equalEd warehouse", vis)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    st = det.state()
    with SHARED.lock:
        SHARED.state = dict(st, fps=round(fps_ema, 1), playing=False, video=path.name)
    log(f"done. processed={processed} wall={time.time()-t_wall0:.1f}s")
    return st


def selftest():
    """Synthetic scene: two robots, one person walking into space."""
    # Skip YOLO weight load — only exercise tracking geometry.
    det = RobotSpaceDetector.__new__(RobotSpaceDetector)
    det.device = "cpu"
    det.tracks = {}
    det.next_id = 1
    det.frame_i = 0
    det.events = __import__("collections").deque(maxlen=80)
    det.video_t = 1.0
    det.fps_est = 0.0
    now = time.time()
    from detector import Track

    det.tracks[1] = Track(1, "robot", "humanoid-teal", np.array([100, 100, 160, 280], float), 0.9, now)
    det.tracks[2] = Track(2, "robot", "agv", np.array([500, 200, 620, 280], float), 0.8, now)
    det.tracks[3] = Track(3, "person", "person", np.array([400, 180, 460, 320], float), 0.9, now)
    det._update_space(now)
    # move person next to robot 1 and hold past HOLD_S
    det.tracks[3].box = np.array([120, 120, 180, 300], float)
    det._update_space(now + 0.1)
    det._update_space(now + 0.5)
    st = det.state()
    assert any(r["invaded"] for r in st["robots"]), st
    assert any(e["kind"] == "invasion" for e in st["events"]), st
    print(json.dumps({"summary": st["summary"], "robots": st["robots"], "events": st["events"][:3]}, indent=2))
    print("selftest ok")
    return st


def main():
    ap = argparse.ArgumentParser(description="EqualEd VM warehouse personal-space dashboard")
    ap.add_argument("--video", help="path to warehouse mp4")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--once", action="store_true", help="do not loop the video")
    ap.add_argument("--max-seconds", type=float, default=None, help="stop after N video seconds")
    ap.add_argument("--stride", type=int, default=2, help="process every Nth frame")
    ap.add_argument("--no-server", action="store_true")
    ap.add_argument("--show", action="store_true", help="OpenCV window (needs display)")
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

    path = find_video(args.video)
    st = run_video(path, loop=not args.once, max_seconds=args.max_seconds,
                   stride=max(1, args.stride), show=args.show)
    if args.once or args.max_seconds:
        print(json.dumps({
            "video": str(path),
            "summary": st["summary"],
            "robots": st["robots"],
            "events_head": st["events"][:10],
        }, indent=2))
        return

    # keep server alive while looping finished? run_video loops forever unless --once
    log("idle — dashboard still serving last state. Ctrl+C to quit.")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
