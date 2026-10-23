# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Local lip-sync for Mac and Windows (no NVIDIA needed): ONNX Runtime + OpenCV.

    film frames → face found in every frame (YOLO-face) → steady crop → mouth re-drawn to the new dialogue
    (Wav2Lip-GAN, 96 px, driven by the dub's mel spectrogram) → blended back with a feathered lower-face mask
    → re-encoded with the dubbed soundtrack.

Model weights: Wav2Lip-GAN (research licence — VERBATIM internal use) and YOLO-face, as ONNX files published in
the FaceFusion assets on GitHub; downloaded once into the models folder. Slower than a GPU, but it runs on any
Mac or PC — CoreML on Apple silicon, DirectML on Windows when available."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import numpy as np

from .platform_info import IS_MAC, IS_WINDOWS, ffmpeg_path, models_dir

BASE = "https://github.com/facefusion/facefusion-assets/releases/download/models-3.0.0/"
FILES = {"wav2lip": "wav2lip_gan_96.onnx", "face": "yoloface_8n.onnx"}
SIZE_MB = 160
LOCAL_LIMIT_MIN = 25          # longer films need a 40-core-GPU Mac, an NVIDIA GPU or the Cloud GPU


def model_dir() -> Path:
    d = models_dir() / "lipsync"
    d.mkdir(parents=True, exist_ok=True)
    return d


def installed() -> bool:
    return all((model_dir() / f).exists() for f in FILES.values())


def ensure(progress=None):
    from .download import fetch

    for k, f in FILES.items():
        p = model_dir() / f
        if not p.exists():
            fetch(BASE + f, p, progress, f"Lip-sync model ({k})")
    return model_dir()


# ---------------------------------------------------------------------- hardware gate
def hardware() -> dict:
    """What this machine can do: Apple GPU cores, NVIDIA present, RAM."""
    info = {"gpu_cores": 0, "nvidia": False, "ram_gb": 0}
    try:
        import os

        info["ram_gb"] = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9) if not IS_WINDOWS else 0
    except Exception:
        pass
    try:
        if IS_MAC:
            out = subprocess.run(["system_profiler", "SPDisplaysDataType"], capture_output=True, text=True,
                                 timeout=15).stdout
            import re

            m = re.search(r"Total Number of Cores:\s*(\d+)", out)
            info["gpu_cores"] = int(m.group(1)) if m else 0
        else:
            r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=10,
                               creationflags=0x08000000 if IS_WINDOWS else 0)
            info["nvidia"] = r.returncode == 0 and "GPU" in r.stdout
    except Exception:
        pass
    return info


def allowed_minutes(hw: dict | None = None, cloud: bool = False) -> float:
    hw = hw or hardware()
    if cloud or hw.get("nvidia") or hw.get("gpu_cores", 0) >= 40:
        return 600.0
    return float(LOCAL_LIMIT_MIN)


# ---------------------------------------------------------------------- audio features (Wav2Lip mel)
def _mel_basis(sr=16000, n_fft=800, n_mels=80, fmin=55.0, fmax=7600.0) -> np.ndarray:
    def hz_to_mel(f):
        f = np.asanyarray(f, dtype=float)
        mels = f / (200.0 / 3)
        logf = f >= 1000.0
        return np.where(logf, 15.0 + np.log(np.maximum(f, 1e-9) / 1000.0) / (np.log(6.4) / 27.0), mels)

    def mel_to_hz(m):
        m = np.asanyarray(m, dtype=float)
        f = (200.0 / 3) * m
        logm = m >= 15.0
        return np.where(logm, 1000.0 * np.exp((np.log(6.4) / 27.0) * (m - 15.0)), f)

    fft_f = np.linspace(0, sr / 2, 1 + n_fft // 2)
    mel_f = mel_to_hz(np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mels + 2))
    fdiff = np.diff(mel_f)
    ramps = mel_f[:, None] - fft_f[None, :]
    w = np.zeros((n_mels, len(fft_f)))
    for i in range(n_mels):
        lower = -ramps[i] / fdiff[i]
        upper = ramps[i + 2] / fdiff[i + 1]
        w[i] = np.maximum(0, np.minimum(lower, upper))
    enorm = 2.0 / (mel_f[2:n_mels + 2] - mel_f[:n_mels])
    return (w * enorm[:, None]).astype(np.float32)


def mel_spectrogram(wav16k: np.ndarray) -> np.ndarray:
    """Wav2Lip's normalised log-mel (80 × frames at 80 frames/s)."""
    x = np.append(wav16k[0], wav16k[1:] - 0.97 * wav16k[:-1]).astype(np.float32)
    n_fft, hop = 800, 200
    x = np.pad(x, (n_fft // 2, n_fft // 2))
    win = np.hanning(n_fft + 1)[:-1].astype(np.float32)
    n = 1 + (len(x) - n_fft) // hop
    frames = np.lib.stride_tricks.as_strided(x, (n, n_fft), (x.strides[0] * hop, x.strides[0]))
    spec = np.abs(np.fft.rfft(frames * win, axis=1)).T
    mel = _mel_basis() @ spec
    s = 20 * np.log10(np.maximum(1e-5, mel)) - 20
    return np.clip(8 * ((s + 100) / 100) - 4, -4, 4).astype(np.float32)


# ---------------------------------------------------------------------- engines
def _session(path: Path):
    import onnxruntime as ort

    prov = []
    av = ort.get_available_providers()
    if IS_MAC and "CoreMLExecutionProvider" in av:
        prov.append("CoreMLExecutionProvider")
    if IS_WINDOWS and "DmlExecutionProvider" in av:
        prov.append("DmlExecutionProvider")
    if "CUDAExecutionProvider" in av:
        prov.append("CUDAExecutionProvider")
    prov.append("CPUExecutionProvider")
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    try:
        return ort.InferenceSession(str(path), so, providers=prov)
    except Exception:
        return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])


class FaceFinder:
    def __init__(self):
        self.s = _session(model_dir() / FILES["face"])

    def find(self, bgr: np.ndarray, thr: float = 0.5) -> list[tuple[float, float, float, float, float]]:
        import cv2

        h, w = bgr.shape[:2]
        scale = 640 / max(h, w)
        nh, nw = int(round(h * scale)), int(round(w * scale))
        canvas = np.zeros((640, 640, 3), np.float32)
        canvas[:nh, :nw] = cv2.resize(bgr, (nw, nh))[:, :, ::-1]
        out = self.s.run(None, {"input": (canvas / 255.0).transpose(2, 0, 1)[None].astype(np.float32)})[0][0].T
        keep = out[:, 4] > thr
        if not keep.any():
            return []
        b = out[keep]
        boxes = np.stack([b[:, 0] - b[:, 2] / 2, b[:, 1] - b[:, 3] / 2, b[:, 0] + b[:, 2] / 2,
                          b[:, 1] + b[:, 3] / 2], 1) / scale
        idx = cv2.dnn.NMSBoxes([[float(x0), float(y0), float(x1 - x0), float(y1 - y0)] for x0, y0, x1, y1 in boxes],
                               b[:, 4].astype(float).tolist(), thr, 0.4)
        idx = np.array(idx).reshape(-1)
        return [(*map(float, boxes[i]), float(b[i, 4])) for i in idx]


def _largest(faces):
    return max(faces, key=lambda f: (f[2] - f[0]) * (f[3] - f[1])) if faces else None


def _probe(video: Path) -> tuple[int, int, float, float]:
    r = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", str(video)], capture_output=True, text=True,
                       errors="replace", creationflags=0x08000000 if IS_WINDOWS else 0)
    import re

    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", r.stderr)
    f = re.search(r"([\d.]+) fps", r.stderr)
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    if not m:
        raise RuntimeError("No video stream found")
    dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0.0
    return int(m.group(1)), int(m.group(2)), float(f.group(1)) if f else 25.0, dur


def sync(video: str | Path, audio: str | Path, out: str | Path, progress=None, gate_audio: bool = True,
         batch: int = 16, cloud: bool = False, soundtrack: str | Path | None = None) -> dict:
    """Re-time the mouth of the main face in `video` to the dialogue in `audio`. Writes an MP4 whose sound is
    `soundtrack` (e.g. the full dubbed mix) — or `audio` when no soundtrack is given."""
    import cv2

    from .voicelab import decode

    say = progress or (lambda f, m: None)
    video, audio, out = Path(video), Path(audio), Path(out)
    w, h, fps, dur = _probe(video)
    if dur / 60 > allowed_minutes(cloud=cloud) + 0.01:
        raise RuntimeError(f"This film is {dur / 60:.0f} min. On this computer lip-sync runs up to {LOCAL_LIMIT_MIN} "
                           "min — use a Mac with a 40-core GPU, an NVIDIA PC, or the Cloud GPU for longer films.")
    say(0.01, "Preparing the lip-sync models (one-time download ≈ 160 MB)…")
    ensure(lambda f, m: say(0.01 + 0.03 * f, m))
    w2l = _session(model_dir() / FILES["wav2lip"])
    finder = FaceFinder()
    wav = decode(audio, 16000, 1)
    wav = wav.mean(1) if wav.ndim > 1 else wav
    mel = mel_spectrogram(wav.astype(np.float32))
    hop = 16000 // 80
    energy = np.sqrt(np.convolve(wav ** 2, np.ones(hop * 8) / (hop * 8), mode="same") + 1e-12)
    speech_thr = max(1e-4, np.percentile(energy, 60) * 0.5)
    flags = 0x08000000 if IS_WINDOWS else 0
    reader = subprocess.Popen([ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-i", str(video), "-f", "rawvideo",
                               "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE, creationflags=flags)
    tmp = out.with_suffix(".video.mp4")
    writer = subprocess.Popen([ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
                               "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps:.5f}", "-i", "-", "-c:v", "libx264",
                               "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(tmp)],
                              stdin=subprocess.PIPE, creationflags=flags)
    n_total = max(1, int(dur * fps))
    fsize = w * h * 3
    box_hist: list[np.ndarray] = []
    pending: list[tuple] = []
    synced = 0
    t0 = time.time()
    i = 0
    # feathered lower-face mask in 96×96 crop space
    yy, xx = np.mgrid[0:96, 0:96]
    mask96 = np.clip(1.0 - (((xx - 48) / 40.0) ** 2 + ((yy - 66) / 34.0) ** 2), 0, 1) ** 0.6
    mask96[:44] = 0
    mask96 = cv2.GaussianBlur(mask96.astype(np.float32), (0, 0), 3)

    def flush():
        nonlocal synced
        if not pending:
            return
        faces = np.stack([p[2] for p in pending]).astype(np.float32)          # (B,96,96,3) BGR
        masked = faces.copy()
        masked[:, 48:] = 0
        tgt = np.concatenate([masked, faces], 3).transpose(0, 3, 1, 2) / 255.0
        src = np.stack([p[3] for p in pending])[:, None]
        pred = w2l.run(None, {"source": src.astype(np.float32), "target": tgt.astype(np.float32)})[0]
        pred = (np.clip(pred.transpose(0, 2, 3, 1), 0, 1) * 255).astype(np.float32)
        for (frame, box, face, _m), p in zip(pending, pred):
            x0, y0, x1, y1 = box
            bw, bh = x1 - x0, y1 - y0
            patch = cv2.resize(p, (bw, bh), interpolation=cv2.INTER_CUBIC)
            soft = cv2.GaussianBlur(patch, (0, 0), 1.2)
            patch = cv2.addWeighted(patch, 1.45, soft, -0.45, 0)              # restore crispness after upscaling
            mk = cv2.resize(mask96, (bw, bh))[:, :, None]
            roi = frame[y0:y1, x0:x1].astype(np.float32)
            frame[y0:y1, x0:x1] = np.clip(roi * (1 - mk) + patch * mk, 0, 255).astype(np.uint8)
            writer.stdin.write(frame.tobytes())
            synced += 1
        pending.clear()

    while True:
        raw = reader.stdout.read(fsize)
        if len(raw) < fsize:
            break
        frame = np.frombuffer(raw, np.uint8).reshape(h, w, 3).copy()
        t = i / fps
        a_idx = min(len(energy) - 1, int(t * 16000))
        speaking = (not gate_audio) or energy[max(0, a_idx - 4000):a_idx + 4000].max() > speech_thr
        face = _largest(finder.find(frame)) if speaking else None
        if face is None:
            flush()
            writer.stdin.write(frame.tobytes())
            box_hist.clear()
        else:
            x0, y0, x1, y1, _s = face
            y1 = y1 + 10 * (h / 360.0)                                     # Wav2Lip's chin padding
            box_hist.append(np.array([x0, y0, x1, y1]))
            box_hist[:] = box_hist[-5:]
            bx = np.mean(box_hist, 0)
            x0, y0 = max(0, int(bx[0])), max(0, int(bx[1]))
            x1, y1 = min(w, int(bx[2])), min(h, int(bx[3]))
            if x1 - x0 < 24 or y1 - y0 < 24:
                flush()
                writer.stdin.write(frame.tobytes())
            else:
                crop = cv2.resize(frame[y0:y1, x0:x1], (96, 96), interpolation=cv2.INTER_AREA)
                st = int(80.0 * t)
                m = mel[:, st:st + 16] if st + 16 <= mel.shape[1] else mel[:, -16:]
                if m.shape[1] < 16:
                    m = np.pad(m, ((0, 0), (0, 16 - m.shape[1])), constant_values=-4)
                pending.append((frame, (x0, y0, x1, y1), crop, m))
                if len(pending) >= batch:
                    flush()
        i += 1
        if i % 25 == 0:
            el = time.time() - t0
            rate = i / max(el, 1e-3)
            left = (n_total - i) / max(rate, 1e-3)
            say(0.05 + 0.9 * min(1.0, i / n_total), f"Lip-sync {i}/{n_total} frames · {rate:.1f} fps · "
                                                    f"~{int(left // 60)} min {int(left % 60)} s left")
    flush()
    writer.stdin.close()
    writer.wait()
    reader.wait()
    say(0.96, "Adding the soundtrack…")
    r = subprocess.run([ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(tmp), "-i",
                        str(soundtrack or audio),
                        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                        str(out)], capture_output=True, creationflags=flags)
    tmp.unlink(missing_ok=True)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError("Could not write the lip-synced film")
    say(1.0, "Lip-sync done.")
    return {"out": str(out), "frames": i, "synced": synced, "seconds": round(time.time() - t0, 1),
            "fps": round(i / max(1e-3, time.time() - t0), 2)}
