# Third-party components

VERBATIM's own code is MIT-licensed. It uses, downloads or bundles the following; check each licence
before commercial redistribution of the packaged app.

| Component | Use | Licence |
|---|---|---|
| OpenAI Whisper model weights (via mlx-community / faster-whisper / sherpa-onnx conversions) | speech recognition | MIT |
| MLX, mlx-whisper (Apple) | Apple Silicon inference | MIT |
| faster-whisper, CTranslate2 (SYSTRAN / OpenNMT) | Windows/Intel inference | MIT |
| sherpa-onnx (k2-fsa) | ONNX runtime for Parakeet / diarisation | Apache-2.0 |
| NVIDIA Parakeet TDT 0.6B v2/v3 weights | speech recognition | CC-BY-4.0 (attribution: NVIDIA) |
| NVIDIA TitaNet small (speaker embeddings) | diarisation | CC-BY-4.0 (attribution: NVIDIA) |
| pyannote segmentation-3.0 | diarisation | MIT |
| Meta Omnilingual ASR 300M CTC (sherpa-onnx int8 export) | precise word timing (forced alignment) | Apache-2.0 |
| Supertonic 3 (Supertone Inc.; sherpa-onnx int8 export) | Voice Studio voices (10 voices × 31 languages) | code MIT; model OpenRAIL-M (use restrictions apply) |
| Google TranslateGemma 4B / 12B (GGUF quantisations) | Voice Studio offline translation | Gemma Terms of Use + Prohibited Use Policy |
| llama.cpp (ggml-org) | runs TranslateGemma locally | MIT |
| Kokoro-82M v1.0 (hexgrad; sherpa-onnx export) | Voice Studio stock voices | Apache-2.0 |
| OPUS-MT translation models via Argos Translate packages | Voice Studio offline translation | CC-BY-4.0 (models; attribution: Helsinki-NLP / OPUS-MT) |
| CTranslate2 (OpenNMT), SentencePiece (Google) | offline translation runtime | MIT / Apache-2.0 |
| Anthropic Claude API | optional cloud translation | Anthropic commercial terms (no code bundled) |
| Silero VAD v5 (bundled `assets/silero_vad.onnx`) | voice activity detection | MIT |
| ONNX Runtime (Microsoft) | inference | MIT |
| Qt for Python / PySide6 | user interface | LGPL-3.0 (dynamically linked, unmodified) |
| FFmpeg (system or imageio-ffmpeg build) | media decoding | LGPL/GPL depending on build — the imageio-ffmpeg binaries are GPL builds; ship the source offer or use a system FFmpeg if this matters for your distribution |
| openpyxl, python-docx, rapidfuzz, requests, keyring, cryptography, numpy | utilities | MIT / BSD / Apache-2.0 / PSF |
| ElevenLabs Scribe API | optional cloud engine | ElevenLabs terms of service (no code bundled) |
| `tests/data/jfk.flac` (from openai/whisper tests) | test fixture | MIT |

No code from MacWhisper, TurboScribe, Fireflies, Cockatoo or ElevenLabs' proprietary services is included;
those products were studied only for publicly documented features and workflows.
