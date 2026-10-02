"""Find hackathon archive footage of people crowding an individual, and download it.

  .venv/bin/python find_footage.py              search + download the top 12 clips
  .venv/bin/python find_footage.py --top 20     more clips
  .venv/bin/python find_footage.py --list       search only, no download
  .venv/bin/python find_footage.py --query "a crowd around a student"   your own question

Needs INGRESS_URL, USERNAME, PASSWORD in vast.env (from the workshop VM's /config/<team>.config).
Clips land in archive_clips/ with an index.json; open the dashboard's Sensory map tab to play
any of them through EqualEd. The clips are the organizers' licensed footage: keep them local.
"""
import json, os, re, sys
from vast import Vast, CROWDING_QUERIES

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "archive_clips")


def safe(s):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", s)[:40].strip("-")


def run(top=12, queries=None, download=True, log=print):
    v = Vast()
    if not v.archive_on:
        raise SystemExit("Add INGRESS_URL, USERNAME and PASSWORD to vast.env first (copy them from the workshop VM).")
    rows = v.find_footage(queries)
    log(f"{len(rows)} matching clips. Top {min(top, len(rows))}:")
    os.makedirs(OUT, exist_ok=True)
    keep = []
    for i, r in enumerate(rows[:top], 1):
        log(f"{i:2d}. {r['similarity']:.2f}  {r['location'] or '?':14s} {r['camera_id'] or '?':22s} {r['query']}")
        log(f"     {r['caption'][:150]}")
        if download:
            name = f"{i:02d}_{safe(r['camera_id'] or 'cam')}_{safe(r['query'])}.mp4"
            try:
                r["file"] = v.download(r["source"], os.path.join(OUT, name))
            except Exception as e:
                r["file"], r["error"] = None, f"{type(e).__name__}: {str(e)[:120]}"
                log(f"     download failed: {r['error']}")
        keep.append(r)
    json.dump(keep, open(os.path.join(OUT, "index.json"), "w"), indent=2)
    return keep


if __name__ == "__main__":
    a = sys.argv[1:]
    top = int(a[a.index("--top") + 1]) if "--top" in a else 12
    qs = [a[a.index("--query") + 1]] if "--query" in a else None
    run(top, qs, download="--list" not in a)
