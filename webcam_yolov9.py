"""Entry point the 'YOLO Webcam' app runs.

Picks which demo to run from mode.txt:
  sensory  (default) -> sensory_demo.py   pose + 10 sensory triggers
  objects            -> object_demo.py    plain YOLOv9 object boxes
"""
import fcntl, multiprocessing, os, runpy, sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Inside the .app, Python thinks the app launcher is "python". Libraries that start
# helper processes would then relaunch the whole app, over and over. Point them at
# the real Python instead.
REAL_PY = os.path.join(HERE, ".venv", "bin", "python")
if os.path.exists(REAL_PY):
    sys.executable = REAL_PY
    multiprocessing.set_executable(REAL_PY)

# Only one copy may run at a time.
_lock = open(os.path.join(HERE, ".running.lock"), "w")
try:
    fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    print("Another copy is already running; this one exits.", flush=True)
    sys.exit(0)
mode = "sensory"
p = os.path.join(HERE, "mode.txt")
if os.path.exists(p):
    mode = open(p).read().strip() or mode
script = {"sensory": "sensory_demo.py", "objects": "object_demo.py"}.get(mode, "sensory_demo.py")
sys.argv = [script] + sys.argv[1:]
sys.path.insert(0, HERE)
runpy.run_path(os.path.join(HERE, script), run_name="__main__")
