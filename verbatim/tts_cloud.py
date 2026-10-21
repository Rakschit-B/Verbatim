# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Optional premium cloud voices, used through their official public APIs with the user's own key.

• ElevenLabs — text-to-speech (eleven_v3 / eleven_v4 / eleven_multilingual_v2) with inline audio tags for
  emotion, and Instant Voice Clone (POST /v1/voices/add) for custom voices made in Voice Lab.
• Microsoft Azure AI Speech — Neural voices driven by SSML (speaking styles, style degree, emphasis,
  prosody). Region + key from the Azure portal.

Keys are stored in the system keychain. Nothing is sent anywhere unless the user picks one of these
engines for a job; local engines remain the default and work fully offline.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import numpy as np

EL_API = "https://api.elevenlabs.io"
EL_MODELS = [("eleven_v3", "Eleven v3 — most expressive, audio tags"),
             ("eleven_v4", "Eleven v4 — newest, 90+ languages"),
             ("eleven_multilingual_v2", "Multilingual v2 — steady, long-form")]
EL_SR = 44100

# Azure Neural voices with a female and a male option for the languages VERBATIM dubs most
AZURE_VOICES = {
    "en": [("en-US-AvaMultilingualNeural", "Ava", "female"), ("en-US-AndrewMultilingualNeural", "Andrew", "male"),
           ("en-IN-NeerjaNeural", "Neerja (Indian English)", "female"), ("en-IN-PrabhatNeural", "Prabhat (Indian English)", "male"),
           ("en-GB-SoniaNeural", "Sonia (British)", "female"), ("en-GB-RyanNeural", "Ryan (British)", "male")],
    "hi": [("hi-IN-SwaraNeural", "Swara", "female"), ("hi-IN-MadhurNeural", "Madhur", "male"),
           ("hi-IN-AnanyaNeural", "Ananya", "female"), ("hi-IN-AaravNeural", "Aarav", "male")],
    "bn": [("bn-IN-TanishaaNeural", "Tanishaa", "female"), ("bn-IN-BashkarNeural", "Bashkar", "male")],
    "he": [("he-IL-HilaNeural", "Hila", "female"), ("he-IL-AvriNeural", "Avri", "male")],
    "fr": [("fr-FR-DeniseNeural", "Denise", "female"), ("fr-FR-HenriNeural", "Henri", "male")],
    "es": [("es-ES-ElviraNeural", "Elvira", "female"), ("es-ES-AlvaroNeural", "Álvaro", "male"),
           ("es-MX-DaliaNeural", "Dalia (Mexico)", "female"), ("es-MX-JorgeNeural", "Jorge (Mexico)", "male")],
    "ru": [("ru-RU-SvetlanaNeural", "Svetlana", "female"), ("ru-RU-DmitryNeural", "Dmitry", "male")],
    "ja": [("ja-JP-NanamiNeural", "Nanami", "female"), ("ja-JP-KeitaNeural", "Keita", "male")],
    "zh": [("zh-CN-XiaoxiaoNeural", "Xiaoxiao", "female"), ("zh-CN-YunxiNeural", "Yunxi", "male")],
    "de": [("de-DE-KatjaNeural", "Katja", "female"), ("de-DE-ConradNeural", "Conrad", "male")],
    "ar": [("ar-AE-FatimaNeural", "Fatima", "female"), ("ar-AE-HamdanNeural", "Hamdan", "male")],
    "ta": [("ta-IN-PallaviNeural", "Pallavi", "female"), ("ta-IN-ValluvarNeural", "Valluvar", "male")],
    "te": [("te-IN-ShrutiNeural", "Shruti", "female"), ("te-IN-MohanNeural", "Mohan", "male")],
    "mr": [("mr-IN-AarohiNeural", "Aarohi", "female"), ("mr-IN-ManoharNeural", "Manohar", "male")],
    "gu": [("gu-IN-DhwaniNeural", "Dhwani", "female"), ("gu-IN-NiranjanNeural", "Niranjan", "male")],
    "pt": [("pt-BR-FranciscaNeural", "Francisca", "female"), ("pt-BR-AntonioNeural", "Antônio", "male")],
    "it": [("it-IT-ElsaNeural", "Elsa", "female"), ("it-IT-DiegoNeural", "Diego", "male")],
}
AZ_LOCALE = {"en": "en-US", "hi": "hi-IN", "bn": "bn-IN", "he": "he-IL", "fr": "fr-FR", "es": "es-ES", "ru": "ru-RU",
             "ja": "ja-JP", "zh": "zh-CN", "de": "de-DE", "ar": "ar-AE", "ta": "ta-IN", "te": "te-IN", "mr": "mr-IN",
             "gu": "gu-IN", "pt": "pt-BR", "it": "it-IT"}


# ---------------------------------------------------------------- keys (system keychain)
def _kr(name: str, value: str | None = None) -> str:
    try:
        import keyring

        if value is None:
            return keyring.get_password("VERBATIM", name) or ""
        if value:
            keyring.set_password("VERBATIM", name, value)
        else:
            try:
                keyring.delete_password("VERBATIM", name)
            except Exception:
                pass
    except Exception:
        pass
    return value or ""


def eleven_key() -> str:
    from .engines import elevenlabs as stt   # same key as ElevenLabs Scribe transcription

    for fn in ("get_api_key", "api_key", "load_key"):
        f = getattr(stt, fn, None)
        if callable(f):
            try:
                k = f()
                if k:
                    return k
            except Exception:
                pass
    return _kr("elevenlabs_api_key")


_CACHE: dict = {}


def _flag(name: str):
    from .platform_info import user_data_dir

    return user_data_dir() / f".{name}.configured"


def azure_configured() -> bool:
    """Cheap check (a marker file) — never touches the Keychain, so building the UI cannot trigger macOS
    Keychain prompts (3.6 fix: 62 Keychain reads at startup could look like the app hanging)."""
    return _flag("azure").exists()


def azure_key() -> tuple[str, str]:
    if "azure" not in _CACHE:
        _CACHE["azure"] = (_kr("azure_speech_key"), _kr("azure_speech_region") or "centralindia")
    return _CACHE["azure"]


def set_azure(key: str, region: str):
    _kr("azure_speech_key", key.strip())
    _kr("azure_speech_region", region.strip() or "centralindia")
    _CACHE.pop("azure", None)
    f = _flag("azure")
    if key.strip():
        f.write_text("1")
    else:
        f.unlink(missing_ok=True)


# ---------------------------------------------------------------- HTTP
def _post(url: str, body: bytes, headers: dict, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise RuntimeError(f"{url.split('/')[2]} returned {exc.code}: {detail}") from None


def _pcm16(b: bytes) -> np.ndarray:
    return np.frombuffer(b[: len(b) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0


# ---------------------------------------------------------------- ElevenLabs
class ElevenLabs:
    def __init__(self, key: str | None = None, model: str = "eleven_v3", post=None):
        self.key = key or eleven_key()
        if not self.key:
            raise RuntimeError("Add your ElevenLabs API key in Settings › Cloud engines first.")
        self.model = model
        self.post = post or _post

    def speak(self, text: str, voice_id: str, lang: str = "", speed: float = 1.0, settings: dict | None = None
              ) -> tuple[np.ndarray, int]:
        body = {"text": text, "model_id": self.model, "voice_settings": dict(settings or {})}
        body["voice_settings"]["speed"] = round(max(0.7, min(1.2, speed)), 2)
        if lang and self.model != "eleven_multilingual_v2":
            body["language_code"] = lang
        raw = self.post(f"{EL_API}/v1/text-to-speech/{voice_id}?output_format=pcm_{EL_SR}",
                        json.dumps(body).encode(), {"xi-api-key": self.key, "Content-Type": "application/json",
                                                    "Accept": "audio/pcm"})
        return _pcm16(raw), EL_SR

    def clone(self, name: str, files: list[Path], description: str = "") -> str:
        """Instant Voice Clone from reference recordings → ElevenLabs voice_id."""
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in (("name", name), ("description", description or "Created with VERBATIM — Infinite Story LLP"),
                     ("remove_background_noise", "true")):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for f in files:
            f = Path(f)
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{f.name}"\r\n'
                         f'Content-Type: audio/wav\r\n\r\n'.encode() + f.read_bytes() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        raw = self.post(f"{EL_API}/v1/voices/add", b"".join(parts),
                        {"xi-api-key": self.key, "Content-Type": f"multipart/form-data; boundary={boundary}"})
        return json.loads(raw)["voice_id"]


# ---------------------------------------------------------------- Azure
class Azure:
    def __init__(self, key: str | None = None, region: str | None = None, post=None):
        k, r = azure_key()
        self.key, self.region = key or k, region or r
        if not self.key:
            raise RuntimeError("Add your Azure Speech key and region in Settings › Cloud engines first.")
        self.post = post or _post

    def speak_ssml(self, ssml: str) -> tuple[np.ndarray, int]:
        raw = self.post(f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1", ssml.encode("utf-8"),
                        {"Ocp-Apim-Subscription-Key": self.key, "Content-Type": "application/ssml+xml",
                         "X-Microsoft-OutputFormat": "raw-48khz-16bit-mono-pcm", "User-Agent": "VERBATIM"})
        return _pcm16(raw), 48000
