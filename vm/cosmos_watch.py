"""Cosmos3-Reason sensory-risk timeline.

Every WINDOW seconds of video, the last WINDOW seconds are cut to a 960 px H.264 clip and
sent to Cosmos3-Reason with the sensory prompt. The reply's `RISK: n` and first sentence
become one point on the timeline. Calls run on worker threads so playback never waits.

Lead time: for each busy moment the detector flags (invasion / sudden move), find the run
of elevated-risk windows just before it. The lead is measured from when Cosmos's *answer
arrived* (window end + call latency) to the moment, so it is what a live user would get.
"""
from __future__ import annotations

import os
import queue
import re
import shutil
import statistics
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import requests

COSMOS_URL = os.environ.get("COSMOS3_REASON_URL", "http://166.19.38.112:8001").rstrip("/")
COSMOS_MODEL = os.environ.get("COSMOS3_REASON_MODEL", "nvidia/cosmos3-nano-reasoner")
WINDOW = 2.0
WORKERS = 2
LOOKBACK = 12.0        # how far before a moment a risk rise still counts
RISE_STEP = 2          # elevated = at least this much above the clip's median risk ...
RISE_MIN = 3           # ... and at least this high
RISE_CAP = 6           # but never above this, or a clip that is busy throughout can never warn
MOMENT_GAP = 3.0       # detector events closer than this belong to one moment

SENSORY_PROMPT = (
    "You are helping an autistic person avoid sensory overload. Describe this clip for search. "
    "List any of these triggers you see, each with a confidence score: crowding around a person; "
    "someone entering personal space; someone approaching fast; rapid movement; commotion; a person "
    "standing up suddenly; several people getting up; a chair being moved; flicker or a sudden light "
    "change; an object likely to make a loud noise (blender, drill, vacuum, dog, alarm, megaphone, "
    "dishes, door). Say what is likely to get loud in the next few seconds. Also note anyone covering "
    "their ears, rocking, putting their head down, looking away or using a phone. End with `RISK: <0-10>`."
)
RISK_RE = re.compile(r"RISK:\s*`?\s*(\d+)", re.I)
SCORED_RE = re.compile(r"^\s*[-*]?\s*([A-Za-z][^:\n]{2,60}):\s*([01](?:\.\d+)?)\s*$", re.M)


def _ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def parse_reply(text: str) -> tuple[int | None, str]:
    hits = RISK_RE.findall(text or "")
    risk = min(int(hits[-1]), 10) if hits else None
    # Cosmos sometimes answers with a "trigger: score" list instead of prose
    scored = sorted(((float(s), n.strip()) for n, s in SCORED_RE.findall(text or "")), reverse=True)
    if len(scored) >= 3:
        top = [f"{n.lower()} {s:.1f}" for s, n in scored[:3] if s >= 0.5]
        return risk, ("triggers: " + ", ".join(top)) if top else "no triggers scored above 0.5"
    body = RISK_RE.sub("", text or "").strip().strip("`").strip()
    first = re.split(r"(?<=[.!?])\s+", body, maxsplit=1)[0] if body else ""
    return risk, first[:220]


class CosmosWatch:
    def __init__(self, video_path: Path | None):
        self.video_path = Path(video_path) if video_path else None
        self.token = os.environ.get("GPU_BEARER_TOKEN", "")
        self.ffmpeg = _ffmpeg()
        self.enabled = bool(self.token and self.ffmpeg and self.video_path)
        self.reason = ("" if self.enabled else
                       "GPU_BEARER_TOKEN not set" if not self.token else
                       "ffmpeg not found" if not self.ffmpeg else "no video file")
        self.lock = threading.Lock()
        self.windows: dict[float, dict] = {}   # t0 -> window; kept across loops as a cache
        self.next_t = WINDOW
        self.duration = None
        self.q: queue.Queue = queue.Queue()
        self.calls = 0
        self.errors = 0
        if self.enabled:
            for _ in range(WORKERS):
                threading.Thread(target=self._worker, daemon=True).start()

    # ---------------------------------------------------------------- feed
    def update(self, video_t: float):
        if not self.enabled:
            return
        while video_t >= self.next_t:
            self._submit(round(self.next_t - WINDOW, 2))
            self.next_t += WINDOW

    def restart(self):
        """Video looped: windows are cached, so only the cursor resets."""
        self.next_t = WINDOW

    def _submit(self, t0: float):
        with self.lock:
            if t0 in self.windows and self.windows[t0]["status"] != "error":
                return
            self.windows[t0] = {"t0": t0, "t1": round(t0 + WINDOW, 2), "status": "pending",
                                "risk": None, "reason": "", "latency": None}
        self.q.put(t0)

    # ---------------------------------------------------------------- worker
    def _worker(self):
        while True:
            t0 = self.q.get()
            try:
                clip = self._cut(t0)
                t = time.time()
                text = self._ask(clip)
                latency = time.time() - t
                risk, reason = parse_reply(text)
                upd = {"status": "done" if risk is not None else "no-risk", "risk": risk,
                       "reason": reason, "latency": round(latency, 2), "text": text[:1200]}
                self.calls += 1
            except Exception as e:
                self.errors += 1
                upd = {"status": "error", "reason": f"{type(e).__name__}: {str(e)[:160]}"}
            with self.lock:
                self.windows[t0].update(upd)

    def _cut(self, t0: float) -> bytes:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "w.mp4"
            subprocess.run(
                [self.ffmpeg, "-v", "error", "-y", "-ss", f"{t0:.2f}", "-i", str(self.video_path),
                 "-t", f"{WINDOW:.2f}", "-an", "-vf", "scale=960:-2", "-c:v", "libx264",
                 "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", str(out)],
                check=True, timeout=60, capture_output=True)
            return out.read_bytes()

    def _ask(self, mp4: bytes) -> str:
        import base64
        body = {"model": COSMOS_MODEL, "temperature": 0.2, "max_tokens": 700,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": SENSORY_PROMPT},
                    {"type": "video_url", "video_url": {
                        "url": "data:video/mp4;base64," + base64.b64encode(mp4).decode()}}]}]}
        r = requests.post(COSMOS_URL + "/v1/chat/completions", json=body, timeout=90,
                          headers={"Authorization": "Bearer " + self.token})
        r.raise_for_status()
        return r.json()["choices"][0]["message"].get("content") or ""

    # ---------------------------------------------------------------- read
    def timeline(self) -> list[dict]:
        with self.lock:
            return [dict(w) for _, w in sorted(self.windows.items())]

    def state(self, det_events: list[dict]) -> dict:
        tl = self.timeline()
        done = [w for w in tl if w["risk"] is not None]
        latest = done[-1] if done else None
        leads = lead_times(done, det_events)
        got = [m["lead"] for m in leads if m["lead"] is not None]
        lat = [w["latency"] for w in done if w.get("latency")]
        return {
            "enabled": self.enabled, "reason": self.reason, "model": COSMOS_MODEL,
            "window_s": WINDOW, "calls": self.calls, "errors": self.errors,
            "pending": sum(1 for w in tl if w["status"] == "pending"),
            "timeline": [{k: w.get(k) for k in ("t0", "t1", "risk", "reason", "latency", "status")} for w in tl],
            "latest": latest and {k: latest.get(k) for k in ("t0", "t1", "risk", "reason", "latency")},
            "moments": leads,
            "baseline": _baseline(done),
            "lead_best": max(got) if got else None,
            "lead_median": round(statistics.median(got), 1) if got else None,
            "predicted": len(got), "moments_n": sum(1 for m in leads if m["predictable"]),
            "too_early": sum(1 for m in leads if not m["predictable"]),
            "latency_median": round(statistics.median(lat), 2) if lat else None,
        }


def _baseline(done: list[dict]) -> float:
    return statistics.median([w["risk"] for w in done]) if done else 0.0


MOMENT_KINDS = ("invasion", "sudden", "loud")


def moments(det_events: list[dict]) -> list[dict]:
    """Collapse invasion / sudden / loud events into moments at least MOMENT_GAP apart."""
    evs = sorted((e for e in det_events if e.get("kind") in MOMENT_KINDS),
                 key=lambda e: float(e["t"]))
    out: list[dict] = []
    for e in evs:
        t = float(e["t"])
        if out and t - out[-1]["last"] < MOMENT_GAP:
            out[-1]["last"] = t
            out[-1]["n"] += 1
            out[-1]["kinds"].add(e["kind"])
            continue
        out.append({"t": t, "last": t, "n": 1, "kinds": {e["kind"]},
                    "what": f"{e['kind']} {e.get('robot') or e.get('agent') or ''}".strip()})
    return out


def lead_times(done: list[dict], det_events: list[dict]) -> list[dict]:
    base = _baseline(done)
    level = min(max(base + RISE_STEP, RISE_MIN), RISE_CAP)
    res = []
    for m in moments(det_events):
        te = m["t"]
        # windows whose answer had arrived before the moment
        before = [w for w in done if w["t1"] + (w.get("latency") or 0) <= te and w["t1"] >= te - LOOKBACK]
        lead, rise = None, None
        if before:
            i = max((k for k, w in enumerate(before) if w["risk"] >= level), default=None)
            # the warning must still be standing: one of the last two answers is elevated
            if i is not None and i >= len(before) - 2:
                j = i
                while j > 0 and before[j - 1]["risk"] >= level and before[j]["t0"] - before[j - 1]["t1"] < 0.01:
                    j -= 1
                rise = before[j]
                lead = round(te - (rise["t1"] + (rise.get("latency") or 0)), 1)
        res.append({"t": round(te, 1), "what": m["what"], "events": m["n"], "kinds": sorted(m["kinds"]),
                    "lead": lead, "rise_t": rise and rise["t1"], "rise_risk": rise and rise["risk"],
                    "level": level, "predictable": bool(before)})
    return res
