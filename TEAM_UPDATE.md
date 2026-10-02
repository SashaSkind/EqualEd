# EqualEd: what we built today (team update)

Read this first. Every change below is in this repo on `main`.
The laptop app is the root of the repo. Sasha's VM app lives in `vm/` (see `vm/START_HERE.md`).

## The idea in one line

One camera and one set of models that help neurodivergent students in class: it shields an autistic
student from sensory overload, rewinds what a student with ADHD missed, and reads aloud for dyslexia.

## What works now (laptop app, `EqualEd.app`)

| Feature | What you see |
|---|---|
| **Lock onto one student** | Raise both hands above your head for 1 second. Green "LOCKED ON" banner; only that student is tracked. The lock is anchored to the student's seat, so people walking in front don't steal it. `u` unlocks. |
| **Personal bubble + "busy around me" meter** | An oval around the student, a 0-100 meter of people close, movement near them, someone approaching, people standing up / chairs. No noise in it. |
| **11 sensory triggers** | Crowding, someone in personal space, someone approaching fast, rapid movement, commotion, someone standing up, several people getting up, chair moved, flicker/light change, sudden loud noise, **someone staying close (8 s+)**. The people causing a trigger get labeled on the video ("TOO CLOSE", "FAST", "STAYING CLOSE 9s") with a red line to the student. |
| **Teacher notifications** | Every trigger sends the teacher a pop-up (max once per 30 s per trigger). Separate urgent alerts for: very busy around the student (meter at 55+ for 3 of 5 s), someone staying close 8 s+, and overload (covering ears, rocking). The professor page chimes, flashes red, and has an "I'm on my way" button the student's screen shows. |
| **Student reactions** | Covering ears (both hands at once, or one hand held 2.5 s), rocking, head down. Only judged for the student near the camera. |
| **Calming sound** | Plays in the student's AirPods only (speakers can be allowed in Settings for stage demos). |
| **Loud things predicted before they're loud** | YOLOE finds a blender, drill, vacuum, hair dryer, dog... by name; the risk meter rises and the calming sound starts early. The microphone (YAMNet) confirms and scores "predicted N s early". |
| **ADHD lecture rewind** | Marks moments the student looked away / was on the phone; live transcript (Whisper on the Mac, or NVIDIA Canary-1B with the GPU key); "What did I miss?" answered by W&B, Claude, or offline search. |
| **Dyslexia reading** | Reading tab: lean in toward the camera and the paragraph is read aloud. |
| **Sensory map of the VAST archive** | All **2,352 clips** (414 videos) of team-17's archive labeled for sensory load from the NVIDIA Cosmos3-Reason captions + YOLO11 counts: 771 high, 1,015 moderate, 566 calm. San Francisco street cams are the most overwhelming (sf_streets_cam-2: 76% of clips high load); the neighborhood cam is the calmest (97% calm). Saved in `archive_sensory_labels.json`, shown in the dashboard's Sensory map tab. Re-run with `label_archive.py`. |

## Models in use

| Job | Model | Where it runs |
|---|---|---|
| People, joints, face points, tracking | YOLO11n-pose + ByteTrack | Laptop |
| Loud objects, chairs, phones (by name) | YOLOE-26s | Laptop |
| Sounds | YAMNet | Laptop |
| Lecture transcript | Whisper base.en, or NVIDIA Canary-1B | Laptop / CoreWeave GPU |
| Live scene reasoning, overload explanation | NVIDIA Cosmos3-Reason | CoreWeave GPU (needs `GPU_BEARER_TOKEN`) |
| Archive captions + search | Cosmos3-Reason, Cosmos Embed1, YOLO11 via VAST DataEngine | VAST / CoreWeave |
| "What did I miss?" | W&B Inference, then Claude, then offline | Cloud / laptop |

## Tested

`stress_test.py` builds classroom scenes from real photos of people and runs them through the real app.
**7/7 pass**: crowding + someone staying close, someone rushing at the student, commotion (busy alert),
flicker, loud noise, overload, lock survives someone walking in front. Frames land in `stress_out/`.
Also checked live on the laptop: covering ears is detected.

## Not done / needs a person

- **Live Cosmos + Canary on the laptop camera** need `GPU_BEARER_TOKEN` from the VM's `/config/<team>.config`
  pasted into `vast.env` (git-ignored). Run on the VM: `grep GPU_BEARER_TOKEN /config/*.config`.
- The loud-object warning has not seen a real blender/drill/hair dryer yet.
- Thresholds (busy 55, staying close 8 s) are first guesses; rehearse with two people crowding the student.
- Three of the 40 saved archive clips have their trigger tag marked "unavailable".

## Run it

```bash
./setup.sh                                   # once
BUNDLE_ID=org.equaled.demo ./make_app.sh --install
open -a EqualEd                              # camera window + dashboard open
.venv/bin/python stress_test.py              # stress test
```

Demo flow (60-90 s): lock on with both hands up -> two teammates walk up and stay -> busy meter climbs,
"staying close" and "busy around" alerts pop up on the professor's phone -> cover your ears -> overload
alert + calming sound -> professor taps "I'm on my way" -> show the Sensory map of the VAST archive.

## Files

| File | What it is |
|---|---|
| `sensory_demo.py` | The app: tracking, lock, bubble, triggers, alerts, drawing |
| `server.py`, `professor.py` | Student dashboard and professor alert page (same Wi-Fi, secret links) |
| `vast.py` | VAST + NVIDIA (Cosmos3-Reason, Canary-1B) + W&B connector |
| `label_archive.py`, `archive_sensory_labels.json` | Archive sensory labeling + saved results |
| `find_footage.py` | Search and download crowding clips from the archive |
| `audio.py`, `loudobjects.py`, `adhd.py`, `calming.py` | Microphone, loud-object finder, ADHD rewind, sounds |
| `stress_test.py` | Scripted scenes, checks every trigger reaches the teacher |
| `VM_CURSOR_PROMPTS.md` | Prompts to paste into Cursor on the VM |
