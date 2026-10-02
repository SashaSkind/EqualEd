# EqualEd VM app: spotting sensory overload before it happens

**Live demo: [http://video-lab-team-17.cosmos.vastdata.com/app](http://video-lab-team-17.cosmos.vastdata.com/app)**
(runs on the team-17 cluster; the first load after a restart takes about 2 minutes).
The host has no public DNS: it resolves only inside the VAST lab network (the VM maps it to `10.146.15.121`
in `/etc/hosts`), so open it from the team VM's browser.

The app plays a clip, flags people and things that get **too close** to a person or are **rushing**,
watches for **loud** sound, and asks NVIDIA Cosmos3-Reason for a 0 to 10 sensory-risk score every 2 s
of video, then shows how early Cosmos saw each busy moment coming. A second and third tab search the
team's VAST video archive for triggers and rank archive places from most overwhelming to calmest.

## Tabs

| Tab | Shows |
|---|---|
| Live | Annotated camera with a clip picker (local files plus 6 archive clips), Cosmos risk and reason, "Seen it coming" lead time, people and things close to a person, sound level, risk-over-time chart, recent moments |
| Search the archive (VAST) | VSS search with preset trigger queries, play any hit, send its chunk to Live, W&B Inference summary (traced with Weave) |
| Sensory map (VAST) | Archive places ranked by sensory load, with play buttons for each place's top clips |

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r vm/requirements.txt
```

Weights (`yolo11n.pt`, `yoloe-11s-seg.pt`, CLIP, about 630 MB) download into the working directory on first
run, so start the app from a scratch folder, not from `vm/`.

Environment (from `/config/<team>.config` and `vast.env`, never committed): `INGRESS_URL`, `USERNAME`,
`PASSWORD` for the archive, `GPU_BEARER_TOKEN` for Cosmos, `WANDB_API_KEY` for the summary.

## Run on the VM

```bash
.venv/bin/python vm/app.py                          # first local clip, or the first archive clip
.venv/bin/python vm/app.py --video /path/clip.mp4   # a specific clip
# open http://127.0.0.1:8765/
```

Useful flags:

```bash
.venv/bin/python vm/app.py --once --max-seconds 45 --stride 3   # smoke test, print JSON
.venv/bin/python vm/app.py --selftest                           # geometry, audio, Cosmos parsing, lead time
.venv/bin/python vm/app.py --video clip.mp4 --port 8765 --mic   # mic when the file has no audio
```

## Deploy to the cluster

```bash
bash vm/deploy.sh
```

Follows `deployment/deploy-app-no-registry`: `python:3.12-slim`, code from a ConfigMap built from `vm/`,
credentials in a Secret, Ingress at `/app` on the team host. Needs `kubectl` in `~/bin` and
`KUBECONFIG=/config/team-17-k8s.yaml`. The pod installs CPU PyTorch and the requirements at start and talks
to the backend through `video-backend-service:8000`, because the public host does not resolve inside the
cluster. Re-run the script after code changes.

## Detection notes

| Agent / cue | How |
|---|---|
| People | YOLO11n `person` |
| Teal humanoids | person boxes with cyan chest-plate pixels (also catches some blue shirts on street clips) |
| Yellow AGVs | YOLOE open-vocab |
| Too close | a person or AGV center closer than **1.15 × the person's size** |
| AGV role | can close in on a person; has no personal space of its own |
| Rushing | box-center speed ≥ **1.35 body-lengths/s** |
| Loud | ≥ 18 dB jump over a baseline seeded from the clip's own level |
| Sensory risk | Cosmos3-Reason on each 2 s window with the START_HERE sensory prompt |

## Layout note

`vm/` stays flat (ConfigMap `--from-file`). Only small Python, HTML and docs live here; videos and `.pt`
weights stay outside git.
