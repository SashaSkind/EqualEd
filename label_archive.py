"""Label every clip in the team's VAST archive for sensory load (autism).

Uses what the pipeline already wrote for each 5-second segment: the NVIDIA Cosmos3-Reason
description and the YOLO11 object counts. Scores five areas, 0 to 10:
  crowding  (people in frame, "crowd", "busy", "group of people")
  noise     (trucks, buses, motorcycles, trains; "siren", "horn", "construction", "forklift")
  light     ("flashing", "glare", "headlights", "bright light")
  motion    ("fast", "rushing", "braking", "swerving", "cyclist")
  closeness ("close to", "crossing in front", "cutting off", "narrow")
and combines them into a sensory load 0-10: calm < 2.5 <= moderate < 5 <= high.

Run on the workshop VM (credentials already in the environment) or on a laptop with vast.env:
  python3 label_archive.py            -> archive_sensory_labels_full.json
"""
import json, re, time
from concurrent.futures import ThreadPoolExecutor
from vast import Vast

RX = {
    "crowd": r"crowd|busy|bustling|many (people|pedestrians)|group of (people|pedestrians)|several (people|pedestrians)|dense|packed|throng|queue",
    "noise": r"siren|horn|honk|construction|jackhammer|loud|engine|motorcycle|bus\b|buses|truck|tram|streetcar|train|forklift|machinery|ambulance|fire truck|police|emergency|drill|alarm",
    "light": r"flash|flicker|glare|bright(ly)? lit|bright light|headlight|sun glare|emergency light|neon|strobe|blinding|reflect",
    "motion": r"fast|speed|rush|running|quickly|sudden|abrupt|brak|swerv|accelerat|cyclist|scooter|merg|lane change|zoom|hurr",
    "close": r"close to|very near|right next to|in front of the camera|cross(es|ing)? in front|cut(s|ting)? off|tight|narrow|pass(es|ing)? closely|tailgat|near-miss|near miss|inches",
}


def label(seg):
    cap = seg.get("reasoning_content") or ""
    oc = seg.get("object_counts") or {}
    if isinstance(oc, str):
        try:
            oc = json.loads(oc)
        except ValueError:
            oc = {}
    n = lambda k: float(oc.get(k, 0) or 0)
    people, heavy = n("person"), n("truck") + n("bus") + n("train") + n("motorcycle")
    vehicles = n("car") + heavy + n("bicycle")
    hits = {k: len(re.findall(rx, cap, flags=re.I)) for k, rx in RX.items()}
    sc = {"crowding": min(10, people * 0.8 + hits["crowd"] * 1.5),
          "noise": min(10, heavy * 1.2 + vehicles * 0.25 + hits["noise"] * 1.2),
          "light": min(10, hits["light"] * 2.5),
          "motion": min(10, hits["motion"] * 1.8),
          "closeness": min(10, hits["close"] * 2.5)}
    load = min(10, 0.3 * sc["crowding"] + 0.25 * sc["noise"] + 0.15 * sc["light"] + 0.15 * sc["motion"]
               + 0.15 * sc["closeness"] + 0.15 * max(sc.values()))
    return {"segment": (seg.get("source") or "").split("/")[-1], "source": seg.get("source"),
            "camera_id": seg.get("camera_id"), "location": seg.get("location"),
            "start_sec": seg.get("segment_start_sec"), "end_sec": seg.get("segment_end_sec"),
            "load": round(load, 1), "level": "high" if load >= 5 else "moderate" if load >= 2.5 else "calm",
            "triggers": "+".join(k for k, v in sorted(sc.items(), key=lambda kv: -kv[1]) if v >= 3),
            "scores": {k: round(v, 1) for k, v in sc.items()}, "caption": cap[:300]}


def main():
    v = Vast()
    if not v.archive_on:
        raise SystemExit("Needs INGRESS_URL, USERNAME, PASSWORD (environment or vast.env).")
    vids, off = [], 0
    while True:
        b = v._api("GET", f"/api/v1/videos/explore?scope=all&limit=100&offset={off}")
        items = b.get("items") or b.get("videos") or b.get("results") or b.get("chunks") or []
        vids += items; off += 100
        if not items or len(vids) >= (b.get("total") or 0):
            break
    ovs = sorted({x["original_video"] for x in vids})
    from urllib.parse import quote
    with ThreadPoolExecutor(6) as ex:
        segs = [s for r in ex.map(lambda ov: v._api("GET", "/api/v1/tools/segments?original_video=" + quote(ov, safe="")), ovs)
                for s in r.get("segments", [])]
    rows = [label(s) for s in segs]
    json.dump({"labeled_at": time.strftime("%Y-%m-%d %H:%M"), "clips": rows}, open("archive_sensory_labels_full.json", "w"), indent=1)
    lv = {k: sum(r["level"] == k for r in rows) for k in ("high", "moderate", "calm")}
    print(f"{len(rows)} clips from {len(ovs)} videos: {lv}")


if __name__ == "__main__":
    main()
