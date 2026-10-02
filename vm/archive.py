"""VAST archive search, clip proxy, sensory map and W&B summaries for the "Search triggers" page.

* VSS: JWT login with USERNAME / PASSWORD, `POST /api/v1/search`, clips via
  `/api/v1/videos/stream`. The JWT stays on the server; the browser plays clips through
  our own `/api/clip` proxy.
* Sensory map: `archive_sensory_labels.json` (all 2,352 archive clips labeled for sensory
  load on the laptop from Cosmos captions + YOLO counts).
* W&B Inference (`meta-llama/Llama-3.3-70B-Instruct`) turns the top hits into a short
  plain-language summary. Calls are traced with Weave when it is installed.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
INGRESS_URL = (os.environ.get("INGRESS_URL") or os.environ.get("VSS_URL")
               or "http://video-lab-team-17.cosmos.vastdata.com").rstrip("/")
VSS_USER = os.environ.get("VSS_USERNAME") or os.environ.get("USERNAME", "")
VSS_PASS = os.environ.get("VSS_PASSWORD") or os.environ.get("PASSWORD", "")
WANDB_BASE = "https://api.inference.wandb.ai/v1"
WANDB_MODEL = os.environ.get("WANDB_SUMMARY_MODEL", "meta-llama/Llama-3.3-70B-Instruct")
WANDB_PROJECT = f"{os.environ.get('WANDB_TEAM', 'vastdata')}/{os.environ.get('WANDB_PROJECT', 'team-17')}"
MIN_SIMILARITY = 0.2

PRESETS = [
    "crowd of people crossing the street",
    "people approaching fast",
    "person looking down at their phone",
    "an ambulance with flashing lights",
    "a forklift near people",
    "a streetcar or tram passing",
    "a cyclist or skateboarder moving fast",
]

try:
    import weave
except Exception:
    weave = None

_weave_lock = threading.Lock()
_weave_ready = False


def _op(fn):
    return weave.op()(fn) if weave else fn


def _init_weave() -> bool:
    global _weave_ready
    if not weave or not os.environ.get("WANDB_API_KEY"):
        return False
    with _weave_lock:
        if not _weave_ready:
            try:
                weave.init(WANDB_PROJECT)
                _weave_ready = True
            except Exception as e:
                print("weave init failed:", type(e).__name__, str(e)[:160], flush=True)
    return _weave_ready


# ------------------------------------------------------------------ VSS
def _check(r: requests.Response) -> None:
    if r.ok:
        return
    try:
        detail = str(r.json().get("detail", ""))
    except ValueError:
        detail = r.text
    if "not ready" in detail or "unavailable" in detail:
        raise RuntimeError(f"the archive's search model is offline right now (VSS {r.status_code}): {detail[:200]}")
    raise RuntimeError(f"archive returned {r.status_code}: {detail[:200]}")


class VSS:
    def __init__(self):
        self._token = None
        self._at = 0.0
        self._lock = threading.Lock()

    def token(self, force=False) -> str:
        with self._lock:
            if force or not self._token or time.time() - self._at > 1500:
                r = requests.post(INGRESS_URL + "/api/v1/auth/login", timeout=20,
                                  json={"username": VSS_USER, "password": VSS_PASS})
                r.raise_for_status()
                self._token, self._at = r.json()["access_token"], time.time()
            return self._token

    def _post(self, path: str, body: dict, timeout=60) -> dict:
        for force in (False, True):
            r = requests.post(INGRESS_URL + path, json=body, timeout=timeout,
                              headers={"Authorization": "Bearer " + self.token(force)})
            if r.status_code != 401:
                _check(r)
                return r.json()
        _check(r)
        return {}

    def search(self, query: str, top_k: int = 12) -> dict:
        t = time.time()
        j = self._post("/api/v1/search", {"query": query, "top_k": top_k, "llm_top_n": 1,
                                          "min_similarity": MIN_SIMILARITY, "include_public": True})
        hits = []
        for r in j.get("results", []):
            try:
                counts = json.loads(r.get("object_counts") or "{}")
            except Exception:
                counts = {}
            hits.append({
                "source": r.get("source"), "video": r.get("filename"),
                "original_video": r.get("original_video"),
                "start": r.get("segment_start_sec"), "end": r.get("segment_end_sec"),
                "score": round(r.get("similarity_score") or 0, 3),
                "caption": (r.get("reasoning_content") or "")[:600],
                "camera_id": r.get("camera_id"), "location": r.get("location"),
                "people": counts.get("person"),
            })
        synth = (j.get("llm_synthesis") or {}).get("response")
        return {"query": query, "hits": hits, "secs": round(time.time() - t, 2),
                "synthesis": (synth or "")[:800]}

    def stream(self, source: str, range_header: str | None = None) -> requests.Response:
        headers = {"Range": range_header} if range_header else {}
        for force in (False, True):
            r = requests.get(INGRESS_URL + "/api/v1/videos/stream", stream=True, timeout=30, headers=headers,
                             params={"source": source, "token": self.token(force)})
            if r.status_code != 401:
                return r
            r.close()
        return r


# ------------------------------------------------------------------ sensory map
def sensory_map() -> dict:
    for p in (HERE / "archive_sensory_labels.json", HERE.parent / "archive_sensory_labels.json"):
        if p.exists():
            d = json.loads(p.read_text())
            break
    else:
        return {"available": False, "reason": "archive_sensory_labels.json not found"}
    prefix = d.get("segment_uri_prefix", "")
    clips: dict[str, list] = {}
    for c in sorted(d.get("top_clips", []), key=lambda c: -c.get("load", 0)):
        clips.setdefault(c["camera_id"], []).append(dict(c, source=prefix + c["segment"]))
    places = sorted(d.get("places", []), key=lambda p: -p.get("avg_load", 0))
    for p in places:
        p["top_clips"] = clips.get(p["camera_id"], [])[:3]
    return {"available": True, "labeled_at": d.get("labeled_at"), "clips_labeled": d.get("clips_labeled"),
            "levels": d.get("levels"), "places": places}


# ------------------------------------------------------------------ W&B summary
@_op
def summarize_hits(query: str, hits: list[dict], places: list[dict]) -> str:
    from openai import OpenAI
    client = OpenAI(base_url=WANDB_BASE, api_key=os.environ["WANDB_API_KEY"], project=WANDB_PROJECT)
    lines = [f"- {h.get('location')} / {h.get('camera_id')}, {h.get('video')} at {h.get('start')}s, "
             f"{h.get('people') or 0} people, match {h.get('score')}: {(h.get('caption') or '')[:260]}"
             for h in hits[:8]]
    place_lines = [f"- {p['location']} / {p['camera_id']}: average load {p['avg_load']}/10, "
                   f"{p['high_pct']}% high, {p['calm_pct']}% calm, triggers {p['main_triggers']}"
                   for p in places]
    prompt = (
        "You help an autistic student avoid sensory overload. Using ONLY the facts below, write 3 to 5 "
        "short plain-language bullet points: which places and moments look most overwhelming for the "
        f"search \"{query}\", and which places are calmest. Mention camera/place names and times. "
        "No preamble.\n\nTop archive moments for the search:\n" + "\n".join(lines or ["(no hits)"]) +
        "\n\nSensory load by place (whole archive):\n" + "\n".join(place_lines or ["(not available)"]))
    r = client.chat.completions.create(model=WANDB_MODEL, temperature=0.2, max_tokens=350,
                                       messages=[{"role": "user", "content": prompt}])
    return r.choices[0].message.content or ""


def summarize(query: str, hits: list[dict]) -> dict:
    traced = _init_weave()
    m = sensory_map()
    t = time.time()
    text = summarize_hits(query, hits, m.get("places", []) if m.get("available") else [])
    return {"summary": text, "model": WANDB_MODEL, "secs": round(time.time() - t, 2), "weave": traced,
            "weave_project": WANDB_PROJECT if traced else None}
