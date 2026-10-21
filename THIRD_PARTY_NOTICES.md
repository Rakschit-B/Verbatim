# Third-party components

VERBATIM's own code is proprietary to Infinite Story LLP (see LICENSE). It uses, downloads or bundles the
following third-party components, which remain under their own licences; their notices must be kept.

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
| Resemble AI Chatterbox Multilingual (ONNX export by onnx-community) | Expressive voices & voice cloning, 23 languages | MIT |
| ZipVoice (k2-fsa; sherpa-onnx int8 export) + Vocos 24 kHz vocoder | local English/Chinese voice cloning | Apache-2.0 (trained on the Emilia dataset — check its terms for commercial use) |
| UVR MDX-Net Voc FT (Ultimate Vocal Remover; sherpa-onnx export) | separating voice from music | MIT |
| tokenizers (Hugging Face) | Chatterbox text tokenizer | Apache-2.0 |
| pykakasi | Japanese reading for Chatterbox | GPL-3.0-or-later → optional, not bundled |
| ElevenLabs text-to-speech / voice cloning API | optional cloud voices (user's own key) | ElevenLabs terms of service (no code bundled) |
| Microsoft Azure AI Speech (Neural TTS REST API) | optional cloud voices (user's own key) | Microsoft terms (no code bundled) |
| ACE-Step 1.5 (code at the pinned commit + Ace-Step1.5 / acestep-5Hz-lm weights) | Music Studio — downloaded on first use | MIT |
| OpenVoice V2 (MyShell.ai; model code vendored in `engine_host/openvoice`, weights downloaded) | voice tone colour, singing conversion | MIT |
| PyTorch, torchaudio, transformers, diffusers, librosa (engine runtime, installed on first use) | engines | BSD / Apache-2.0 / ISC |
| python-build-standalone (Astral) | engine runtime interpreter | PSF + component licences |
| UTMOS22 (SpeechMOS implementation) · wav2vec2 SUPERB ER | quality scorecard | MIT · Apache-2.0 |
| OmniVoice (k2-fsa) — **legacy, opt-in, not bundled**; weights CC-BY-NC-4.0 (non-commercial) | legacy voice designer (being retired) | Apache-2.0 code / CC-BY-NC weights |
| Phosphor Icons 2.1 (glyph geometry in `verbatim/icons_phosphor.py`) | interface icons | MIT (© 2023 Phosphor Icons) |
| Instrument Serif, Hanken Grotesk, JetBrains Mono, Mukta (`assets/fonts`, licence texts alongside) | interface typefaces | SIL Open Font License 1.1 |
| LatentSync 1.6 (ByteDance) — Cloud GPU server only, installed by `cloud/install.sh`, not bundled in the app | lip-sync in Video Localise | Apache-2.0 |
| `tests/data/jfk.flac` (from openai/whisper tests) | test fixture | MIT |

No code from MacWhisper, TurboScribe, Fireflies, Cockatoo or ElevenLabs' proprietary services is included;
those products were studied only for publicly documented features and workflows.
