"""macOS camera permission + camera listing helpers."""
import time


def request_camera_access(timeout=600):
    return request_access("video", timeout)


def request_mic_access(timeout=600):
    return request_access("audio", timeout)


def request_access(kind="video", timeout=600):
    """Ask macOS for camera or microphone permission and wait for the user's answer."""
    try:
        import AVFoundation, Foundation, threading
        media = AVFoundation.AVMediaTypeVideo if kind == "video" else AVFoundation.AVMediaTypeAudio
        status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(media)
        if status == 3:  # authorized
            return True
        done = threading.Event(); answer = []

        def cb(granted):
            answer.append(bool(granted)); done.set()
        if status == 2:  # denied earlier
            print(f"{kind} access was denied earlier. Turn it on in System Settings > Privacy & Security.", flush=True)
            return False
        AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(media, cb)
        print(f"Waiting for you to click Allow on the {'camera' if kind == 'video' else 'microphone'} prompt...", flush=True)
        loop = Foundation.NSRunLoop.currentRunLoop()
        end = time.time() + timeout
        while not done.is_set() and time.time() < end:
            loop.runUntilDate_(Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.1))
        return bool(answer and answer[0])
    except Exception as e:
        print("camera permission check skipped:", e, flush=True)
        return True


def camera_names():
    try:
        import AVFoundation
        devs = AVFoundation.AVCaptureDevice.devicesWithMediaType_(AVFoundation.AVMediaTypeVideo)
        return [str(d.localizedName()) for d in devs]
    except Exception:
        return []


def raise_window(win):
    """Bring the OpenCV window in front of other apps."""
    import cv2
    try:
        import AppKit
        app = AppKit.NSApplication.sharedApplication()
        app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
        app.activateIgnoringOtherApps_(True)
        cv2.setWindowProperty(win, cv2.WND_PROP_TOPMOST, 1)
    except Exception as e:
        print("could not raise window:", e, flush=True)
