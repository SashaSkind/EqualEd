"""Live YOLOv9 object detection on the webcam.

Run:  .venv/bin/python webcam_yolov9.py
Keys: q = quit
"""
import sys, time
import cv2
from ultralytics import YOLO


def request_camera_access(timeout=120):
    """Ask macOS for camera permission and wait for the user's answer."""
    try:
        import AVFoundation, threading
        status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(AVFoundation.AVMediaTypeVideo)
        if status == 3:  # authorized
            return True
        done = threading.Event(); answer = []
        def cb(granted):
            answer.append(bool(granted)); done.set()
        AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVFoundation.AVMediaTypeVideo, cb)
        print("Waiting for you to click Allow on the camera prompt...", flush=True)
        import Foundation
        loop = Foundation.NSRunLoop.currentRunLoop()
        import time as _t
        end = _t.time() + timeout
        while not done.is_set() and _t.time() < end:
            loop.runUntilDate_(Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.1))
        return bool(answer and answer[0])
    except Exception as e:
        print("camera permission check skipped:", e, flush=True)
        return True

MODEL = sys.argv[1] if len(sys.argv) > 1 else "yolov9c.pt"
CAM = int(sys.argv[2]) if len(sys.argv) > 2 else 0

if not request_camera_access():
    sys.exit('Camera access was denied. Allow it in System Settings > Privacy & Security > Camera.')
model = YOLO(MODEL)
cap = cv2.VideoCapture(CAM)
if not cap.isOpened():
    sys.exit(f"Could not open camera {CAM}. Check System Settings > Privacy > Camera.")

print(f"Running {MODEL} on camera {CAM}. Press q in the video window to quit.")
WIN = "YOLOv9 webcam (press q to quit)"
cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
try:
    import AppKit
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    app.activateIgnoringOtherApps_(True)
    cv2.setWindowProperty(WIN, cv2.WND_PROP_TOPMOST, 1)
except Exception as e:
    print("could not raise window:", e, flush=True)
prev = time.time()
while True:
    ok, frame = cap.read()
    if not ok:
        break
    results = model.predict(frame, device="mps", conf=0.4, verbose=False)
    out = results[0].plot()
    now = time.time()
    fps = 1.0 / max(now - prev, 1e-6)
    prev = now
    cv2.putText(out, f"{MODEL}  {fps:.1f} FPS", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.imshow(WIN, out)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
