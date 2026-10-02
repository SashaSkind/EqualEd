"""Clip library for the live shield: local video files plus demo chunks from the VAST archive.

Archive chunks are downloaded once through the VSS stream endpoint into CLIP_DIR and then
played like any local file.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

CLIP_DIR = Path(os.environ.get("EQUALED_CLIPS", "/tmp/equaled_clips"))
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".avi", ".webm")
CHUNKS = "s3://team-17-vss-chunks/team-17/"
ALLOWED_PREFIXES = (CHUNKS, "s3://team-17-vss-chunks-segments/")

# 30 s parent chunks picked from archive searches (see VM_NOTES.md)
ARCHIVE_CLIPS = [
    {"label": "SF crosswalk, crowd surging (sf2)", "source": CHUNKS + "20261001_095927_sf2_chunk_0019.mp4"},
    {"label": "SF crosswalk, crowd crossing (sf4)", "source": CHUNKS + "20261001_101759_sf4_chunk_0026.mp4"},
    {"label": "SF ambulance with flashing lights (sf1)", "source": CHUNKS + "20261001_094630_sf1_chunk_0013.mp4"},
    {"label": "Warehouse, people + robots (Camera_02, re-captioned)",
     "source": CHUNKS + "20261001_080845_2025_test_Warehouse_017_Camera_02_chunk_0006.mp4"},
    {"label": "Synthetic warehouse, forklift near people (10 s)",
     "source": CHUNKS + "20261001_075529_16face5576497e69c190_03a2937960b9e61f1c99_run_7_seed_900334964.ceiling_04.rgb_chunk_0000.mp4"},
    {"label": "Toronto dashcam, streetcar passing", "source": CHUNKS + "20261001_071213_set06_video_chunk_0004.mp4"},
]

_lock = threading.Lock()
_downloading: dict[str, str] = {}   # source -> status text


def cached_path(source: str) -> Path:
    return CLIP_DIR / source.rsplit("/", 1)[-1]


def local_clips(dirs: list[Path]) -> list[Path]:
    seen, out = set(), []
    for d in list(dirs) + [CLIP_DIR]:
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix.lower() in VIDEO_EXT and p.stat().st_size > 0:
                rp = p.resolve()
                if rp not in seen:
                    seen.add(rp)
                    out.append(rp)
    return out


def listing(dirs: list[Path], current: str) -> dict:
    archive = []
    for c in ARCHIVE_CLIPS:
        p = cached_path(c["source"])
        archive.append(dict(c, cached=p.exists(), path=str(p) if p.exists() else None,
                            status=_downloading.get(c["source"], "")))
    local = [{"name": p.name, "path": str(p)} for p in local_clips(dirs)
             if p.parent != CLIP_DIR.resolve()]
    return {"current": current, "local": local, "archive": archive}


def fetch(source: str, stream_fn, on_ready, on_status) -> None:
    """Download an archive chunk in the background, then call on_ready(path)."""
    if not source.startswith(ALLOWED_PREFIXES) or not source.endswith(".mp4"):
        on_status(f"refused source {source[:80]}")
        return
    dest = cached_path(source)
    if dest.exists():
        on_ready(dest)
        return
    with _lock:
        if source in _downloading:
            return
        _downloading[source] = "downloading"

    def run():
        try:
            CLIP_DIR.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".part")
            on_status(f"downloading {dest.name} from the archive…")
            r = stream_fn(source)
            r.raise_for_status()
            n = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(256 * 1024):
                    f.write(chunk)
                    n += len(chunk)
            r.close()
            tmp.rename(dest)
            on_status(f"downloaded {dest.name} ({n / 1e6:.1f} MB)")
            on_ready(dest)
        except Exception as e:
            on_status(f"download failed: {type(e).__name__}: {str(e)[:160]}")
        finally:
            with _lock:
                _downloading.pop(source, None)

    threading.Thread(target=run, daemon=True).start()
