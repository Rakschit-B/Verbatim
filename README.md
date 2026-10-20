# VERBATIM 3.3 — by Infinite Story

**Every word. Every moment.** VERBATIM 3.0 introduces the new interface and three modules:

| Module | Status |
|---|---|
| **01 Transcribe** — accurate multilingual transcription, speaker identification and batch exports | Available |
| **02 Voice Studio** — translate dialogue, multilingual voiceovers (stock voices), consent register; cloning next | Available (part 1) |
| **03 Video Localise** — translate videos, preserve speaker voices, synchronise lip movements | Coming soon |

The 3.0 window: left navigation (Transcribe, Files, Projects, Speakers, Vocabulary, Output, Activity Log,
Settings), a drop zone, a file table with thumbnails, duration, language, status and progress, and a
settings panel with Settings / Speakers / Vocabulary / Output tabs. Light and dark themes.

**New in 3.1 (Phase 2 — Transcribe Pro):** speaker library (name a voice once, recognised in later
files), projects (per-client vocabulary, output folder and Master Log), a transcript editor (listen,
correct, rename speakers, every export rewritten) and optional precise word timing for Whisper
languages. Details and measurements: [docs/PHASE2.md](docs/PHASE2.md).

**New in 3.2 (Phase 3 — Voice Studio part 1):** translation (offline or Claude API), Hindi/English and
6 more languages of local voiceover with automatic timing fit, dubbed MP4 + translated subtitles,
and the voice consent register. Details: [docs/PHASE3.md](docs/PHASE3.md).

**New in 3.3:** Supertonic 3 voices (10 natural voices × 31 languages), offline TranslateGemma translation
(55 languages), Claude translation with styles + native-speaker polish, meaning check and auto-shortening.

Accurate, private, batch transcription of videos and audio for Mac (Apple Silicon) and Windows, with a
full audit trail: every file, every word, every correction and every doubt is logged in one
**Master Excel Transcription Log**.

## What it does

| | |
|---|---|
| **Batch** | Drop any number of videos/audio files or whole folders (MP4, MOV, MKV, AVI, MP3, WAV, M4A, FLAC…). Failures never stop the batch; re-running skips finished files (resume). Original file names are kept everywhere. |
| **Engines** | Whisper large-v3 / turbo (MLX on the Mac GPU, faster-whisper on Windows), NVIDIA Parakeet TDT v2/v3 (ONNX, best local English), ElevenLabs Scribe v2 (optional cloud, highest accuracy + speakers). |
| **Accuracy layer** | Silero VAD speech gating · per-window vocabulary prompting · temperature fallback · hallucination & repetition-loop guard · missed-speech detector · audited vocabulary auto-correction · two-engine cross-check with disagreement list · per-word confidence. |
| **Speakers** | Local diarisation (pyannote segmentation 3.0 + TitaNet, no account needed) or ElevenLabs diarisation (up to 32 speakers). |
| **Exports per file** | TXT (timestamped + dialogue-only), SRT, VTT (broadcast line rules), CSV, JSON (word-level), DOCX (uncertain words highlighted), Markdown, processing log. |
| **Master Excel Log** | Dashboard · Files · Master Transcript · Review Queue (with Status you can edit) · Corrections · Batches · Errors. Cumulative across every batch. |
| **Updates** | In-app update banner, `Update VERBATIM` script, and an optional weekly scheduled update. Downloads are HTTPS-only, SHA-256 verified and (when configured) Ed25519-signature verified; the previous version is kept for rollback. |

## The honest truth about "99 % accuracy"

No speech-to-text engine reaches 99 % word accuracy on *every* recording. Best published systems
average 94–95 % across the Hugging Face Open ASR Leaderboard (WER 5.3–7.4 %); on clean, single-speaker
audio they reach 98–99 %. VERBATIM's route to **99 %+ delivered accuracy** is therefore:

1. use the most accurate engine for the language and setting,
2. remove the systematic errors (hallucinations on silence, dropped windows, misspelt names),
3. **tell you exactly where the remaining errors are likely to be** (low-confidence words, engine
   disagreements, speech with no words) so a reviewer checks minutes, not hours.

Measured on real corporate earnings calls (Earnings-21) + clean speech — full report in
[`docs/ACCURACY.md`](docs/ACCURACY.md):

| | Word error rate | Word accuracy |
|---|---|---|
| v1-style decoding (no VAD, fixed windows) | 10.28 % | 89.7 % |
| **v2 (VAD + Parakeet/Whisper + vocabulary)** | **3.82 %** | **96.2 %** |
| v2 + reviewer checks the highlighted words (Thorough) | 1.83 % | 98.2 % |
| Clean single-speaker speech, raw | 0–4 % | 96–100 % |

## Install (no Python, no Terminal)

The installers carry their own Python 3.12 and every library, so **no Python install is needed** (and
Python 3.15 on your machine is fine to keep — VERBATIM never uses it).

**Mac (Apple Silicon M1–M4, macOS 14+):** open `VERBATIM-2.1.0-mac-arm64.dmg`, drag VERBATIM onto Applications.
First launch of this not-yet-notarised build: macOS 15+/26/27 → System Settings › Privacy & Security ›
**Open Anyway**; macOS 14 → right-click › Open.

**Windows 10/11 (64-bit):** run `VERBATIM-2.1.0-Setup.exe` (installs per-user, no admin). If SmartScreen
says "Windows protected your PC": **More info › Run anyway**. Tick "Check for updates every week".

Models download once on first use (Whisper large-v3 ≈ 3 GB, Parakeet ≈ 0.6 GB); after that everything
local runs offline.

## What VERBATIM learned from TurboScribe

| TurboScribe | VERBATIM 2.1 |
|---|---|
| Modes Cheetah / Dolphin / Whale (Whisper base / small / large-v2) | Fast / Balanced / Most accurate presets, incl. **Whisper large-v2** (TurboScribe's Whale model) and large-v3 |
| Uses file name / title as context for names | **File-name hints**: names in the file name (e.g. `EXL_TownHall.mp4`) bias the decoder and the spelling corrector |
| "Restore audio" — AI noise removal, only for poor files | **Restore audio (AI)** option (GTCRN neural enhancement). Benchmark: slightly *worse* on clean calls (4.43 % vs 4.02 % WER), so it is opt-in exactly as TurboScribe advises |
| Speaker recognition, 2–8 speakers or auto | Local speaker labels (auto or 1–32) or ElevenLabs diarisation |
| Readable paragraph transcripts; export TXT/DOCX/PDF/SRT/VTT/CSV with timestamp & speaker options | **Paragraph exports** with Timestamps / Speaker names toggles; TXT, DOCX, MD, SRT, VTT, CSV, JSON (PDF: print the DOCX) |
| Translation of transcripts | **English translation** of non-English videos (Whisper speech translation) → `(English translation).txt` + `(English).srt` |
| 50-file bulk upload, 10 h / 5 GB per file | Unlimited local batch, any length, resumable |

## Build the installers

| Where | How |
|---|---|
| **GitHub (recommended — builds both DMG and EXE in the cloud)** | Push this folder to a GitHub repository, then push a tag: `git tag v2.0.0 && git push --tags`. The workflow in `.github/workflows/release.yml` tests, builds the DMG on an Apple Silicon runner and the Setup.exe on Windows, and publishes a Release with `latest.json` (the update channel). |
| **On your Mac** | Double-click `scripts/mac/BUILD MAC DMG.command` (needs Python 3.12). Output: `dist/VERBATIM-<ver>-mac-arm64.dmg`. |
| **On a Windows PC** | Double-click `scripts\windows\BUILD WINDOWS EXE.bat` (needs Python 3.12 + Inno Setup 6). Output: `dist\VERBATIM-<ver>-Setup.exe`. |

The GitHub build automatically points the in-app updater at your repository's latest release, so every
installed copy finds new versions by itself. (For local builds, edit `update_manifest_url` in
`verbatim/settings.py` to `https://github.com/<you>/<repo>/releases/latest/download/latest.json`.)

**Shipping an update:** bump `__version__` in `verbatim/__init__.py`, commit, `git tag v2.0.1 && git push --tags`.
Installed apps see the banner on next launch, or install it automatically via the weekly scheduled task.

Optional hardening: run `python scripts/release/generate_signing_key.py` once, commit the public key it
writes to `assets/`, and store the private key as the `VERBATIM_SIGNING_KEY` GitHub secret — from then on
installed apps refuse any update that isn't signed by you. Add Apple Developer ID secrets to get a
signed, notarised DMG with no Gatekeeper warning.

## Command line

```
VERBATIM --cli transcribe "~/Videos/Client shoot" --engine whisper --language en --vocab terms.txt --diarize
VERBATIM --cli accuracy verified.txt "Interview 01.json" --xlsx errors.xlsx
VERBATIM --cli rebuild-log
VERBATIM --update            # check + install;  --check-only, --auto (scheduled)
python benchmarks/run_benchmark.py --folder "verified samples"   # your own WER test
```
(On Mac the binary is `/Applications/VERBATIM.app/Contents/MacOS/VERBATIM`; on Windows use `verbatim-cli.exe`.)

## Run from source

```
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python run.py
```
Tests: `pip install -r requirements-dev.txt && pytest -q`

## Privacy

Local engines never upload audio. ElevenLabs Scribe is opt-in, asks for confirmation before each cloud
batch, and stores its API key in the macOS Keychain / Windows Credential Manager.

## Licence

VERBATIM source: MIT (see `LICENSE`). Third-party models and libraries keep their own licences — see
`THIRD_PARTY_NOTICES.md` before redistributing commercially.
