"""Calming sound for overload moments, played only on AirPods/headphones."""
import json, os, subprocess, threading, time, wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SOUND = os.path.join(HERE, "calm_sound_v2.wav")
ALLOW_SPEAKERS = False   # True = also play out loud on the laptop speakers


def make_sound(path=SOUND, seconds=48, sr=44100):
    """A soft, warm pad of slow chords (C maj7, A min7, F maj7, G6) with a faint ocean under it.
    Breathes in and out every 10 s to pace slow breathing. No high or sharp sounds; 6 s fade in/out."""
    rng = np.random.default_rng(7)
    n = seconds * sr
    t = np.arange(n) / sr
    chords = [(130.81, 164.81, 196.00, 246.94), (110.00, 130.81, 164.81, 196.00),
              (87.31, 110.00, 130.81, 164.81), (98.00, 123.47, 146.83, 164.81)]
    seg = seconds / len(chords)
    pad = np.zeros(n)
    for i, ch in enumerate(chords):
        center = (i + 0.5) * seg
        w = np.clip(1 - np.abs(t - center) / (seg * 0.75), 0, 1)
        w = 0.5 - 0.5 * np.cos(np.pi * w)                       # smooth crossfade between chords
        tone = np.zeros(n)
        for f in ch:
            for det in (1.0, 1.003):                              # gentle chorus
                tone += np.sin(2 * np.pi * f * det * t) + 0.25 * np.sin(4 * np.pi * f * det * t)
        pad += w * tone
    ocean = rng.standard_normal(n)
    for k in (400, 200):                                          # heavy low-pass: a soft wash, no hiss
        ocean = np.convolve(ocean, np.ones(k) / k, mode="same")
    ocean /= np.abs(ocean).max() + 1e-9
    ocean *= 0.5 + 0.5 * np.sin(2 * np.pi * t / 10.0 - np.pi / 2)  # waves in time with the breath
    breath = 0.8 + 0.2 * np.sin(2 * np.pi * t / 10.0 - np.pi / 2)
    mix = pad / (np.abs(pad).max() + 1e-9) * breath + 0.18 * ocean
    fade = np.minimum(1, np.minimum(t / 6.0, (seconds - t) / 6.0))
    mix = mix * fade
    mix = mix / (np.abs(mix).max() + 1e-9) * 0.35                 # quiet
    data = (np.stack([mix, np.roll(mix, int(sr * 0.008))], 1) * 32767).astype(np.int16)
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
        self.proc = subprocess.Popen(["afplay", "-v", "0.6", SOUND])
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
