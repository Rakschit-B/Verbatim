# VERBATIM accuracy: test report, research and method

*VERBATIM 2.0–2.1 · tested 16 Oct 2026 (2.1 also verified on macOS 27 Apple Silicon and Windows-x64 under Wine 11)*

## 1. What was wrong in VERBATIM 1.x (found by testing)

| # | Problem in v1 | Evidence | Fix in v2 |
|---|---|---|---|
| 1 | **Custom vocabulary only applied to the first 30 s of each file.** With `condition_on_previous_text=False`, mlx-whisper's `transcribe()` sets `prompt_reset_since` after every window, so the `initial_prompt` is never sent again. | mlx-whisper 0.4.3 source, `transcribe.py` L532-534 | Each speech window is decoded on its own with the glossary prompt (unit-tested). |
| 2 | **`temperature=0` only.** Whisper's loop and garbage detectors (`compression_ratio_threshold`, `logprob_threshold`) work by re-decoding at a higher temperature. With no fallback temperatures, they did nothing. | openai-whisper / mlx-whisper decoding logic | Full fallback schedule (0, 0.2 … 1.0). |
| 3 | **No voice-activity detection.** Fixed 30-s windows that start mid-word made Whisper skip whole windows. | Test A below: 97 and 108 words missing in 2 of 4 earnings calls | Silero VAD v5. Windows are cut at pauses (the quietest point) and never mid-word. |
| 4 | No word timestamps, so no confidence scores. Subtitle cues ran up to 30 s with no line rules. | v1 code | Word-level timing and confidence. Cues are ≤42 characters × 2 lines and ≤7 s. |
| 5 | Master Excel was overwritten by each batch, so history and earlier failures were lost. | v1 `master_export` | Cumulative SQLite ledger → 7-sheet workbook. Review status is preserved. |
| 6 | Needed Homebrew FFmpeg and ffprobe, so a DMG would fail on any other Mac. | v1 build script | Bundled FFmpeg fallback (imageio-ffmpeg). ffprobe is no longer needed. |
| 7 | Updater ran `pip --upgrade` on unpinned packages, so a breaking release of a dependency could break the app. | v1 `UPDATE VERBATIM.command` | Versioned releases, SHA-256 and Ed25519 checks, rollback, and pinned ranges. |
| 8 | Only 6 languages. The CSV had no BOM, so Excel garbled Hindi text. | v1 code | 25 languages listed (99 available in Whisper). UTF-8-BOM CSV. |

## 2. Benchmark

**Test set:** the first 5 minutes of 4 real corporate earnings calls from **Earnings-21** (Rev.com, CC-BY-SA). They are entity-dense business speech with multiple speakers, one recorded at 11 kHz telephone quality, ≈3,400 reference words. The set also includes JFK and 3 LibriSpeech clips (clean read speech). Scoring uses word error rate (WER) after Open-ASR-Leaderboard-style normalisation (case, punctuation, numbers, fillers).
**Hardware:** 2-core cloud CPU, ONNX builds of the same model weights. MLX (Apple GPU) could not be run here, so the Mac path is covered by wiring tests and by `benchmarks/run_benchmark.py`, which runs on your Mac.

| Config | Overall WER | Earnings calls | Clean speech |
|---|---|---|---|
| A · v1-style: Whisper turbo, fixed 30-s windows, no VAD | **10.28 %** | 10.49 % | 0–6.3 % |
| B · v2: Whisper turbo + VAD + level normalisation | 4.38 % | 4.42 % | 0–6.3 % |
| C · v2: Parakeet TDT v2 + VAD + normalisation | 4.02 % | 4.08 % | 0–4.2 % |
| C2 · Parakeet, no audio prep | 3.94 % | 3.99 % | same |
| C3 · Parakeet, "clean" (denoise) prep | 4.11 % | 4.17 % | same |
| R · Parakeet, **AI "Restore audio"** (GTCRN, v2.1) | 4.43 % | 4.50 % | 0–2.1 % |
| **D · Parakeet + VAD + vocabulary (1,000-term noisy glossary)** | **3.82 %** | 3.88 % | same |

**Takeaways**

- v2's pipeline cuts errors by **~60 %** against v1-style decoding (10.3 % → 3.8–4.4 %). Most of the gain is from VAD, which prevents dropped windows.
- Denoising made things slightly worse on this audio, which matches published findings that Whisper-family models are trained on raw audio. "Clean" stays opt-in.
- The first version of the vocabulary corrector **made accuracy worse** (it turned "at" into "A&T", "being" into "Boeing" and "sell" into "Shell"). It was rebuilt with these safeguards:
  - only words the engine was unsure of are touched;
  - common English words are never touched;
  - the word count never changes;
  - possessives are kept.

  After the rebuild, all 9 of its corrections on the test set were right ("Maholland"→"Mulholland", "Renal"→"Reynal", "Lumkin"→"Lumpkin" and others).
- Some remaining "errors" are mistakes in the reference transcript itself, or compound-word spelling ("cashflow" vs "cash flow"). True accuracy is therefore a little higher than these numbers.

### Review Queue effectiveness (config F: Parakeet + Whisper cross-check)

| Review strictness | Words highlighted | Real errors caught | WER after a reviewer checks the highlights |
|---|---|---|---|
| Light (confidence < 0.5) + disagreements | 7.3 % | 32 % | 2.78 % |
| **Standard (< 0.8) + disagreements — default** | 9.1 % | 41 % | **2.40 %** |
| Thorough (< 0.95) + disagreements | 12.6 % | 55 % | **1.83 %** |

Two-engine agreement on these calls was 96.8–97.4 %, which tracks the measured accuracy closely. The app shows agreement in the Files sheet as a no-reference accuracy estimate.

Local speaker labels on the 3-speaker ZAGG call: 3 speakers found, and turn boundaries were within ~0.3 s of the reference RTTM at threshold 0.9.

## 3. So, can it do 99 %?

| Recording type | Expected raw accuracy | With vocabulary + Thorough review |
|---|---|---|
| Clean interview, presenter to camera, single good mic | 98–100 % (measured 96–100 % on clean clips) | **≥ 99 %** |
| Corporate call / webinar, several speakers, jargon | 95–97 % (measured 96.1–96.2 %) | ~98–98.5 % measured; 99 % needs the reviewer to also skim non-flagged text |
| Noisy, overlapping or heavily accented, Hindi/Hinglish | 85–95 % | Use ElevenLabs Scribe v2 (best published multilingual WER) plus Thorough review |

**99 % is reachable, but by workflow, not by any single model.** The steps are:
1. Pick the right engine: Parakeet or Whisper large-v3 locally, or Scribe v2 for the hardest audio.
2. Load the client glossary.
3. Use Thorough review.
4. Work the Review Queue to zero.
5. Verify on your own material with `benchmarks/run_benchmark.py --folder <your verified samples>`.

## 4. What was learned from each source

**Open-source repositories (code patterns adopted, licences respected)**
- **WhisperX** (m-bain): VAD "cut & merge" windows, batched per-window decoding, avoiding error propagation between windows.
- **faster-whisper** (SYSTRAN): Silero VAD gating, `hotwords`, `hallucination_silence_threshold`, beam search 5, temperature fallback (used in the Windows engine).
- **openai/whisper and mlx-examples/whisper**: prompt semantics (the v1 bug), word timestamps, compression-ratio heuristics; the prompting guide's tip that a disfluent prompt keeps "um/uh" (*Exact verbatim* style).
- **Silero VAD**: v5 ONNX model and hysteresis algorithm (re-implemented in NumPy, no PyTorch).
- **sherpa-onnx** (k2-fsa): portable Parakeet and diarisation with no Hugging Face token.
- **NVIDIA Parakeet TDT**: #7 on the Open ASR Leaderboard (6.05 % mean WER vs 7.44 % for Whisper large-v3). It is fast and gives per-token log-probabilities.
- **pyannote segmentation-3.0 + TitaNet**: speaker turns.
- **stable-ts / whisper-timestamped**: word-confidence-driven review, subtitle regrouping rules.
- **Earnings-21 and the HF Open ASR Leaderboard**: evaluation method and text normaliser rules (years, currency, ordinals, fillers).
- **ROVER** (NIST system combination): the two-engine cross-check and optional fusion.

**ElevenLabs (API reference, elevenlabs-python SDK, elevenlabs/skills `speech-to-text`, elevenlabs-examples)**
- Scribe v2 is #6 on the leaderboard snapshot (5.83 % mean WER), with 90+ languages, up to 32 speakers and per-word `logprob`. VERBATIM integrates it as an opt-in engine with these settings:
  - `keyterms` carry the glossary (max 1,000 terms, under 50 characters and at most 5 words each; sanitised);
  - `diarize` and `num_speakers` handle speakers;
  - `timestamps_granularity=word` gives word timing;
  - `tag_audio_events` marks laughter and applause;
  - `temperature=0` with a fixed `seed` keeps runs repeatable;
  - `no_verbatim` maps to the Clean/Exact style switch;
  - audio is sent as lossless FLAC upload, with retry on 429/5xx;
  - the `request-id` is captured;
  - the key is kept in the system keychain.
- Ideas noted for later: `entity_detection`/`entity_redaction` (PII redaction for client data), `use_multi_channel` (one speaker per mic track), and webhooks for very long files.

**MacWhisper**: batch queue with drag-and-drop folders, multiple export formats (SRT/VTT/TXT/DOCX/MD), choice of Whisper or Parakeet models, a speaker-recognition toggle, and fully local processing.
**TurboScribe**: unlimited batch uploads with per-file status, speaker recognition, export to DOCX/PDF/SRT/VTT, and its noise caveat. VERBATIM's "clean" prep is opt-in for the same reason.
**Fireflies**: searchable transcripts and keyword tracking. In VERBATIM this became the Master Transcript sheet: every segment of every file in one filterable table.
**Cockatoo**: its accuracy claim (99.8 %) is marketing, not a benchmark. VERBATIM ships a measurement tool instead of a claim. Its subtitle-first workflow informed the SRT/VTT rules.

No proprietary code from any of these products is included. Only publicly documented features and workflows were studied.

## 5. Not yet verified

- MLX Whisper inference speed and accuracy on an M-series Mac. Run `python benchmarks/run_benchmark.py --earnings21` on the Mac.
- Fusion mode ("let the second engine repair words") was not testable here, because the ONNX Whisper build gives no confidences. It stays off by default.
- Hindi/Hinglish accuracy, because no verified Hindi references were available. Test with your own clips.
- The signed and notarised DMG requires an Apple Developer ID.
