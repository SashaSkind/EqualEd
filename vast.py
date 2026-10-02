"""Hackathon stack: VAST DataEngine + NVIDIA models on CoreWeave GPUs.

Live (from the laptop, needs GPU_BEARER_TOKEN):
  * Cosmos3-Reason  reasons over the last few seconds of classroom video
  * Canary-1B       transcribes the lecture (Whisper on the Mac is the fallback)
Archive (needs INGRESS_URL + USERNAME + PASSWORD):
  * VSS search / agent Q&A over the team's indexed footage -> "Sensory map"
App reasoning (needs WANDB_API_KEY):
  * Weights & Biases serverless inference for "What did I miss?"

Keys come from the environment or from vast.env next to this file (git-ignored).
Copy the values from the workshop VM's /config/<team>.config into vast.env.
"""
import base64, json, os, re, threading, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GPU_HOST = "166.19.38.112"
WANDB_BASE = "https://api.inference.wandb.ai/v1"

SENSORY_INGEST_PROMPT = (
    "Describe this clip for a student with autism who is sensitive to sensory overload. "
    "State how many people are visible and how close together they are (empty, few, crowded, packed). "
    "Note fast or sudden movement: running, rushing, people standing up together, vehicles braking or swerving. "
    "Note things that are likely loud: vehicles, horns, machinery, forklifts, construction, groups talking or shouting. "
    "Note flashing, flickering or very bright lights. End with one line: SENSORY LOAD: calm, moderate, or high."
)

ARCHIVE_TRIGGERS = [
    ("Crowding", "a crowd of people packed close together"),
    ("Rushing", "people running or rushing quickly"),
    ("Sudden movement", "a sudden movement, a vehicle braking hard or swerving"),
    ("Loud machinery", "heavy machinery, a forklift or a large truck moving nearby"),
    ("Busy traffic", "a busy intersection with many cars and pedestrians"),
    ("Bright lights", "flashing lights or bright headlights glaring"),
    ("Person near vehicle", "a person close to a moving vehicle"),
]
ARCHIVE_CALM = ("Calm", "a quiet empty corridor or street with nobody around")

# Footage for the autism demo: someone being crowded, surrounded or closed in on.
CROWDING_QUERIES = [
    "a group of people crowding around one person",
    "several people surrounding a single person",
    "a crowd of people packed close together",
    "people gathering closely in a hallway or corridor",
    "a person standing in a crowded indoor space",
    "many pedestrians crossing close together",
    "people rushing past someone",
    "a person close to a moving vehicle",
    "a forklift approaching a person in an aisle",
]


def load_settings():
    vals = {}
    p = os.path.join(HERE, "vast.env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("GPU_BEARER_TOKEN", "GPU_HOST", "COSMOS3_REASON_URL", "YOLO_URL", "COSMOS_EMBED1_URL",
              "CANARY_1B_URL", "INGRESS_URL", "USERNAME", "PASSWORD", "WANDB_API_KEY", "WANDB_TEAM",
              "WANDB_PROJECT", "WANDB_MODEL", "COSMOS3_REASON_MODEL"):
        if os.environ.get(k):
            vals[k] = os.environ[k]
    host = vals.get("GPU_HOST", DEFAULT_GPU_HOST)
    vals.setdefault("COSMOS3_REASON_URL", f"http://{host}:8001")
    vals.setdefault("YOLO_URL", f"http://{host}:8002")
    vals.setdefault("COSMOS_EMBED1_URL", f"http://{host}:8003")
    vals.setdefault("CANARY_1B_URL", f"http://{host}:8004")
    return vals


def _clean_json(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


class Vast:
    def __init__(self):
        self.s = load_settings()
        self.token = self.s.get("GPU_BEARER_TOKEN", "")
        self.gpu_on = bool(self.token) and "<" not in self.token
        self.archive_on = all(self.s.get(k) for k in ("INGRESS_URL", "USERNAME", "PASSWORD"))
        self.wandb_on = bool(self.s.get("WANDB_API_KEY"))
        self.cosmos_model = self.s.get("COSMOS3_REASON_MODEL", "")
        self.status = {"cosmos": "no key" if not self.gpu_on else "not checked",
                       "canary": "no key" if not self.gpu_on else "not checked",
                       "archive": "no login" if not self.archive_on else "not checked",
                       "wandb": "no key" if not self.wandb_on else "ready"}
        self.video_mode = True     # send real video; falls back to still frames if refused
        self._jwt, self._jwt_at = None, 0
        self._wandb_model = self.s.get("WANDB_MODEL", "")

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"}

    # ---------------------------------------------------------------- health
    def check(self):
        if self.gpu_on:
            for name, url, path in (("cosmos", self.s["COSMOS3_REASON_URL"], "/v1/health/ready"),
                                    ("canary", self.s["CANARY_1B_URL"], "/v1/health/ready")):
                try:
                    r = requests.get(url + path, headers=self._h(), timeout=6)
                    self.status[name] = "connected" if r.ok else f"error {r.status_code}"
                except Exception as e:
                    self.status[name] = f"unreachable ({type(e).__name__})"
            if self.status["cosmos"] == "connected" and not self.cosmos_model:
                try:
                    r = requests.get(self.s["COSMOS3_REASON_URL"] + "/v1/models", headers=self._h(), timeout=6)
                    self.cosmos_model = r.json()["data"][0]["id"]
                except Exception:
                    self.cosmos_model = "nvidia/cosmos3-nano-reasoner"
        if self.archive_on:
            try:
                self._login(force=True)
                self.status["archive"] = "connected"
            except Exception as e:
                self.status["archive"] = f"login failed ({e})"
        return dict(self.status)

    # ---------------------------------------------------------------- Cosmos3-Reason
    def cosmos(self, prompt, mp4_bytes=None, jpgs=None, max_tokens=300, timeout=40):
        content = [{"type": "text", "text": prompt}]
        if mp4_bytes is not None and self.video_mode:
            content.append({"type": "video_url",
                            "video_url": {"url": "data:video/mp4;base64," + base64.b64encode(mp4_bytes).decode()}})
        else:
            for j in (jpgs or [])[:6]:
                content.append({"type": "image_url",
                                "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(j).decode()}})
        body = {"model": self.cosmos_model or "nvidia/cosmos3-nano-reasoner",
                "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens, "temperature": 0}
        r = requests.post(self.s["COSMOS3_REASON_URL"] + "/v1/chat/completions", headers=self._h(), json=body, timeout=timeout)
        if r.status_code >= 400 and mp4_bytes is not None and self.video_mode and jpgs:
            self.video_mode = False          # server would not take our video; use still frames from now on
            return self.cosmos(prompt, None, jpgs, max_tokens, timeout)
        r.raise_for_status()
        self.status["cosmos"] = "connected"
        return r.json()["choices"][0]["message"]["content"] or ""

    def cosmos_risk(self, mp4_bytes, jpgs):
        prompt = ("This classroom camera watches a student who has sensory sensitivities (autism). "
                  "Watch the clip. Is anything likely to become loud, sudden, crowded or overwhelming for the "
                  "student in the next few seconds? Reply with JSON only: "
                  '{"risk": a number from 0 to 1, "what": "a short phrase", "why": "one short sentence"}')
        text = self.cosmos(prompt, mp4_bytes, jpgs, max_tokens=400)
        d = _clean_json(text) or {}
        try:
            risk = float(d.get("risk", 0))
        except Exception:
            risk = 0.0
        return {"risk": max(0.0, min(1.0, risk)), "what": str(d.get("what", ""))[:80],
                "why": str(d.get("why", re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()))[:240]}

    def cosmos_explain(self, mp4_bytes, jpgs, reaction):
        prompt = (f"A student with sensory sensitivities just showed signs of overload ({reaction}). "
                  "Watch this clip of the moments before. In two short sentences, say what in the scene most likely "
                  "overwhelmed them (noise, crowding, sudden movement, light) and one thing the teacher could do now.")
        text = self.cosmos(prompt, mp4_bytes, jpgs, max_tokens=500)
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()[:400]

    # ---------------------------------------------------------------- Canary-1B
    def canary(self, wav_bytes):
        r = requests.post(self.s["CANARY_1B_URL"] + "/v1/audio/transcriptions", headers=self._h(),
                          files={"file": ("chunk.wav", wav_bytes, "audio/wav")},
                          data={"language": "en-US"}, timeout=30)   # Riva: language only, no model field (VM_NOTES.md)
        r.raise_for_status()
        self.status["canary"] = "connected"
        try:
            return (r.json().get("text") or "").strip()
        except ValueError:
            return r.text.strip()

    # ---------------------------------------------------------------- VSS archive
    def _login(self, force=False):
        if self._jwt and not force and time.time() - self._jwt_at < 1800:
            return self._jwt
        r = requests.post(self.s["INGRESS_URL"].rstrip("/") + "/api/v1/auth/login",
                          json={"username": self.s["USERNAME"], "password": self.s["PASSWORD"]}, timeout=15)
        r.raise_for_status()
        self._jwt, self._jwt_at = r.json()["access_token"], time.time()
        return self._jwt

    def _api(self, method, path, **kw):
        for attempt in (0, 1):
            h = {"Authorization": f"Bearer {self._login(force=attempt == 1)}"}
            r = requests.request(method, self.s["INGRESS_URL"].rstrip("/") + path, headers=h, timeout=60, **kw)
            if r.status_code != 401:
                r.raise_for_status()
                return r.json()
        r.raise_for_status()

    def search(self, query, top_k=15, min_similarity=0.3, metadata_filters=None):
        return self._api("POST", "/api/v1/search", json={
            "query": query, "top_k": top_k, "llm_top_n": 1, "min_similarity": min_similarity,
            "metadata_filters": metadata_filters or {}, "include_public": True})

    def archive_ask(self, question):
        return self._api("POST", "/api/v1/agent/ask", json={"question": question, "top_k": 10})

    def sensory_map(self, min_similarity=0.3):
        """Search the archive for every trigger; rank cameras/places by sensory load."""
        places, clips = {}, []
        for label, q in ARCHIVE_TRIGGERS + [ARCHIVE_CALM]:
            res = self.search(q, top_k=20, min_similarity=min_similarity)
            for hit in res.get("results", []):
                meta = {k: hit.get(k) for k in ("camera_id", "location")}
                cam = meta.get("camera_id") or "unknown camera"
                loc = meta.get("location") or ""
                key = f"{loc} · {cam}" if loc else cam
                p = places.setdefault(key, {"place": key, "load": 0.0, "calm": 0.0, "hits": {}})
                sim = float(hit.get("similarity_score") or 0)
                if label == "Calm":
                    p["calm"] += sim
                else:
                    p["load"] += sim
                    p["hits"][label] = p["hits"].get(label, 0) + 1
                clips.append({"trigger": label, "place": key, "similarity": round(sim, 3),
                              "source": hit.get("source"), "start": hit.get("start_time") or hit.get("segment_start_sec"),
                              "caption": (hit.get("reasoning_content") or "")[:300]})
        ranked = sorted(places.values(), key=lambda p: -(p["load"] - p["calm"]))
        for p in ranked:
            p["score"] = round(p["load"] - p["calm"], 2)
            p["top"] = ", ".join(f"{k} ×{v}" for k, v in sorted(p["hits"].items(), key=lambda kv: -kv[1])[:3])
        clips.sort(key=lambda c: -c["similarity"])
        return {"places": ranked, "clips": clips[:40], "time": time.strftime("%I:%M %p").lstrip("0")}

    def find_footage(self, queries=None, per_query=10, min_similarity=0.25):
        """Search the archive with crowding questions; one ranked row per unique clip."""
        best = {}
        for q in queries or CROWDING_QUERIES:
            for hit in self.search(q, top_k=per_query, min_similarity=min_similarity).get("results", []):
                src = hit.get("source")
                if not src:
                    continue
                sim = float(hit.get("similarity_score") or 0)
                row = best.get(src)
                if row is None or sim > row["similarity"]:
                    best[src] = {"source": src, "similarity": round(sim, 3), "query": q,
                                 "camera_id": hit.get("camera_id") or "", "location": hit.get("location") or "",
                                 "original_video": hit.get("original_video") or "",
                                 "caption": (hit.get("reasoning_content") or "")[:400],
                                 "hits": (row or {}).get("hits", 0)}
                best[src]["hits"] = best[src].get("hits", 0) + 1
        rows = sorted(best.values(), key=lambda r: -(r["similarity"] + 0.05 * (r["hits"] - 1)))
        return rows

    def download(self, source, path):
        """Save one indexed clip (segment) to a local file."""
        url = self.s["INGRESS_URL"].rstrip("/") + "/api/v1/videos/stream"
        with requests.get(url, params={"source": source, "token": self._login()}, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        return path

    # ---------------------------------------------------------------- W&B inference
    def wandb_chat(self, prompt, timeout=60):
        h = {"Authorization": f"Bearer {self.s['WANDB_API_KEY']}"}
        if self.s.get("WANDB_TEAM") and self.s.get("WANDB_PROJECT"):
            h["OpenAI-Project"] = f"{self.s['WANDB_TEAM']}/{self.s['WANDB_PROJECT']}"
        if not self._wandb_model:
            ids = [m["id"] for m in requests.get(WANDB_BASE + "/models", headers=h, timeout=15).json().get("data", [])]
            prefs = ("Llama-3.3-70B", "Qwen3-235B", "DeepSeek-V3", "gpt-oss-120b", "Llama-4")
            self._wandb_model = next((i for p in prefs for i in ids if p.lower() in i.lower()), ids[0] if ids else "")
        r = requests.post(WANDB_BASE + "/chat/completions", headers=h, timeout=timeout, json={
            "model": self._wandb_model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 600})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip(), f"W&B ({self._wandb_model})"


class CosmosWatcher:
    """Every few seconds, sends the last ~3 s of video to Cosmos3-Reason and keeps its latest read."""

    def __init__(self, vast, every=4.0, start=True):
        self.vast, self.every = vast, every
        self.frames = []           # (t, small BGR frame)
        self.lock = threading.Lock()
        self.latest = None         # {"t", "risk", "what", "why", "latency"}
        self.error = ""
        self.calls = 0
        if vast.gpu_on and start:
            threading.Thread(target=self._loop, daemon=True).start()

    def push(self, t, frame):
        import cv2
        with self.lock:
            if not self.frames or t - self.frames[-1][0] >= 0.25:      # keep ~4 fps
                self.frames.append((t, cv2.resize(frame, (480, int(frame.shape[0] * 480 / frame.shape[1])))))
                self.frames = [f for f in self.frames if t - f[0] <= 8.0]

    def clip(self, seconds=3.0):
        import cv2, tempfile
        with self.lock:
            now = self.frames[-1][0] if self.frames else time.time()
            fr = [f for t, f in self.frames if now - t <= seconds]
        if len(fr) < 3:
            return None, []
        h, w = fr[0].shape[:2]
        path = tempfile.mktemp(suffix=".mp4")
        mp4 = None
        for fourcc in ("avc1", "mp4v"):
            vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*fourcc), 4, (w, h))
            if vw.isOpened():
                for f in fr:
                    vw.write(f)
                vw.release()
                if os.path.exists(path) and os.path.getsize(path) > 1000:
                    mp4 = open(path, "rb").read()
                    break
        try:
            os.remove(path)
        except OSError:
            pass
        step = max(1, len(fr) // 4)
        jpgs = [cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes() for f in fr[::step]][:4]
        return mp4, jpgs

    def _loop(self):
        self.vast.check()
        while True:
            time.sleep(self.every)
            mp4, jpgs = self.clip(3.0)
            if not jpgs:
                continue
            t0 = time.time()
            try:
                d = self.vast.cosmos_risk(mp4, jpgs)
                d["t"], d["latency"] = time.time(), round(time.time() - t0, 1)
                self.latest, self.error = d, ""
                self.calls += 1
            except Exception as e:
                self.error = f"{type(e).__name__}: {str(e)[:120]}"
                self.vast.status["cosmos"] = "error"

    def fresh(self, now, max_age=12.0):
        return self.latest if self.latest and now - self.latest["t"] <= max_age else None

    def explain_async(self, reaction, done):
        def run():
            mp4, jpgs = self.clip(6.0)
            if not jpgs:
                return
            try:
                done(self.vast.cosmos_explain(mp4, jpgs, reaction))
            except Exception as e:
                self.error = f"explain: {type(e).__name__}"
        if self.vast.gpu_on:
            threading.Thread(target=run, daemon=True).start()
