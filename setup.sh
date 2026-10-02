#!/bin/zsh
# One-time setup on a Mac with Apple Silicon. Needs Python 3.11.
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3.11}
$PY -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
# Sound classifier (YAMNet, ~4 MB)
curl -sL -o yamnet.tflite "https://storage.googleapis.com/download.tensorflow.org/models/tflite/task_library/audio_classification/android/lite-model_yamnet_classification_tflite_1.tflite"
# Sample image for the offline self-test
curl -sL -o bus.jpg https://ultralytics.com/images/bus.jpg
# YOLO pose + YOLOE models download themselves on first run. Self-test:
.venv/bin/python sensory_demo.py --selftest
echo "Setup done. Next: ./make_app.sh, then double-click 'EqualEd.app'."
