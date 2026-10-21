#!/usr/bin/env bash
# VERBATIM Cloud GPU — server install (Ubuntu 22.04/24.04 + NVIDIA driver, e.g. RunPod, Lambda, Vast, AWS g5/g6).
# © 2026 Infinite Story LLP. Usage:
#   sudo bash install.sh --token "<long random secret>" [--with-lipsync] [--port 8765]
set -euo pipefail
TOKEN=""; PORT=8765; LIPSYNC=0; PREFIX=/opt/verbatim-cloud; MODELS=/opt/verbatim-models
while [ $# -gt 0 ]; do case "$1" in
  --token) TOKEN="$2"; shift 2;; --port) PORT="$2"; shift 2;; --with-lipsync) LIPSYNC=1; shift;;
  --prefix) PREFIX="$2"; shift 2;; --models) MODELS="$2"; shift 2;; *) echo "unknown option $1"; exit 1;; esac; done
[ ${#TOKEN} -ge 24 ] || { echo "Pass --token with 24+ characters (e.g. \$(openssl rand -hex 24))"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
apt-get update -y && apt-get install -y python3.12-venv python3-pip git ffmpeg libsndfile1 espeak-ng
mkdir -p "$PREFIX" "$MODELS"
cp -r "$HERE/../engine_host" "$PREFIX/"
python3.12 -m venv "$PREFIX/venv"
PY="$PREFIX/venv/bin/python"
"$PY" -m pip install -U pip wheel
"$PY" -m pip install torch==2.9.0 torchaudio==2.9.0 --index-url https://download.pytorch.org/whl/cu128
"$PY" -m pip install "transformers>=4.51,<4.58" accelerate librosa soundfile "numpy<2.4" pydub huggingface_hub \
  diffusers peft loguru tqdm pyyaml xxhash einops vector-quantize-pytorch scipy safetensors
# ACE-Step 1.5 (music) — source on the import path
git clone https://github.com/ace-step/ACE-Step-1.5 "$PREFIX/ACE-Step-1.5" || true
git -C "$PREFIX/ACE-Step-1.5" checkout ca1e85fe9430179831e6bc6be790c332190a3866
"$PY" -m pip install -e "$PREFIX/ACE-Step-1.5" --no-deps || true
if [ "$LIPSYNC" = 1 ]; then
  git clone --depth 1 https://github.com/bytedance/LatentSync "$PREFIX/LatentSync"
  "$PY" -m pip install -r "$PREFIX/LatentSync/requirements.txt"
  "$PY" -c "from huggingface_hub import snapshot_download as s; s('ByteDance/LatentSync-1.6', local_dir='$PREFIX/LatentSync/checkpoints')"
fi
cat > /etc/systemd/system/verbatim-cloud.service <<UNIT
[Unit]
Description=VERBATIM Cloud GPU (Infinite Story LLP)
After=network-online.target
[Service]
Environment=VERBATIM_TOKEN=$TOKEN
Environment=VERBATIM_PORT=$PORT
Environment=VERBATIM_MODELS=$MODELS
Environment=VERBATIM_LATENTSYNC=$PREFIX/LatentSync
Environment=PYTHONPATH=$PREFIX/ACE-Step-1.5
Environment=PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
ExecStart=$PY $PREFIX/engine_host/server.py --host 127.0.0.1
Restart=on-failure
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload && systemctl enable --now verbatim-cloud
echo "VERBATIM Cloud GPU is running on 127.0.0.1:$PORT. Put HTTPS in front (see README.md) or use an SSH tunnel."
