"""Microphone: a fast loudness/spectrum reflex plus the YAMNet sound classifier.

Fast path : every 50 ms, loudness in dB and how much energy is high-pitched.
            A jump far above the room's normal level is a "sudden loud sound".
Smart path: every 0.4 s, YAMNet (521 everyday sounds) names what it heard,
            so a fire alarm counts but the professor talking does not.
Also keeps the last 60 s of audio for the live lecture transcript.
"""
import csv, os, threading, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 16000
TRIGGER_WORDS = ["siren", "alarm", "smoke detector", "buzzer", "beep", "dog", "bark", "blender",
                 "vacuum", "drill", "power tool", "hair dryer", "scream", "shout", "yell", "crying",
                 "baby cry", "glass", "shatter", "slam", "bang", "explosion", "whistl", "gunshot",
                 "firework", "squeal", "screech", "clatter", "smash", "air horn", "horn", "boom",
                 "crash", "thump", "knock", "chainsaw", "jackhammer", "applause", "cheering"]
SPEECHY = {"Speech", "Conversation", "Narration, monologue", "Male speech, man speaking",
           "Female speech, woman speaking", "Child speech, kid speaking", "Silence", "Inside, small room"}


def is_trigger_sound(name):
    n = name.lower()
    return any(w in n for w in TRIGGER_WORDS)


class AudioMonitor:
    def __init__(self):
        self.ok, self.error = False, ""
        self.db, self.baseline, self.hf = -90.0, -55.0, 0.0
        self.label, self.label_score = "", 0.0
        self.trigger_label, self.trigger_score, self.trigger_at = "", 0.0, -1e9
        self.loud_at, self.loud_db = -1e9, -90.0
        self.buf = np.zeros(SR * 60, np.float32)
        self.pos = 0                       # total samples ever written
        self.pos_time = time.time()        # wall clock of the newest sample
        self.lock = threading.Lock()
        self.interp = None
        self._load_yamnet()
        try:
            import sounddevice as sd
            self.stream = sd.InputStream(samplerate=SR, channels=1, blocksize=800,
                                         dtype="float32", callback=self._cb)
            self.stream.start()
            self.ok = True
        except Exception as e:
            self.error = f"microphone: {e}"
        threading.Thread(target=self._classify_loop, daemon=True).start()

    # -------------------------------------------------------------- capture
    def _cb(self, indata, frames, t, status):
        x = indata[:, 0].copy()
        n = len(x)
        with self.lock:
            i = self.pos % len(self.buf)
            if i + n <= len(self.buf):
                self.buf[i:i + n] = x
            else:
                k = len(self.buf) - i
                self.buf[i:] = x[:k]; self.buf[:n - k] = x[k:]
            self.pos += n
            self.pos_time = time.time()
        db = float(20 * np.log10(np.sqrt(np.mean(x * x)) + 1e-9))
        self.db = db
        spec = np.abs(np.fft.rfft(x * np.hanning(n)))          # the Fourier transform
        freqs = np.fft.rfftfreq(n, 1 / SR)
        self.hf = float(spec[freqs > 2000].sum() / (spec.sum() + 1e-9))
        now = time.time()
        if db - self.baseline > 20 and db > -30:
            if now - self.loud_at > 1.0:
                self.loud_db = db
            self.loud_at = now
        else:
            self.baseline = 0.98 * self.baseline + 0.02 * db   # follows the room over ~3 s

    def latest(self, n):
        with self.lock:
            n = min(n, self.pos, len(self.buf))
            end = self.pos % len(self.buf)
            idx = (np.arange(end - n, end)) % len(self.buf)
            return self.buf[idx].copy()

    def since(self, start_pos):
        """Audio recorded after sample number start_pos. Returns (audio, new_pos, wall time of first sample)."""
        with self.lock:
            pos, t_end = self.pos, self.pos_time
        n = min(pos - start_pos, len(self.buf))
        x = self.latest(n) if n > 0 else np.zeros(0, np.float32)
        return x, pos, t_end - n / SR

    # -------------------------------------------------------------- YAMNet
    def _load_yamnet(self):
        try:
            from ai_edge_litert.interpreter import Interpreter
            self.interp = Interpreter(model_path=os.path.join(HERE, "yamnet.tflite"))
            self.interp.allocate_tensors()
            self.inp = self.interp.get_input_details()[0]
            self.out = self.interp.get_output_details()[0]
            self.names = [r["display_name"] for r in csv.DictReader(open(os.path.join(HERE, "yamnet_class_map.csv")))]
        except Exception as e:
            self.interp = None
            self.error = f"sound classifier: {e}"

    def _classify_loop(self):
        n = 15600
        while True:
            time.sleep(0.4)
            if self.interp is None or self.pos < n:
                continue
            try:
                x = self.latest(n).reshape(self.inp["shape"]).astype(np.float32)
                self.interp.set_tensor(self.inp["index"], x)
                self.interp.invoke()
                s = self.interp.get_tensor(self.out["index"]).reshape(-1)
                top = int(s.argmax())
                self.label, self.label_score = self.names[top], float(s[top])
                for i in np.argsort(s)[::-1][:5]:
                    if s[i] > 0.25 and is_trigger_sound(self.names[i]):
                        self.trigger_label, self.trigger_score = self.names[i], float(s[i])
                        self.trigger_at = time.time()
                        break
            except Exception as e:
                self.error = f"sound classifier: {e}"

    # -------------------------------------------------------------- the trigger
    def loud_event(self, now):
        """(fired?, description). Classifier hit, or a loudness jump that wasn't just speech."""
        if now - self.trigger_at < 1.2:
            return True, f"{self.trigger_label} ({self.trigger_score:.0%})"
        if now - self.loud_at < 0.3 and self.label not in SPEECHY:
            return True, f"sudden loud sound ({self.loud_db:.0f} dB)"
        return False, ""


class NoAudio:
    """Stand-in when the microphone is off (self-test)."""
    ok, error, db, baseline, hf, label, label_score, pos = False, "microphone off", -90.0, -55.0, 0.0, "", 0.0, 0

    def loud_event(self, now):
        return False, ""

    def since(self, start_pos):
        return np.zeros(0, np.float32), 0, time.time()
