# EqualEd VM app: instructions for the coding agent on the VAST VM

You are running inside the VAST Builders Challenge VM for **team-17**. The repo you are in
is EqualEd. The root of this repo is the **local app** (a Mac app that watches a live webcam).
Do not modify, move or delete anything outside `vm/`. Your job is the **VM app**, which lives
only in `vm/`.

## What EqualEd is

One camera, one model stack, help for three neurodivergent conditions:

- **Autism, sensory shield (lead feature).** Spot what is about to get loud or overwhelming
  *before* it happens (a blender, a drill, a dog, someone standing up fast, a chair dragged,
  crowding, a sudden light change), give a risk score and warn early. Audio confirms it.
- **ADHD, attention rewind.** Mark the moments a person looked away or picked up their phone,
  line them up with the transcript, and answer "what did I miss about X?"
- **Dyslexia, read-along.** Stretch goal, skip unless everything else works.

The local app does this live on a laptop. The VM app does the same analysis on **recorded
video**: the team's indexed archive plus any clips we upload, using the models on CoreWeave.

## Skills and rules

The challenge skills live in `.cursor/skills/`, symlinked from `~/vast-builders-challenge`.
Use a matching skill before writing raw REST calls. Follow `.cursor/rules/build-day.mdc`.
Credentials are already in environment variables (source `/config/*.config` if one is
missing). Never print, log or commit secret values. List variable names only, with
`env | cut -d= -f1 | sort`.

## Phase 1: look around and write down what you find (do this first, then stop)

Write everything you learn into `vm/VM_NOTES.md`. A second agent working on the laptop
reads that file to keep the local app in sync, so be concrete: real model ids, real
request and response shapes, real latencies, real video names. No secret values.

1. Health check: `deployment/health`, `gpu/model-health`, then `gpu/model-smoke-test`.
2. List the variable names that exist for WANDB, GPU, COSMOS, YOLO, CANARY, INGRESS and VDB.
3. Log in and inventory the archive (`retrieval/login`, `retrieval/dashboard`,
   `retrieval/videos`, `retrieval/list-metadata`): which videos and cameras exist, how many
   segments, and whether the clips **have audio tracks** (check one segment with ffprobe).
4. Cosmos3-Reason: send one 2-second segment as `video_url` with the prompt in the
   "Sensory prompt" section below. Record the latency and the raw answer. Also try one JPEG
   frame as `image_url` and note whether it works.
5. YOLO11: run `/v1/infer` on the same segment. Record the response fields and the latency.
6. Canary-1B: if any clip has audio, extract a WAV and transcribe it. Record the model id
   and the latency.
7. W&B Inference: call `https://api.inference.wandb.ai/v1/models` with `WANDB_API_KEY`.
   Write down the available models, which ones accept images, and which one is fast. Send
   one chat completion with `project=f"{WANDB_TEAM}/{WANDB_PROJECT}"`.
8. Find out whether we can upload our own clip (`ingest/upload-video`). Do not upload
   anything yet. Just write down what it needs.
9. Search the archive (`retrieval/search`) for: "person standing up suddenly", "crowd of
   people", "person covering ears", "loud machine", "person looking at phone". Record
   which ones return good hits. Those are the gaps a re-ingest would fill.

Commit `vm/VM_NOTES.md`, push, and report back with a short summary and a proposed
re-ingest plan. **Do not re-ingest until a human says go.**

## Phase 2: build the VM app (after the human approves)

A small web app in `vm/`, deployed with `deployment/deploy-app-no-registry` to
`http://video-lab-team-17.cosmos.vastdata.com/app`.

- Python, stdlib or FastAPI plus `requests` and `openai`. Keep `vm/` **flat** (no
  subfolders) and under 1 MiB in total, because the ConfigMap is built with
  `--from-file vm/`, which does not recurse.
- Do not commit large model files. If YAMNet is needed, the pod downloads it at startup:
  `https://storage.googleapis.com/download.tensorflow.org/models/tflite/task_library/audio_classification/android/lite-model_yamnet_classification_tflite_1.tflite`
  (use `ai-edge-litert` to run it, with `yamnet_class_map.csv` from the repo root).
- Add `GPU_BEARER_TOKEN`, `COSMOS3_REASON_URL`, `YOLO_URL`, `CANARY_1B_URL`, `WANDB_API_KEY`,
  `WANDB_TEAM` and `WANDB_PROJECT` to the app's Kubernetes Secret, next to the VSS
  credentials.
- Use Weave (`weave.init(f"{WANDB_TEAM}/{WANDB_PROJECT}")`) so every LLM call is traced.

Pages, in priority order:

1. **Sensory timeline** (autism). Pick a video from the archive. For each segment show the
   YOLO objects, the Cosmos sensory risk (0 to 10) with its reason and "what may get loud
   next", and audio distress if the clip has sound. Highlight the moments where the risk
   rose *before* the loud or busy moment and show the lead time.
2. **Search triggers.** A box backed by VSS search plus W&B: "show every moment of sudden
   crowding", with clip playback.
3. **Attention rewind** (ADHD). For a clip with speech: Canary transcript, plus the moments
   Cosmos says a person looks away or at a phone, plus a "what did I miss about X?" box
   answered by a W&B model from the transcript and those moments.

### Sensory prompt (for Cosmos calls and, later, re-ingest)

> You are helping an autistic person avoid sensory overload. Describe this clip for search.
> List any of these triggers you see, each with a confidence score: crowding around a
> person; someone entering personal space; someone approaching fast; rapid movement;
> commotion; a person standing up suddenly; several people getting up; a chair being moved;
> flicker or a sudden light change; an object likely to make a loud noise (blender, drill,
> vacuum, dog, alarm, megaphone, dishes, door). Say what is likely to get loud in the next
> few seconds. Also note anyone covering their ears, rocking, putting their head down,
> looking away or using a phone. End with `RISK: <0-10>`.

## Audio distress (ported from another project)

Run YAMNet on the clip's audio. Flag distress when any label containing one of these words
scores at least 0.30: scream, shout, yell, groan, grunt, crying, sob, wail, moan, gasp, thud,
thump, bang, slam, gunshot, gunfire, explosion, firecracker, fireworks, glass, shatter,
breaking, fall, whimper, choking, cough, gagging.

## Git rules

- Commit as you go, in small commits with plain messages.
- **No `Co-authored-by` trailers and no AI attribution of any kind** in commit messages.
- Only touch `vm/`. Run `git pull --rebase` before each push, because the laptop agent
  pushes to the same repo.
- Never commit secrets, `/config` contents, videos or model weights.
