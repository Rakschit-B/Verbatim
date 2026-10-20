# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Audio extraction and conditioning.

Every engine receives the same 16 kHz mono float32 signal, decoded once by FFmpeg.
Source media is only ever read, never modified.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .platform_info import IS_WINDOWS, ffmpeg_path

SAMPLE_RATE = 16000

MEDIA_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".mkv", ".avi", ".wmv", ".webm", ".mpg", ".mpeg", ".3gp", ".flv", ".mts", ".m2ts",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".aif", ".caf",
}

# Conditioning chains. Whisper-family models are trained on unprocessed audio, so heavy
# denoising can *hurt* accuracy; "normalize" is the safe default (it only fixes level).
ENHANCEMENTS = {
    "off": None,
    "normalize": "highpass=f=60,loudnorm=I=-18:TP=-2:LRA=11",
    "clean": "highpass=f=80,lowpass=f=7800,afftdn=nf=-25,loudnorm=I=-18:TP=-2:LRA=11",
}


@dataclass
class MediaInfo:
    duration: float
    channels: int
    sample_rate: int
    codec: str
    has_video: bool


def _creationflags() -> int:
    return 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW


def probe(path: str | Path) -> MediaInfo:
    """Read basic stream info using `ffmpeg -i` (no ffprobe dependency)."""
    p = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-nostdin", "-i", str(path)],
        capture_output=True, text=True, errors="replace", creationflags=_creationflags(),
    )
    err = p.stderr
    dur = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    a = re.search(r"Audio:\s*([^,\s]+)[^\n]*?(\d+)\s*Hz,\s*([^,\n]+)", err)
    channels = 1
    sr = 0
    codec = ""
    if a:
        codec, sr = a.group(1), int(a.group(2))
        layout = a.group(3).strip().lower()
        named = {"mono": 1, "stereo": 2, "quad": 4}
        num = re.match(r"(\d+)(?:\.(\d+))?", layout)
        if layout in named:
            channels = named[layout]
        elif num:
            channels = int(num.group(1)) + int(num.group(2) or 0)
        else:
            channels = 2
    elif "Audio:" not in err:
        raise RuntimeError("No audio stream found in this file.")
    return MediaInfo(dur, channels, sr, codec, "Video:" in err)


def load_audio(path: str | Path, enhancement: str = "normalize", channel: int | None = None) -> np.ndarray:
    """Decode any media file to 16 kHz mono float32 in [-1, 1].

    `channel` selects a single input channel (0-based) for multi-channel recordings where
    each person is on their own track; None down-mixes all channels.
    """
    cmd = [ffmpeg_path(), "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn", "-sn", "-dn"]
    filters = []
    if channel is not None:
        filters.append(f"pan=mono|c0=c{int(channel)}")
    chain = ENHANCEMENTS.get(enhancement)
    if chain:
        filters.append(chain)
    if filters:
        cmd += ["-af", ",".join(filters)]
    cmd += ["-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-acodec", "pcm_f32le", "-"]
    p = subprocess.run(cmd, capture_output=True, creationflags=_creationflags())
    if p.returncode != 0:
        raise RuntimeError("FFmpeg could not decode the audio: " + p.stderr.decode(errors="replace")[-400:])
    audio = np.frombuffer(p.stdout, dtype=np.float32).copy()
    if audio.size == 0:
        raise RuntimeError("The file contains no decodable audio.")
    np.clip(audio, -1.0, 1.0, out=audio)
    return audio


def write_wav(path: str | Path, audio: np.ndarray, sr: int = SAMPLE_RATE) -> Path:
    """Write float32 mono audio as 16-bit PCM WAV (used for cloud upload and engines that need a file)."""
    import wave

    path = Path(path)
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def signal_stats(audio: np.ndarray) -> dict:
    """Simple audio-quality indicators recorded in the master log."""
    if audio.size == 0:
        return {"rms_dbfs": -120.0, "peak_dbfs": -120.0, "clipping_pct": 0.0}
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(audio)))
    clip = float(np.mean(np.abs(audio) >= 0.999)) * 100
    db = lambda v: round(20 * np.log10(max(v, 1e-6)), 1)  # noqa: E731
    return {"rms_dbfs": db(rms), "peak_dbfs": db(peak), "clipping_pct": round(clip, 3)}
