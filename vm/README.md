# EqualEd VM app — warehouse robot personal space

Phase 1: detect robots in the warehouse clip, decide whether each robot's
personal space is invaded, and show a live status dashboard.

## Video

Looks for a file whose name starts with:

```
20261001_080730_test_Wherehouse_017_Camera_chunck_00
```

Default search paths: `/workspace/data/`, `vm/data/`, `/data`, `./data`.

If you do not have the clip locally (it is the NVIDIA PhysicalAI-SmartSpaces
`Warehouse_017` camera export), fetch it:

```bash
cd /workspace
.venv/bin/python vm/app.py --download-sample
# saves /workspace/data/20261001_080730_test_Wherehouse_017_Camera_chunck_00.mp4
```

Do **not** commit the mp4.

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
# smoke test first 45s of video, print JSON summary, no loop
.venv/bin/python vm/app.py --once --max-seconds 45 --stride 3

# geometry unit test (no video / no GPU)
.venv/bin/python vm/app.py --selftest

# custom path / port
.venv/bin/python vm/app.py --video /path/to/clip.mp4 --port 8765
```

## What it shows

- Per-robot row: **invaded** / **clear**, subtype (`humanoid-teal` / `agv` / …),
  nearest person distance in body-lengths, invasion count
- Annotated camera frame with personal-space circles
- Event log when space flips invaded ↔ clear

## How detection works

| Agent | How |
|---|---|
| People | YOLO11n `person` |
| Teal humanoid robots | person boxes with cyan/teal chassis pixels |
| Dark humanoid robots | tall, dark metal person boxes |
| Yellow AGVs / platforms | YOLOE open-vocab (`yellow AGV`, …) |

Personal space (same flat-camera idea as the laptop sensory demo): a person
invades when center distance &lt; **1.15 × robot box height**, with a short hold
to avoid flicker.

## Phase 2 (not in this pass)

Sudden movement, loud-noise / audio distress, and other classroom alerts —
wire into the same `/api/state` + dashboard once phase 1 is solid.

## Layout note

`vm/` stays flat (ConfigMap `--from-file vm/`). Only small Python/HTML/docs
live here; video and `.pt` weights stay outside git.
