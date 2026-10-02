# Prompts to paste into Cursor on the workshop VM

Run these in the Cursor agent on the VAST workshop VM (`cd ~/vast-builders-challenge && agent`).
They use the organizers' skills and your team login automatically.

## 1. Find footage of people crowding an individual

> Search our team's archive for moments where people crowd, surround or close in on one person. Run these searches
> and merge the results, best match first, grouped by camera_id and location: "a group of people crowding around one person",
> "several people surrounding a single person", "a crowd of people packed close together", "people gathering closely in a
> hallway or corridor", "a person standing in a crowded indoor space", "many pedestrians crossing close together",
> "people rushing past someone", "a person close to a moving vehicle", "a forklift approaching a person in an aisle".
> Use min_similarity 0.25. Show the top 15 with their Cosmos caption and a playback link.

Best packs for this: **F (indoor smart spaces, smartspace_cam-1)**, then **E (SF streets)** and **C (warehouse)**.

## 2. Make the captions describe sensory load (re-ingest)

Cosmos only writes down what its prompt asks about. Re-ingest a few Pack F clips first, check, then more.

> Re-ingest 3 chunks of the indoor smart-spaces video (smartspace_cam-1) with this custom prompt, then confirm the
> segments are re-indexed: "Describe this clip for a student with autism who is sensitive to sensory overload. State how
> many people are visible and how close together they are (empty, few, crowded, packed). Note fast or sudden movement:
> running, rushing, people standing up together, vehicles braking or swerving. Note things that are likely loud: vehicles,
> horns, machinery, forklifts, construction, groups talking or shouting. Note flashing, flickering or very bright lights.
> End with one line: SENSORY LOAD: calm, moderate, or high."

Then search again: "SENSORY LOAD: high", "crowded hallway".

## 3. Connect the EqualEd app on your laptop

On the VM, open `/config/<team>.config`. Copy these values into `vast.env` on the laptop
(copy `vast.env.example` first). Never commit or post them.

`GPU_BEARER_TOKEN`, `INGRESS_URL`, `USERNAME`, `PASSWORD`, `WANDB_API_KEY`, `WANDB_TEAM`, `WANDB_PROJECT`

Then in the laptop's EqualEd dashboard, open **Sensory map (VAST)** and press **Find and download clips**,
or run `.venv/bin/python find_footage.py`.
