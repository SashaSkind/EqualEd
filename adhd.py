"""ADHD attention rewind.

1. Watches the student's face: looking away or on the phone for longer than a few
   seconds is an "attention drop", stamped with the clock time.
2. Transcribes the lecture from the microphone on this Mac (Whisper, offline).
3. "What did I miss?" sends only the lecture transcript text and the drop times to
   Claude, which answers with a recap of exactly the parts they missed.
"""
import json, os, shutil, subprocess, threading, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 16000
NOSE, L_EYE, R_EYE = 0, 1, 2
CLAUDE_MODEL = "claude-opus-5"


def clock(t):
    return time.strftime("%I:%M:%S %p", time.localtime(t)).lstrip("0")


class Attention:
    def __init__(self, away_seconds=6.0):
        self.away_seconds = away_seconds
        self.state, self.reason = "focused", ""
        self.away_since, self.away_reason = None, ""
        self.drops = []          # {"start", "end", "reason"}
        self.current = None
        self.focused_time, self.total_time, self.last_t = 0.0, 0.0, None

    def update(self, now, subject, phone_near):
        reason = None
        if subject is None:
            reason = "left the desk"
        else:
            _, b, k, c, _ = subject
            eyes = [i for i in (L_EYE, R_EYE) if c[i] > 0.5]
            if phone_near:
                reason = "on the phone"
            elif c[NOSE] < 0.5 or not eyes:
                reason = "looking away"
            elif len(eyes) == 1:
                reason = "head turned away"
            else:
                eye_mid = (k[L_EYE][0] + k[R_EYE][0]) / 2
                eye_d = max(abs(k[L_EYE][0] - k[R_EYE][0]), 4)
                if abs(k[NOSE][0] - eye_mid) / eye_d > 0.9:
                    reason = "head turned away"
        if self.last_t is not None:
            dt = min(now - self.last_t, 1.0)
            self.total_time += dt
            if not reason:
                self.focused_time += dt
        self.last_t = now
        new_drop = None
        if reason:
            if self.away_since is None:
                self.away_since, self.away_reason = now, reason
            if self.current is None and now - self.away_since >= self.away_seconds:
                self.current = {"start": self.away_since, "end": None, "reason": self.away_reason}
                self.drops.append(self.current)
                new_drop = self.current
            self.state, self.reason = "away", reason
        else:
            if self.current is not None:
                self.current["end"] = now
            self.current, self.away_since = None, None
            self.state, self.reason = "focused", ""
        return new_drop

    def focused_pct(self):
        return 100.0 * self.focused_time / self.total_time if self.total_time > 1 else 100.0


class Transcriber:
    def __init__(self, audio, chunk_seconds=8.0):
        self.audio, self.chunk = audio, chunk_seconds
        self.segments = []       # {"t", "end", "text"}
        self.lock = threading.Lock()
        self.status = "loading speech model..."
        self.model = None
        if getattr(audio, "ok", False):
            threading.Thread(target=self._run, daemon=True).start()
        else:
            self.status = "off (no microphone)"

    def _run(self):
        try:
            from faster_whisper import WhisperModel
            self.model = WhisperModel("base.en", device="cpu", compute_type="int8")
            self.status = "listening"
        except Exception as e:
            self.status = f"speech model failed: {e}"
            return
        pos = self.audio.pos
        f = open(os.path.join(HERE, "events", "transcript.jsonl"), "a")
        while True:
            time.sleep(self.chunk)
            x, pos, t0 = self.audio.since(pos)
            if len(x) < SR or float(np.sqrt(np.mean(x * x))) < 0.003:
                continue
            try:
                segs, _ = self.model.transcribe(x, language="en", beam_size=1, vad_filter=True)
                for s in segs:
                    text = s.text.strip()
                    if not text:
                        continue
                    seg = {"t": t0 + s.start, "end": t0 + s.end, "text": text}
                    with self.lock:
                        self.segments.append(seg)
                    f.write(json.dumps(seg) + "\n"); f.flush()
            except Exception as e:
                self.status = f"transcribe error: {e}"

    def recent(self, n=80):
        with self.lock:
            return list(self.segments[-n:])


def _prompt(question, segments, drops, now):
    lines = "\n".join(f"[{clock(s['t'])}] {s['text']}" for s in segments)
    missed = "\n".join(f"- {clock(d['start'])} to {clock(d['end'] or now)} ({d['reason']})" for d in drops) or "- none"
    return (
        "You help a student with ADHD catch up on a lecture.\n\n"
        f"<lecture_transcript>\n{lines}\n</lecture_transcript>\n\n"
        f"<times_student_was_distracted>\n{missed}\n</times_student_was_distracted>\n\n"
        f"<student_question>\n{question}\n</student_question>\n\n"
        "Answer in plain, friendly language in under 150 words, using only the transcript. "
        "If the answer was covered while the student was distracted, say what time it was covered "
        "and give a short recap of what they missed. If the transcript does not cover it, say so."
    )


def _local_answer(question, segments, drops, now):
    words = {w.strip("?.,!").lower() for w in question.split() if len(w) > 3}
    hits = [s for s in segments if words & {w.strip("?.,!").lower() for w in s["text"].split()}]
    in_drop = [s for s in hits if any(d["start"] <= s["t"] <= (d["end"] or now) for d in drops)]
    pick = in_drop or hits
    if not pick:
        return "I couldn't find that in the lecture transcript yet."
    head = "You missed this while distracted:" if in_drop else "Here is what the lecture said:"
    return head + "\n" + "\n".join(f"[{clock(s['t'])}] {s['text']}" for s in pick[:6])


def ask(question, segments, drops):
    """Returns (answer, source)."""
    now = time.time()
    if not segments:
        return "No lecture has been transcribed yet. Play or give the lecture near the Mac's microphone first.", "none"
    prompt = _prompt(question, segments, drops, now)
    # 1) Anthropic SDK, if this Mac has API credentials (env, `ant auth login`, or a .env file here)
    envf = os.path.join(HERE, ".env")
    if os.path.exists(envf):
        for line in open(envf):
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))
    try:
        import anthropic
        client = anthropic.Anthropic()
        resp = client.beta.messages.create(
            model=CLAUDE_MODEL, max_tokens=2000,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        )
        if resp.stop_reason != "refusal":
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            if text:
                return text, "Claude API"
    except Exception:
        pass
    # 2) Claude Code on this Mac (uses the local Claude Code sign-in)
    exe = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    if os.path.exists(exe):
        try:
            r = subprocess.run([exe, "-p", "Answer the student's question using the context above.", "--model", "opus"],
                               input=prompt, capture_output=True, text=True, timeout=90, cwd=os.path.expanduser("~"))
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip(), "Claude"
        except Exception:
            pass
    # 3) Offline fallback
    return _local_answer(question, segments, drops, now), "offline search"
