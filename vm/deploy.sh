#!/usr/bin/env bash
# Deploy or update the EqualEd app on the team cluster at http://<team host>/app
# (deployment/deploy-app-no-registry: python:3.12-slim, code in a ConfigMap, creds in a Secret).
# Run from the repo root on the VM:  bash vm/deploy.sh
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-/config/team-17-k8s.yaml}"
K="${KUBECTL:-$HOME/bin/kubectl}"
NS="${NS:-team-17}"
APP=equaled-app
cd "$(dirname "$0")/.."

set -a
. "$(ls /config/*.config | head -1)"
set +a
HOST="${INGRESS_URL#http://}"; HOST="${HOST#https://}"; HOST="${HOST%%/*}"
WANDB_KEY=""
[ -f vast.env ] && WANDB_KEY="$(grep '^WANDB_API_KEY=' vast.env | cut -d= -f2- | tr -d "\"'")"

files=()
for f in vm/*.py vm/requirements.txt; do files+=(--from-file="$f"); done
[ -f vm/archive_sensory_labels.json ] && files+=(--from-file=vm/archive_sensory_labels.json) \
  || { [ -f archive_sensory_labels.json ] && files+=(--from-file=archive_sensory_labels.json); }
"$K" -n "$NS" create configmap $APP-code "${files[@]}" --dry-run=client -o yaml | "$K" apply -f -

"$K" -n "$NS" create secret generic $APP-creds \
  --from-literal=VSS_URL="$INGRESS_URL" --from-literal=VSS_USERNAME="$USERNAME" \
  --from-literal=VSS_PASSWORD="$PASSWORD" --from-literal=GPU_BEARER_TOKEN="$GPU_BEARER_TOKEN" \
  --from-literal=WANDB_API_KEY="$WANDB_KEY" --dry-run=client -o yaml | "$K" apply -f - >/dev/null

# The public host does not resolve inside the cluster, so the pod talks to the backend service directly.
"$K" -n "$NS" apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata: {name: $APP, labels: {app: $APP}}
spec:
  replicas: 1
  strategy: {type: Recreate}
  selector: {matchLabels: {app: $APP}}
  template:
    metadata: {labels: {app: $APP}}
    spec:
      containers:
      - name: app
        image: python:3.12-slim
        ports: [{containerPort: 8080}]
        envFrom: [{secretRef: {name: $APP-creds}}]
        env:
        - {name: PORT, value: "8080"}
        - {name: INGRESS_URL, value: "http://video-backend-service:8000"}
        - {name: WANDB_PROJECT, value: "vastdata/$NS"}
        - {name: PYTHONUNBUFFERED, value: "1"}
        workingDir: /work
        command: ["bash", "-c"]
        args:
        - |
          set -euo pipefail
          pip install --no-cache-dir -q torch torchvision --index-url https://download.pytorch.org/whl/cpu
          pip install --no-cache-dir -q -r /code/requirements.txt imageio-ffmpeg ftfy https://github.com/ultralytics/CLIP/archive/refs/heads/main.zip
          pip uninstall -y -q opencv-python || true
          pip install --no-cache-dir -q --force-reinstall --no-deps opencv-python-headless
          ln -sf "\$(python -c 'import imageio_ffmpeg as f; print(f.get_ffmpeg_exe())')" /usr/local/bin/ffmpeg
          exec python /code/app.py --port 8080
        resources:
          requests: {cpu: "2", memory: 4Gi}
          limits: {memory: 10Gi}
        readinessProbe:
          httpGet: {path: /health, port: 8080}
          initialDelaySeconds: 20
          periodSeconds: 10
        volumeMounts:
        - {name: code, mountPath: /code}
        - {name: work, mountPath: /work}
      volumes:
      - {name: code, configMap: {name: $APP-code}}
      - {name: work, emptyDir: {}}
---
apiVersion: v1
kind: Service
metadata: {name: $APP, labels: {app: $APP}}
spec:
  selector: {app: $APP}
  ports: [{name: http, port: 80, targetPort: 8080}]
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: $APP
  labels: {app: $APP}
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /\$2
    nginx.ingress.kubernetes.io/proxy-body-size: 10m
    nginx.ingress.kubernetes.io/proxy-read-timeout: "120"
spec:
  ingressClassName: nginx
  rules:
  - host: $HOST
    http:
      paths:
      - path: /app(/|$)(.*)
        pathType: ImplementationSpecific
        backend: {service: {name: $APP, port: {number: 80}}}
EOF

"$K" -n "$NS" rollout restart deploy/$APP
echo "deploying: http://$HOST/app (about 2 minutes for pip install and weights)"
