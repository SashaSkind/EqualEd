# EqualEd VM: next steps for the coding agent

**Agent: read this file, `vm/START_HERE.md` (rules) and `vm/VM_NOTES.md` (your Phase 1 findings), then do the
tasks below in order.** The human has approved all of them, including the re-ingest pilot in Task 1.
Same rules as START_HERE: only touch `vm/` (except reading files at the repo root), never print or commit
secrets, videos or model weights, small commits, `git pull --rebase` before every push.
After each task, add a short "Done" note with real numbers to `vm/VM_NOTES.md`, commit and push.

## Why these tasks

The hackathon judges a **video agent built on their stack**. The current VM app (`vm/app.py`) runs its own
YOLO on one clip. It does not yet use NVIDIA Cosmos3-Reason, the VAST archive search, Weights & Biases,
or Canary, and it is not deployed. These tasks fix that and bring the story back to **sensory overload for an
autistic student**: the warehouse clip with people and robots closing in on a person is the same
"busy around me" idea as the laptop app.

## Task 1: re-ingest pilot (approved, 15 min)

Run the pilot exactly as written in `vm/VM_NOTES.md` "Proposed re-ingest plan", step 1:
3 smartspace `Warehouse_017_Camera_02` chunks (`…080845…chunk_0006`, `…080755…chunk_0004`,
`…080705…chunk_0002`), `custom_prompt` = the sensory prompt from `vm/START_HERE.md`, metadata kept.
Wait until re-indexing finishes, then re-run these searches and write a **before/after table**
(best score + top caption) into VM_NOTES.md:
"crowd of people", "crowding around a person", "people approaching fast", "person standing up suddenly",
"loud machine", "RISK: 7".
If the pilot clearly improves search, also re-ingest the 3 busiest SF chunks (`sf2_chunk_0019`,
`sf2_chunk_0007`, plus the next one by person count). Stop there; do not re-ingest more without a human.

## Task 2: Cosmos sensory-risk timeline in the VM dashboard (30 min)

In `vm/app.py`, while the clip plays: every 2 s send the **last 2 s of video** (960 px wide, H.264,
as a `video_url` data URI, see VM_NOTES section 4) to Cosmos3-Reason, model id
**`nvidia/cosmos3-nano-reasoner`**, temperature 0.2, with the sensory prompt. Parse `RISK:\s*(\d+)`.
Run the call in a background thread so the video never stalls (it takes about 2 s).
Dashboard: add a **sensory-risk timeline** (0 to 10 over time) next to the existing YOLO events, show
Cosmos's one-line reason for the latest window, and **highlight moments where the Cosmos risk rose
before a YOLO invasion / sudden-move event**, with the lead time in seconds. That lead time is the
headline demo number ("Cosmos saw it coming N seconds early").

## Task 3: "Search triggers" page: VAST archive + W&B (30 min)

Add a page to the VM app:
1. A search box backed by VSS `POST /api/v1/search` (`llm_top_n` must be at least 1, `min_similarity` 0.2),
   with clip playback via `/api/v1/videos/stream?source=...&token=`.
2. Preset buttons that run: "crowd of people crossing the street", "people approaching fast",
   "person looking down at their phone", "an ambulance with flashing lights", "a forklift near people",
   "a streetcar or tram passing", "a cyclist or skateboarder moving fast".
3. A **sensory map**: read `archive_sensory_labels.json` from the **repo root** (the laptop labeled all 2,352
   archive clips for sensory load from the Cosmos captions + YOLO counts) and show places ranked from most
   overwhelming to calmest, with their top clips.
4. A "Summarize" button that sends the top hits' captions to W&B Inference,
   `meta-llama/Llama-3.3-70B-Instruct`, header `OpenAI-Project: vastdata/team-17`, and shows a short plain-language
   summary: which places/times are most overwhelming and which are calmest. Use `python-requests` or the OpenAI
   SDK (W&B blocks the urllib User-Agent). Wrap LLM calls with Weave (`weave.init("vastdata/team-17")`).

Good archive moments found from the laptop (use them as demo examples):
- Real ambulance: `sf_streets_cam-1`, a segment starting at 5 s (search "an ambulance with flashing lights", score 0.44).
- Crowd surging across a crosswalk: `sf_streets_cam-4` / `sf_streets_cam-2` (score 0.54).
- Pedestrians looking down at phones (ADHD attention example): 58 SF / Toronto segments, e.g. `sf2` crosswalk clips.
- Skateboards / scooters weaving: 48 segments, mostly `sf_streets_cam-1`.
- Forklift near people: `sdg_warehouse_cam-2` (score 0.47).
- Not in the archive at all: covering ears, rocking, fidgeting, people running, classrooms.

## Task 4: deploy (15 min max)

`kubectl` is missing. Install the official release binary into `~/bin` (no sudo), use
`KUBECONFIG=/config/team-17-k8s.yaml`, then follow `deployment/deploy-app-no-registry` to
`http://video-lab-team-17.cosmos.vastdata.com/app`. Remember the START_HERE limits: `vm/` flat, under 1 MiB,
secrets in the Kubernetes Secret. **If it is not working after 15 minutes, stop**, run the dashboard on the VM
(`.venv/bin/python vm/app.py`) and note in VM_NOTES.md that the demo runs from the VM browser.

## Task 5: one-line story check

Make the dashboard title and empty states say what this is for: "EqualEd: spotting sensory overload before it
happens". Robots and AGVs are just "things closing in on a person"; personal-space invasion = "too close";
sudden movement = "rushing". Keep the existing robot detection, only change the wording a person sees.

## Report back

When done, push and write at the top of VM_NOTES.md: what works, the Cosmos lead time you measured, the
before/after search table, the deploy URL (or "runs on VM only"), and anything blocked.

## Human step (not for the agent)

Live Cosmos + Canary on the **laptop** camera need `GPU_BEARER_TOKEN`. On the VM run
`grep GPU_BEARER_TOKEN /config/*.config` and paste the value after `=` into `vast.env` in the EqualEd folder
on the laptop. Do not paste it into chat, GitHub or this repo.
