# VERBATIM Cloud GPU — container image. © 2026 Infinite Story LLP.
# docker build -t verbatim-cloud -f cloud/Dockerfile .
# docker run --gpus all -p 8765:8765 -e VERBATIM_TOKEN=... -v verbatim-models:/models verbatim-cloud
FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu24.04
RUN apt-get update && apt-get install -y python3 python3-venv python3-pip git ffmpeg libsndfile1 espeak-ng && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /venv
ENV PATH=/venv/bin:$PATH VERBATIM_MODELS=/models VERBATIM_PORT=8765 PYTHONPATH=/opt/ACE-Step-1.5 \
    VERBATIM_LATENTSYNC=/opt/LatentSync PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
RUN pip install -U pip wheel && pip install torch==2.9.0 torchaudio==2.9.0 --index-url https://download.pytorch.org/whl/cu128 && \
    pip install "transformers>=4.51,<4.58" accelerate librosa soundfile "numpy<2.4" pydub huggingface_hub diffusers peft \
      loguru tqdm pyyaml xxhash einops vector-quantize-pytorch scipy safetensors
RUN git clone https://github.com/ace-step/ACE-Step-1.5 /opt/ACE-Step-1.5 && git -C /opt/ACE-Step-1.5 checkout ca1e85fe9430179831e6bc6be790c332190a3866 && pip install -e /opt/ACE-Step-1.5 --no-deps
ARG LIPSYNC=1
RUN if [ "$LIPSYNC" = 1 ]; then git clone --depth 1 https://github.com/bytedance/LatentSync /opt/LatentSync && \
      pip install -r /opt/LatentSync/requirements.txt; fi
COPY engine_host /opt/engine_host
VOLUME /models
EXPOSE 8765
CMD ["python", "/opt/engine_host/server.py"]
