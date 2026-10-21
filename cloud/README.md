# VERBATIM Cloud GPU

Optional. Runs VERBATIM's heavy engines — **music (ACE-Step 1.5), voice tone-colour & singing conversion
(OpenVoice V2), lip-sync (LatentSync 1.6) and the quality scorers** — on a GPU server you control. Transcription,
editing, mixing and the Master Log stay on your computer.

© 2026 Infinite Story LLP. Proprietary.

## 1 · Rent or use a GPU machine
Any NVIDIA GPU with 24 GB+ for music + lip-sync (L4, A10G, RTX 4090, A100, H100). Ubuntu 22.04/24.04.
RunPod, Lambda, Vast.ai, AWS g6/g5, GCP g2 all work.

## 2 · Install
```bash
git clone https://github.com/Rakschit-B/Verbatim && cd Verbatim
TOKEN=$(openssl rand -hex 24); echo "$TOKEN"      # keep this — it goes into VERBATIM Settings
sudo bash cloud/install.sh --token "$TOKEN" --with-lipsync
```
or with Docker: `docker build -t verbatim-cloud -f cloud/Dockerfile . && docker run --gpus all -p 127.0.0.1:8765:8765 -e VERBATIM_TOKEN=$TOKEN -v verbatim-models:/models verbatim-cloud`

Models download on first use into `/opt/verbatim-models` (≈ 20 GB) and stay there.

## 3 · Make it reachable — pick one
* **HTTPS (recommended):** install Caddy and add `gpu.yourdomain.com { reverse_proxy 127.0.0.1:8765 }`.
  Server address in VERBATIM: `https://gpu.yourdomain.com`.
* **SSH tunnel (no domain needed):** on your Mac `ssh -N -L 8765:127.0.0.1:8765 user@server`, then use
  `http://127.0.0.1:8765`.

Never expose port 8765 to the internet without HTTPS.

## 4 · Connect VERBATIM
Settings › **Cloud GPU** → server address + access token → **Test connection** → tick the engines to run there.
Untick (or switch Cloud GPU off) at any time to run everything on your computer again.

## What is sent
Only the audio/video a job needs (e.g. the vocal stem for singing conversion, the dubbed film for lip-sync).
Files are deleted from the server as soon as the job returns. One job runs at a time; others wait in line.
