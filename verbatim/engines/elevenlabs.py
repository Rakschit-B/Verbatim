# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""ElevenLabs Scribe v2 (cloud) — highest-accuracy option, optional and opt-in.

Scribe v2 is #6 on the Open ASR Leaderboard snapshot (mean WER 5.83% vs 7.44% for
Whisper large-v3) and returns per-word log-probabilities, speaker IDs (up to 32
speakers) and audio-event tags. Features adopted from the ElevenLabs API/skills repos:
  keyterms (custom vocabulary), diarize + num_speakers, timestamps_granularity=word,
  tag_audio_events, temperature=0 + seed for repeatability, no_verbatim=false for true
  verbatim, request-id captured for the audit log.
Audio is uploaded to ElevenLabs — only use it where the client's data policy allows.
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from ..model import Transcript, Word
from .base import DecodeOptions, Engine, Progress, logprob_to_prob, words_to_segments

API = "https://api.elevenlabs.io/v1/speech-to-text"
ISO1_TO_3 = {"en": "eng", "hi": "hin", "es": "spa", "fr": "fra", "de": "deu", "it": "ita", "pt": "por", "ja": "jpn",
             "zh": "zho", "ar": "ara", "bn": "ben", "ta": "tam", "te": "tel", "mr": "mar", "gu": "guj", "kn": "kan",
             "ml": "mal", "pa": "pan", "ur": "urd", "ru": "rus", "ko": "kor", "nl": "nld", "tr": "tur"}
ISO3_TO_1 = {v: k for k, v in ISO1_TO_3.items()}


def get_api_key() -> str | None:
    import os

    key = os.environ.get("ELEVENLABS_API_KEY")
    if key:
        return key
    try:
        import keyring

        return keyring.get_password("VERBATIM", "elevenlabs_api_key")
    except Exception:
        return None


def set_api_key(key: str) -> None:
    import keyring  # macOS Keychain / Windows Credential Manager

    keyring.set_password("VERBATIM", "elevenlabs_api_key", key.strip())


class ElevenLabsScribeEngine(Engine):
    id = "elevenlabs"
    label = "ElevenLabs Scribe v2 (cloud)"
    model = "scribe_v2"

    def __init__(self, model_id: str = "scribe_v2", api_key: str | None = None, timeout: int = 1800):
        self.model = model_id
        self.api_key = api_key
        self.timeout = timeout
        self.last_request_id = ""

    @classmethod
    def available(cls):
        try:
            import requests  # noqa: F401
        except Exception:
            return False, "requests not installed"
        if not get_api_key():
            return False, "add an ElevenLabs API key in Settings"
        return True, ""

    def transcribe(self, audio, chunks, opts: DecodeOptions, progress: Progress | None = None) -> Transcript:
        import requests

        from ..audio import write_wav

        key = self.api_key or get_api_key()
        if not key:
            raise RuntimeError("No ElevenLabs API key configured.")
        data: list[tuple[str, str]] = [
            ("model_id", self.model), ("timestamps_granularity", "word"), ("tag_audio_events", "true"),
            ("diarize", "true" if opts.diarize else "false"), ("temperature", "0"), ("seed", "42"),
        ]
        if self.model.startswith("scribe_v2"):
            data.append(("no_verbatim", "false" if opts.verbatim else "true"))
        if opts.language:
            data.append(("language_code", ISO1_TO_3.get(opts.language, opts.language)))
        if opts.diarize and opts.num_speakers:
            data.append(("num_speakers", str(int(opts.num_speakers))))
        for term in opts.vocabulary.keyterms():
            data.append(("keyterms", term))
        if progress:
            progress(0.05, "Uploading audio to ElevenLabs Scribe…")
        with tempfile.TemporaryDirectory() as tmp:
            wav = write_wav(Path(tmp) / "audio.wav", audio)
            upload, mime = wav, "audio/wav"
            try:  # lossless FLAC is ~45% of WAV size: faster uploads, identical audio
                import subprocess

                from ..platform_info import ffmpeg_path

                flac = Path(tmp) / "audio.flac"
                subprocess.run([ffmpeg_path(), "-nostdin", "-loglevel", "error", "-y", "-i", str(wav), str(flac)],
                               check=True, capture_output=True)
                upload, mime = flac, "audio/flac"
            except Exception:
                pass
            for attempt in range(4):
                with open(upload, "rb") as fh:
                    r = requests.post(API, headers={"xi-api-key": key}, data=data,
                                      files={"file": (upload.name, fh, mime)}, timeout=self.timeout)
                if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                break
        if r.status_code != 200:
            raise RuntimeError(f"ElevenLabs error {r.status_code}: {r.text[:300]}")
        self.last_request_id = r.headers.get("request-id", "")
        if progress:
            progress(0.95, "Scribe transcript received")
        return self.parse(r.json(), self.model)

    @staticmethod
    def parse(payload: dict | str, model: str = "scribe_v2") -> Transcript:
        if isinstance(payload, str):
            payload = json.loads(payload)
        words: list[Word] = []
        events = []
        pending_space = False
        for w in payload.get("words", []):
            kind = w.get("type", "word")
            if kind == "spacing":
                pending_space = True
                continue
            if kind == "audio_event":
                events.append({"start": w.get("start"), "end": w.get("end"), "event": w.get("text")})
                continue
            text = w.get("text", "")
            is_punct = text and all(not c.isalnum() for c in text)
            if words and (is_punct and not pending_space):
                words[-1].text += text
                words[-1].end = max(words[-1].end, float(w.get("end") or words[-1].end))
            else:
                speaker = w.get("speaker_id")
                words.append(Word(" " + text, float(w.get("start") or 0), float(w.get("end") or 0),
                                  logprob_to_prob(w.get("logprob")), _speaker_label(speaker)))
            pending_space = False
        segs = words_to_segments(words)
        lang = payload.get("language_code") or "unknown"
        return Transcript(segs, ISO3_TO_1.get(lang, lang), "elevenlabs", model,
                          payload.get("language_probability"), events)


def _speaker_label(sid) -> str | None:
    if sid is None:
        return None
    s = str(sid)
    if s.startswith("speaker_"):
        try:
            return f"Speaker {int(s.split('_')[1]) + 1}"
        except ValueError:
            return s
    return s
