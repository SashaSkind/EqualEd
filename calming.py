"""Calming sound for overload moments, played only on AirPods/headphones."""
import json, os, subprocess, threading, time, wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SOUND = os.path.join(HERE, "calm_sound.wav")
ALLOW_SPEAKERS = False   # True = also play out loud on the laptop speakers


def make_sound(path=SOUND, seconds=40, sr=44100):
    """Soft ocean-like brown noise that slowly swells, under a quiet warm chord."""
    rng = np.random.default_rng(7)
    n = seconds * sr
    t = np.arange(n) / sr
    brown = np.cumsum(rng.standard_normal(n)); brown -= np.convolve(brown, np.ones(4410) / 4410, "same")
    brown /= np.abs(brown).max() + 1e-9
    swell = 0.55 + 0.45 * np.sin(2 * np.pi * t / 10.0)          # one slow wave every 10 s
    chord = sum(np.sin(2 * np.pi * f * t) * a for f, a in ((220.0, .5), (277.18, .35), (329.63, .3), (110.0, .4)))
    chord *= 0.5 + 0.5 * np.sin(2 * np.pi * t / 16.0)           # gentle breathing in and out
    mix = 0.55 * brown * swell + 0.12 * chord
    fade = np.minimum(1, np.minimum(t / 4.0, (seconds - t) / 4.0))
    mix = mix * fade / (np.abs(mix).max() + 1e-9) * 0.5
    left = mix; right = np.roll(mix, int(sr * 0.012))           # slight stereo width
    data = (np.stack([left, right], 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr); w.writeframes(data.tobytes())


class Calming:
    def __init__(self):
        if not os.path.exists(SOUND):
            make_sound()
        self.proc = None
        self.say_proc = None
        self.allow_speakers = ALLOW_SPEAKERS   # the dashboard can flip this for stage demos
        self.output_name = "checking..."
        self.headphones = False
        threading.Thread(target=self._watch_output, daemon=True).start()

    def _watch_output(self):
        while True:
            try:
                out = subprocess.run(["system_profiler", "SPAudioDataType", "-json"],
                                     capture_output=True, text=True, timeout=20).stdout
                for item in json.loads(out)["SPAudioDataType"][0]["_items"]:
                    if item.get("coreaudio_default_audio_output_device") == "spaudio_yes":
                        self.output_name = item.get("_name", "?")
                        tr = item.get("coreaudio_device_transport", "")
                        self.headphones = ("bluetooth" in tr or "headphone" in self.output_name.lower()
                                           or "airpods" in self.output_name.lower())
            except Exception:
                pass
            time.sleep(8)

    def playing(self):
        return self.proc is not None and self.proc.poll() is None

    def play(self):
        """Returns where it played, or None if it was held back."""
        if self.playing():
            return self.output_name
        if not self.can_play():
            return None
        self.proc = subprocess.Popen(["afplay", "-v", "0.7", SOUND])
        return self.output_name

    def can_play(self):
        return self.headphones or self.allow_speakers

    def stop(self):
        if self.playing():
            self.proc.terminate()

    def say(self, text):
        """Read text aloud (dyslexia support). Same headphones-only rule."""
        if not self.can_play():
            return None
        if self.say_proc is not None and self.say_proc.poll() is None:
            self.say_proc.terminate()
        self.say_proc = subprocess.Popen(["say", "-r", "170", text])
        return self.output_name
