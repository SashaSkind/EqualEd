"""Audio watch for the VM dashboard: file track, optional mic, or 'no audio'.

Loudness reflex (same idea as the laptop audio.py): jump far above the recent
baseline = sudden loud sound. Optional YAMNet if `yamnet.tflite` + ai-edge-litert
are present; otherwise loudness alone is enough for phase 2.
"""
from __future__ import annotations

import collections
import csv
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

SR = 16000
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

DISTRESS = (
    "scream", "shout", "yell", "groan", "grunt", "crying", "sob", "wail", "moan",
    "gasp", "thud", "thump", "bang", "slam", "gunshot", "gunfire", "explosion",
    "firecracker", "fireworks", "glass", "shatter", "breaking", "fall", "whimper",
    "choking", "cough", "gagging", "alarm", "siren", "drill", "blender", "vacuum",
)


def probe_has_audio(path: str | Path) -> bool:
    """True if ffprobe reports at least one audio stream."""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            stderr=subprocess.STDOUT, text=True, timeout=30,
        )
        return bool(out.strip())
    except Exception:
        return False


def extract_mono_wav(path: str | Path, sr: int = SR) -> np.ndarray | None:
    """Decode video/audio file to mono float32 PCM via ffmpeg. None on failure."""
    try:
        raw = subprocess.check_output(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
             "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "1", "-ar", str(sr), "-"],
            stderr=subprocess.STDOUT, timeout=300,
        )
        if not raw:
            return None
        return np.frombuffer(raw, dtype=np.float32).copy()
    except Exception:
        return None


class LoudnessEngine:
    """Shared loudness + optional YAMNet classifier."""

    def __init__(self):
        self.db = -90.0
        self.baseline = -55.0
        self.label = ""
        self.label_score = 0.0
        self.loud_at = -1e9
        self.loud_db = -90.0
        self.trigger_at = -1e9
        self.trigger_label = ""
        self.trigger_score = 0.0
        self._interp = None
        self._names = []
        self._load_yamnet()

    def _load_yamnet(self):
        model = HERE / "yamnet.tflite"
        if not model.exists():
            model = ROOT / "yamnet.tflite"
        cmap = HERE / "yamnet_class_map.csv"
        if not cmap.exists():
            cmap = ROOT / "yamnet_class_map.csv"
        if not model.exists() or not cmap.exists():
            return
        try:
            from ai_edge_litert.interpreter import Interpreter
            self._interp = Interpreter(model_path=str(model))
            self._interp.allocate_tensors()
            self._inp = self._interp.get_input_details()[0]
            self._out = self._interp.get_output_details()[0]
            self._names = [r["display_name"] for r in csv.DictReader(open(cmap))]
        except Exception:
            self._interp = None

    def feed(self, samples: np.ndarray, now: float | None = None):
        if samples is None or len(samples) == 0:
            return
        now = time.time() if now is None else now
        x = samples.astype(np.float32)
        db = float(20 * np.log10(np.sqrt(np.mean(x * x)) + 1e-9))
        self.db = db
        if db - self.baseline > 18 and db > -35:
            if now - self.loud_at > 0.8:
                self.loud_db = db
            self.loud_at = now
        else:
            self.baseline = 0.98 * self.baseline + 0.02 * db
        if self._interp is not None and len(x) >= 15600:
            try:
                chunk = x[-15600:].reshape(self._inp["shape"]).astype(np.float32)
                self._interp.set_tensor(self._inp["index"], chunk)
                self._interp.invoke()
                s = self._interp.get_tensor(self._out["index"]).reshape(-1)
                top = int(s.argmax())
                self.label, self.label_score = self._names[top], float(s[top])
                for i in np.argsort(s)[::-1][:6]:
                    name = self._names[i].lower()
                    if s[i] >= 0.30 and any(w in name for w in DISTRESS):
                        self.trigger_label = self._names[i]
                        self.trigger_score = float(s[i])
                        self.trigger_at = now
                        break
            except Exception:
                pass

    def loud_event(self, now: float):
        if now - self.trigger_at < 1.5:
            return True, f"{self.trigger_label} ({self.trigger_score:.0%})"
        if now - self.loud_at < 0.4:
            return True, f"sudden loud sound ({self.loud_db:.0f} dB)"
        return False, ""


class AudioWatch:
    """Dashboard-facing audio status for a video (and optional mic)."""

    def __init__(self, video_path: str | Path | None = None, use_mic: bool = False):
        self.video_path = str(video_path) if video_path else None
        self.engine = LoudnessEngine()
        self.pcm: np.ndarray | None = None
        self.has_audio = False
        self.source = "none"
        self.reason = "no audio source"
        self.events: collections.deque = collections.deque(maxlen=40)
        self.last_fire = -1e9
        self._lock = threading.Lock()
        self._mic = None

        if self.video_path:
            if probe_has_audio(self.video_path):
                self.pcm = extract_mono_wav(self.video_path)
                if self.pcm is not None and len(self.pcm) > SR // 2:
                    self.has_audio = True
                    self.source = "file"
                    self.reason = ""
                else:
                    self.has_audio = False
                    self.source = "none"
                    self.reason = "audio stream present but decode failed"
            else:
                self.has_audio = False
                self.source = "none"
                self.reason = "no audio track"

        if use_mic and not self.has_audio:
            self._try_mic()

    def _try_mic(self):
        try:
            import sounddevice as sd

            def cb(indata, frames, t, status):
                self.engine.feed(indata[:, 0].copy())

            self._mic = sd.InputStream(samplerate=SR, channels=1, blocksize=800,
                                       dtype="float32", callback=cb)
            self._mic.start()
            self.has_audio = True
            self.source = "mic"
            self.reason = ""
        except Exception as e:
            if not self.has_audio:
                self.reason = f"no audio track; mic unavailable ({e})"

    def update(self, video_t: float, now: float | None = None):
        """Advance file-audio cursor to video_t; update loudness; maybe log event."""
        now = time.time() if now is None else now
        if self.source == "file" and self.pcm is not None:
            end = int(video_t * SR)
            start = max(0, end - int(0.25 * SR))
            if end > start and end <= len(self.pcm):
                self.engine.feed(self.pcm[start:end], now=now)
            elif end > len(self.pcm) and len(self.pcm) > 0:
                self.engine.feed(self.pcm[-int(0.25 * SR):], now=now)
        # mic feeds itself via callback
        fired, desc = self.engine.loud_event(now)
        if fired and now - self.last_fire > 1.5:
            self.last_fire = now
            self.events.appendleft({
                "t": round(video_t, 2),
                "wall": time.strftime("%H:%M:%S"),
                "kind": "loud",
                "detail": desc,
                "source": self.source,
            })
        return fired, desc

    def state(self) -> dict:
        eng = self.engine
        return {
            "has_audio": self.has_audio,
            "source": self.source,          # file | mic | none
            "reason": self.reason,          # human-readable when has_audio is False
            "ok": self.has_audio,
            "db": round(eng.db, 1),
            "baseline": round(eng.baseline, 1),
            "label": eng.label,
            "label_score": round(eng.label_score, 2),
            "alerting": (time.time() - eng.loud_at < 0.5) or (time.time() - eng.trigger_at < 1.5),
            "last_event": eng.trigger_label or (
                f"sudden loud sound ({eng.loud_db:.0f} dB)" if time.time() - eng.loud_at < 2 else ""
            ),
            "events": list(self.events)[:20],
            "hint": (
                "This warehouse clip has no audio track. "
                "Test loud-noise with: python vm/app.py --video clip_with_audio.mp4 "
                "or --mic on a machine with a microphone."
                if self.reason.startswith("no audio") else ""
            ),
        }

    def close(self):
        if self._mic is not None:
            try:
                self._mic.stop(); self._mic.close()
            except Exception:
                pass
