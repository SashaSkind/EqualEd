# VM notes (Phase 1 findings)

Written by the VM agent on 2026-10-02 from the VAST Builders Challenge VM (team-17).
Everything below was measured on this VM, not copied from docs. No secret values.
Latencies are single calls from the VM, so treat them as rough.

## TL;DR for the laptop agent

- All four GPU models are up. The Cosmos model id is **`nvidia/cosmos3-nano-reasoner`**,
  not `nvidia/cosmos3-reason` (that id returns 404 `The model ... does not exist`).
  `vast.py` falls back to the wrong id if `/v1/models` fails.
- **Canary: send `language=en-US` and no `model` field.** `model=nvidia/canary-1b` (what
  `vast.py` sends) returns `400 bad model`, and `language=en` returns
  `Model not found for language en`. Every model id tried was rejected.
- **W&B Inference blocks the `Python-urllib` User-Agent** (Cloudflare 403, `error code: 1010`).
  `python-requests`, the OpenAI SDK and curl are fine. If you use `urllib`, set a User-Agent.
- Archive segments are **5 s** (not 2 s), parent chunks are 30 s. Only the **SF streets** clips
  have audio, and almost none of it is speech.
- VSS search scores for our triggers are low (0.15 to 0.34). The current captions do not talk
  about sensory load, which is why a re-ingest with the sensory prompt is worth doing.

## 1. Health

| Check | Result |
|-------|--------|
| Cosmos3-Reason `:8001` | `/v1/models`, `/v1/health/ready`, `/v1/health/live` all 200 |
| Cosmos Embed1 `:8003` | all three 200, model `nvidia/cosmos-embed1`, 256 dims (backend config) |
| YOLO11 `:8002` | `/healthz` → `{"ok":true,"model":"/models/yolo11s.pt","device":"0","cuda_available":true,"model_loaded":true,"inputs":["url","video_base64"]}`; GET `/v1/infer` 405 (expected) |
| Canary-1B `:8004` | `/v1/health/ready` ready, `/v1/health/live` live; `/v1/metadata` → `canary-1b:ofl-rmir-26.01.1`, Riva HTTP API release 1.5.1 |
| VSS backend | login OK (`/api/v1/auth/me` → `team-17`), `/api/v1/config` OK, dashboard `pipeline_alignment.healthy: true` |

GPU host is `166.19.38.112` (ports 8001 to 8004), as in the skills' `gpu/README.md`. Every GPU call needs
`Authorization: Bearer $GPU_BEARER_TOKEN`.

`$INGRESS_URL/health` returns the VSS frontend HTML, not a JSON health doc. Use an authenticated
API call (e.g. `/api/v1/auth/me`) as the backend health check instead.

`kubectl` is **not installed** on this VM, and the kubeconfig is at the team-prefixed path
`/config/team-17-k8s.yaml` (there is no `/config/kubeconfig`). That needs sorting before the
Phase 2 deploy.

## 2. Variable names

In the environment (names only):
`GPU_BEARER_TOKEN INGRESS_URL PASSWORD USERNAME VDB_COLLECTION VDB_PROMPTS_COLLECTION VDB_SCHEMA WANDB_API_KEY WANDB_PROJECT WANDB_TEAM`

In `/config/team-17.config`:
`ACCESS_KEY GPU_BEARER_TOKEN INGRESS_URL PASSWORD PIPELINE S3_CHUNKS_BUCKET S3_ENDPOINT S3_SEGMENTS_BUCKET SECRET_KEY USERNAME VASTDB_BUCKET VDB_COLLECTION VDB_PROMPTS_COLLECTION VDB_SCHEMA`

**Not set anywhere:** `COSMOS3_REASON_URL`, `YOLO_URL`, `COSMOS_EMBED1_URL`, `CANARY_1B_URL`,
`COSMOS3_REASON_MODEL`, `CANARY_1B_MODEL`, `VDB_ENDPOINT`. Default the URLs to
`http://166.19.38.112:800{1,2,3,4}`.

Non-secret values: `WANDB_TEAM=vastdata`, `WANDB_PROJECT=team-17`. Ingress host is
`video-lab-team-17.cosmos.vastdata.com`.

Backend `/api/v1/config` (non-secret parts): S3 buckets `team-17-vss-chunks` and
`team-17-vss-chunks-segments`, VastDB `team-17-vss-db` / `vss-schema` / `vss-collection`,
synthesis model `nvidia/cosmos3-nano-reasoner` at temperature 0.2, `max_upload_size_mb=100`,
allowed extensions `.mp4 .mov .webm .avi .mkv`.

## 3. Archive inventory

`GET /api/v1/dashboard/stats?scope=all`: **414 parent videos, 2352 segments**, all indexed and all
public. Reasoning, perception and object classes are present on 100 % of segments. No re-ingest has
been done yet, and there are no duplicates.

- Parent chunks are **30 s** (the SDG warehouse ones are 10 s). Each parent chunk is cut into
  **5 s segments**, 6 per 30 s chunk.
- Segments are **H.264**, 1080p (neighborhood is 2048x1154), at 30, 29.97 or 19.9 fps, and about
  3 to 6 MB per 5 s. The **parent chunks are HEVC**, so play segments in the browser, not parents.
- Fetching a 5 s segment through `/api/v1/videos/stream?source=...&token=` takes about 0.1 s.

| camera_id | location | capture_type | segments | file prefix in `filename` | audio | people (median / max per segment) |
|-----------|----------|--------------|---------:|---------------------------|-------|-----------------------------------|
| `pie_cam-3` | toronto | streets | 1080 | `set01_video` … `set06_video` (dashcam) | no | 3 / 16 |
| `neighborhood_cam-1` | neighborhood | streets | 307 | `neighborhood_20260901`, `_20260902` (night) | no | 0 / 2 |
| `sf_streets_cam-1..4` | san_francisco | streets | 148 + 180 + 37 + 180 | `sf1` … `sf4` | **yes**, AAC 44.1 kHz stereo | 8 to 11 / 18 |
| `smartspace_cam-1` | indoor | crowds | 180 | `2025_test_Warehouse_017_Camera`, `_01`, `_02` | no | **12 / 17** |
| `i24_cam-1` | nashville | traffic | 180 | `scene1_p1c1..3` (highway) | no | 0 / 2 |
| `sdg_warehouse_cam-2` | warehouse3 | warehouse | 60 | `<hash>_run_N_seed_N.{ceiling,eye}_NN.rgb` (synthetic, forklift and person) | no | 1 / 3 |

The "people" column is the indexed `object_counts.person`. In the index it looks like a peak count
of people per frame, not a sum. See the YOLO note below, because raw `/v1/infer` returns a sum.

Audio was checked with ffprobe on 2 segments per camera family. Canary on 10 random SF parent
chunks found speech in only one (`20261001_100108_sf2_chunk_0023.mp4`: "that's what I'd say").
The rest is street noise. **No archive clip is usable for the ADHD transcript feature.**

Caption quality varies. smartspace, SF and SDG captions are detailed. Some neighborhood captions
are junk ("A donut is visible in the frame.", "A car is driving on the road."), and they pollute
search results.

Filterable fields (`/api/v1/metadata/schema`): `camera_id`, `capture_type`, `location`,
`object_classes`. Search results carry `camera_id`, `capture_type`, `location`, `object_counts`,
`segment_start_sec`, `segment_end_sec`, `original_video`, `source`, `reasoning_content`,
`detection_sidecar_uri` and more.

Explore (`GET /api/v1/videos/explore?scope=all&limit=100&offset=N`) returns `chunks[]` with a
`timeline[]` of segments. Each segment has `source`, `segment_start_sec`, `segment_end_sec`,
`reasoning_content`, `object_classes` (CSV string) and `object_counts` (a JSON *string*).

## 4. Cosmos3-Reason (`nvidia/cosmos3-nano-reasoner`)

OpenAI-compatible `POST /v1/chat/completions`. Tested with the sensory prompt from
`START_HERE.md` (665 chars), `temperature 0.2`, `max_tokens 700`. Answers came back in `content`.
`reasoning_content` was empty: it does not think out loud here.

| Input | Prompt tokens | Latency | Answer |
|-------|--------------:|--------:|--------|
| 2 s clip, 960 px, H.264, about 69 KB, as `video_url` data URI | 2231 | **1.90 s** | "Several people are walking around in a large open space. There is no crowding … RISK: 0" |
| 1 JPEG frame, 960 px, about 40 KB, as `image_url` data URI | 671 | **1.43 s** | "…warehouse-like space with several people and robots … RISK: 0" (**image_url works**) |
| full 5 s segment, 1080p, about 3.3 MB (smartspace) | 12199 | 3.24 s | "…multiple people and robots moving around … relatively calm … RISK: 2" |
| full 5 s segment, 1080p (sf2 busy crosswalk) | 12199 | 3.54 s | "…busy urban intersection with moderate pedestrian and vehicle traffic … RISK: 2" |

Request shape:

```json
{"model": "nvidia/cosmos3-nano-reasoner", "temperature": 0.2, "max_tokens": 700,
 "messages": [{"role": "user", "content": [
   {"type": "text", "text": "<sensory prompt>"},
   {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,..."}}]}]}
```

Observations:

- It always ended with `RISK: <n>` as asked, so parse it with the regex `RISK:\s*(\d+)`.
- It did **not** give per-trigger confidence scores, even though the prompt asks for them. It writes
  one prose paragraph. If we need structured output, ask for JSON explicitly.
- Downscaling to 960 px and 2 s cut the prompt tokens by about 5x and latency by about 40 %.

## 5. YOLO11 (`yolo11s`, COCO)

`POST /v1/infer` with `{"video_base64": "...", "filename": "clip.mp4", "include_frames": bool}`.
It also accepts `{"url": ...}`, and there is a `/v1/infer-base64` route.

| Input | Latency | Result |
|-------|--------:|--------|
| 2 s clip (60 frames), `include_frames:false` | **0.84 s** | `object_counts {"person": 724, "truck": 14}`, `max_detection_conf 0.9033`, `frame_count 60`, `detection_count 738` |
| 5 s segment (150 frames), `include_frames:true` | 2.55 s | 150 frames, each `{"frame_index", "shape":[1080,1920], "detections":[{"label","confidence","bbox":[x1,y1,x2,y2]}]}` |

Response top level: `ok`, `perception_ok`, `perception_json{source:"yolo11_coco", frames, object_classes,
object_counts, max_detection_conf, frame_count, detection_count}`, plus copies of `object_classes`,
`object_counts`, `max_detection_conf` and `frames`.

**Raw `object_counts` is summed over every frame** (724 person detections over 60 frames is about
12 people per frame). Divide by `frame_count`, or take the per-frame max from `frames`. It runs on
every frame, with no sampling.

## 6. Canary-1B (Riva HTTP ASR)

`POST /v1/audio/transcriptions`, multipart: `file=@clip.wav` and `language=en-US`. Response:
`{"text": "...", "language_code": "en-US"}`.

- 9.7 s English speech, 16 kHz mono WAV: **0.42 s**, transcript perfect.
- 30 s SF street audio: 0.66 s, `{"text": ""}` (no speech).
- `response_format` accepts only `json` or `text` (no `verbose_json`, so no word timestamps over HTTP).
- **Send WAV.** MP3 input fails with `Audio decoder exception: Request config encoding not specified`.
  Convert first with `ffmpeg -i in -vn -ac 1 -ar 16000 out.wav`.
- Without `language` (and with no valid model) the server returns `need model or language`.

## 7. W&B Inference

`https://api.inference.wandb.ai/v1`, `Authorization: Bearer $WANDB_API_KEY`,
header `OpenAI-Project: vastdata/team-17` (or `project=` in the OpenAI SDK). `/v1/models` lists
29 models and returns no modality info, so I tested each one (`max_tokens` 60, temperature 0).

Accept images (a 480 px JPEG sent as `image_url`):

- `google/gemma-4-26B-A4B-it`: 0.69 s, direct answer ("There are 10 people in this image.")
- `google/gemma-4-31B-it`: 0.51 s, direct answer
- These also accept images but are reasoning models that spent the whole budget thinking:
  `Qwen/Qwen3.5-35B-A3B`, `Qwen/Qwen3.6-35B-A3B`, `Qwen/Qwen3.6-27B`, `Qwen/Qwen3.8-27B`,
  `MiniMaxAI/MiniMax-M3`, `moonshotai/Kimi-K2.6`, `moonshotai/Kimi-K2.7-Code`,
  `zai-org/GLM-5.3-Flash`, `deepseek-ai/DeepSeek-V4.1-Flash`. `openai/gpt-oss-20b` accepted the
  request too, but it is a text model, so the image is probably ignored.

Fastest text (time for a 2-token reply): `meta-llama/Llama-3.1-70B-Instruct` 0.22 s,
`meta-llama/Llama-3.1-8B-Instruct` 0.23 s, `OpenPipe/Qwen3-14B-Instruct` 0.23 s,
`deepseek-ai/DeepSeek-V3.1` 0.40 s, `Qwen/Qwen3-30B-A3B-Instruct-2507` 0.54 s,
`meta-llama/Llama-3.3-70B-Instruct` 0.55 s. All of these answer directly, with no reasoning
preamble. `zai-org/GLM-5.2` was slow (7.8 s).

Suggested picks: `google/gemma-4-31B-it` for anything with images, and
`meta-llama/Llama-3.3-70B-Instruct` for "what did I miss about X?" (fast, direct, strong
enough). Use `meta-llama/Llama-3.1-8B-Instruct` where speed matters most.

## 8. Uploading our own clip (`ingest/upload-video`), not done yet

`POST /api/v1/videos/upload`, multipart, JWT. One file per request, at most 100 MB, extensions
`.mp4 .mov .webm .avi .mkv`.
Fields: `file` (required), `is_public`, `tags` (CSV), `allowed_users`, `scenario` (preset key) **or**
`custom_prompt` (at most 800 chars, overrides the scenario), `camera_id`, `capture_type`, `location`.
The response contains `object_key`. Indexing is asynchronous; watch
`/api/v1/videos/explore?scope=mine`.

`GET /api/v1/metadata/ingest-config` (no auth) lists the presets:
- capture types: `traffic streets crowds malls general sports robotics warehouse retail`
- scenarios: `surveillance traffic live_driving nhl sports retail warehouse nyc_control nyc_safety_surveillance egocentric general`

Re-ingest is `POST /api/v1/dashboard/reingest` with `{"original_video": "<s3 uri>", "chunk_count": 1,
"custom_prompt": "..."}`. Poll `GET /api/v1/dashboard/reingest/<job_id>`. It works on whole chunks
only and replaces captions in place, so the old caption is lost.

## 9. Search results for trigger queries

`POST /api/v1/search` with `top_k 10`, `min_similarity 0.25`. **`llm_top_n` must be at least 1**:
0 returns 422, even though the reingest-chunk skill's example sends 0. Each call took 1.5 to 5.5 s
including the Cosmos synthesis.

| Query | Hits | Best score | Verdict |
|-------|-----:|-----------:|---------|
| person standing up suddenly | 10 | 0.336 | weak: SDG forklift clips of a person standing, then walking or running off |
| crowd of people | 10 | 0.205 | **bad**: top hit is a neighborhood caption "A car is driving on the road."; the smartspace hits are shelving descriptions |
| person covering ears | 2 | 0.166 | **bad**: "A donut is visible in the frame." |
| loud machine | 0 | – | **none** |
| person looking at phone | 2 | 0.181 | **good**: two real SF hits of a pedestrian looking at a phone (`sf1_chunk_0011` seg 2, `sf1_chunk_0018` seg 2) |

The visual content is there: smartspace has 12 to 17 people per segment, SF has busy crosswalks
with up to 18 people, and SDG has forklifts approaching people. The captions just never mention
crowding, approach or noise, so the gaps are a caption problem, which re-ingest fixes. Covering
ears, rocking and classroom scenes are not in the archive at all, so only uploading our own
footage can fill those.

## Proposed re-ingest plan (waiting for a human "go")

Use the sensory prompt from `START_HERE.md` verbatim as `custom_prompt` (665 chars, under the 800
limit) and keep the metadata. It starts with "Describe this clip for search", so captions stay
useful for general search too.

1. **Pilot, 3 chunks (18 segments)**, smartspace `Warehouse_017_Camera_02`, the most crowded indoor
   footage: `…080845…Camera_02_chunk_0006`, `…080755…Camera_02_chunk_0004`,
   `…080705…Camera_02_chunk_0002`. Afterwards, re-run the five searches plus
   "RISK: 7", "crowding around a person" and "people approaching fast", and compare.
2. If the pilot improves search: **the rest of smartspace** (27 chunks), **the busiest SF chunks**
   (`sf2_chunk_0019`, `sf2_chunk_0007`, plus about 6 more ranked by person count; these have audio
   for YAMNet), and **the SDG forklift clips** (30 clips of 10 s, "approaching fast" or "loud machine").
3. Skip pie_cam-3, neighborhood and i24 (dashcam, night streets and highway with almost no people).
4. Separately, **upload** 1 or 2 short clips with speech and classroom-like activity, to cover
   attention rewind (Canary) and covering ears. The archive has neither.

## Done: Task 1, re-ingest pilot (2026-10-02)

Re-ingested the 3 smartspace `Warehouse_017_Camera_02` chunks (`chunk_0002`, `_0004`, `_0006`, 18 segments)
with the START_HERE sensory prompt as `custom_prompt`, metadata kept. Started 21:49:09 UTC. All three had
new captions within about 2 minutes. The backend returned 503 for about 10 s at 21:50:51, and after that
`GET /api/v1/dashboard/reingest/<job_id>` answered `Re-ingest job not found (backend may have restarted)`
for all three jobs, so **job status lives in memory and is lost on a backend restart**; check Explore
captions instead. Explore still shows 6 segments per chunk (no duplicates).

The new captions follow the prompt: they list what is moving, say "No one is covering their ears, rocking,
or using a phone", and end in `RISK: 2` for all three chunks (Cosmos calls this footage calm).

Before/after (`top_k 10`, `min_similarity 0.15`, `llm_top_n 1`; best score and top hit):

| Query | Before | Before top hit | After | After top hit |
|-------|-------:|----------------|------:|---------------|
| crowd of people | 0.256 | `Camera_02_chunk_0008` (old shelving caption) | **0.293** | `Camera_02_chunk_0002` (pilot): "large warehouse … Several people and robots …" |
| crowding around a person | 0.241 | `sf1_chunk_0007` | 0.241 | same |
| people approaching fast | 0.283 | `Warehouse_017_Camera_chunk_0006` | **0.293** | `Camera_02_chunk_0002` (pilot) |
| person standing up suddenly | 0.336 | SDG `run_3 … eye_02` | 0.336 | same |
| loud machine | 0.158 | `set01_video_chunk_0005` (tram) | 0.158 | same |
| RISK: 7 | 0.222 | neighborhood "A donut is visible in the frame." | 0.222 | same |

Pilot chunks in the top 10 for "crowd of people": 3 before, 4 after. Extra checks after: "no one covering
their ears" puts 2 pilot segments in the top 5; "RISK: 2" and "calm space with no sensory triggers" put none.

**Verdict: a small improvement, not a clear one**, so the 3 SF chunks were **not** re-ingested. The re-captioned
clips now rank first for crowd and approach queries, but the gains are 0.01 to 0.04 and the other four
queries are unchanged, because Cosmos honestly rated this footage calm and there is no loud machine in it.
Re-ingesting the SF crosswalk chunks (where the busy moments are) is the next thing to try if a human agrees.
