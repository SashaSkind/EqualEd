# EqualEd VM app — warehouse robot shield

Phases 1–2: detect robots in the warehouse clip, flag **personal-space invasions**
and **sudden movement**, watch for **loud sounds** when audio exists, and show a
live status dashboard.

## Video

Looks for a file whose name starts with:

```
20261001_080730_test_Wherehouse_017_Camera_chunck_00
```

Default search paths: `/workspace/data/`, `vm/data/`, `/data`, `./data`.

```bash
cd /workspace
.venv/bin/python vm/app.py --download-sample
# saves /workspace/data/20261001_080730_test_Wherehouse_017_Camera_chunck_00.mp4
```

Do **not** commit the mp4. This Warehouse_017 camera export has **no audio track**.

## Setup

```bash
cd /workspace
python3 -m venv .venv
.venv/bin/pip install -r vm/requirements.txt
```

Weights (`yolo11n.pt`, `yoloe-11s-seg.pt`, CLIP) download on first run.

## Run (dashboard)

```bash
cd /workspace
.venv/bin/python vm/app.py
# open http://127.0.0.1:8765/
```

Useful flags:

```bash
# smoke test first 45s, print JSON, no loop
.venv/bin/python vm/app.py --once --max-seconds 45 --stride 3

# geometry + audio-state unit test
.venv/bin/python vm/app.py --selftest

# custom path / port / try mic when file has no audio
.venv/bin/python vm/app.py --video /path/to/clip.mp4 --port 8765 --mic
```

## Dashboard panels

| Panel | Shows |
|---|---|
| Annotated camera | Boxes, personal-space circles, MOVE tags |
| Audio | **No audio track** for this clip, or dB / loud alert when audio exists |
| Robots | invaded / clear + nearest person + speed |
| Moving agents | agents currently over the sudden-move threshold |
| Events | invasion, clear, sudden, loud |

## Detection notes

| Agent / cue | How |
|---|---|
| People | YOLO11n `person` |
| Teal humanoids | person boxes with cyan chest-plate pixels |
| Yellow AGVs | YOLOE open-vocab |
| Personal space | person center &lt; **1.15 × robot size** |
| Sudden movement | box-center speed ≥ **1.35 body-lengths/s** |
| Loud noise | file audio (ffmpeg) or `--mic`; loudness jump (+ optional YAMNet) |

### Testing loud noise on a clip *with* audio

```bash
# any mp4/mov that ffprobe shows an audio stream
.venv/bin/python vm/app.py --video /path/to/clip_with_sound.mp4 --once --max-seconds 20
# or fall back to microphone when the file has none:
.venv/bin/python vm/app.py --mic
```

## Layout note

`vm/` stays flat (ConfigMap `--from-file vm/`). Only small Python/HTML/docs
live here; video and `.pt` weights stay outside git.
