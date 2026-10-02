"""Finds things that are about to get loud, by name, before they make a sound.

Uses YOLOE, a YOLO model you give a plain-word list of objects to look for.
The standard YOLO 80-object list has no blender, drill or fire alarm.
"""
import numpy as np

MODEL = "yoloe-26s-seg.pt"
# object -> how likely it is to make a sudden loud noise (0..1)
LOUD_THINGS = {
    "blender": 0.95, "power drill": 0.95, "vacuum cleaner": 0.9, "hair dryer": 0.85,
    "megaphone": 0.95, "air horn": 0.95, "drum": 0.8, "trumpet": 0.8, "whistle": 0.6,
    "fire alarm": 0.7, "balloon": 0.5, "dog": 0.6, "loudspeaker": 0.5,
}
OTHER_THINGS = ["chair", "cell phone"]
CONF = {"chair": 0.3, "cell phone": 0.3, "megaphone": 0.6, "air horn": 0.6, "whistle": 0.55}
DEFAULT_CONF = 0.45
MIN_LOUD_AREA = 0.012   # loud things smaller than 1.2% of the picture are far away; skip them


class LoudObjects:
    def __init__(self, device):
        from ultralytics import YOLOE
        self.device = device
        self.names = list(LOUD_THINGS) + OTHER_THINGS
        self.m = YOLOE(MODEL)
        self.m.set_classes(self.names, self.m.get_text_pe(self.names))

    def detect(self, frame):
        H, W = frame.shape[:2]
        r = self.m.predict(frame, device=self.device, conf=0.2, verbose=False)[0]
        out = []
        if r.boxes is None:
            return out
        for c, p, b in zip(r.boxes.cls.cpu().numpy(), r.boxes.conf.cpu().numpy(), r.boxes.xyxy.cpu().numpy()):
            name = self.names[int(c)]
            if p < CONF.get(name, DEFAULT_CONF):
                continue
            if name in LOUD_THINGS and (b[2] - b[0]) * (b[3] - b[1]) < MIN_LOUD_AREA * W * H:
                continue
            out.append((name, float(p), b))
        return out


def closeness(box, H):
    """1.0 for something big and close, down to 0.4 for something small and far."""
    return float(np.clip((box[3] - box[1]) / (0.25 * H), 0.4, 1.0))


def held_by_someone(box, people, kp_ok=0.4):
    """True if any person's wrist is inside the (slightly enlarged) object box."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    x1, y1, x2, y2 = x1 - 0.2 * w, y1 - 0.2 * h, x2 + 0.2 * w, y2 + 0.2 * h
    for _, _, k, c, _ in people:
        for wr in (9, 10):
            if c[wr] > kp_ok and x1 <= k[wr][0] <= x2 and y1 <= k[wr][1] <= y2:
                return True
    return False
