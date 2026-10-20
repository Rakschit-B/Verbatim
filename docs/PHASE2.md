# VERBATIM 3.1 — Phase 2 (Transcribe Pro)

## 1. Speaker library: name a voice once
- Every diarised speaker gets a voice fingerprint (NVIDIA TitaNet, from up to 30 s of their speech), stored
  in the transcript JSON. Fingerprints are numbers, not audio, and stay on the computer (`speakers.json`).
- In the transcript editor, click a speaker label → type the name → keep "Remember this voice". New files
  label that voice automatically. Matching is one-to-one per file; anyone unknown stays "Speaker N".
- Calibration (4 different calls, 9 speakers): same voice 0.85–0.96 cosine, different voices ≤ 0.42.
  Threshold 0.60. End-to-end test: speaker named in part A of a call was recognised in part B (0.91);
  the new speaker in part B stayed "Speaker 2"; the operator (absent from B) was not wrongly assigned.
- Limits: the same person on a very different microphone/room can score lower; name them again from
  that file to add a second sample (up to 24 samples per person are kept).
- Files transcribed before 3.1 have no fingerprints: rename works, "Remember this voice" needs a re-run.

## 2. Projects
- Each project = name + output folder (own Master Excel Log) + own vocabulary. Switch from the Files
  header or the Projects page. "No project" restores the general vocabulary and folder.
- Removing a project only removes it from the list; files stay on disk.

## 3. Transcript editor
- Open from the file table (double-click a finished file or ⋯ › Edit transcript) or the Files page.
- Uncertain words are highlighted. Click a time to hear that line (system audio player — no extra
  components), Space plays/stops, the list follows playback.
- Double-click text to edit; speaker column to reassign a line; speaker chips to rename everywhere.
- Save rewrites every export (TXT, Word, SRT, VTT, CSV, Markdown, JSON), keeps the timing of unchanged
  words, logs each change in the Master Excel Log (Corrections sheet) and marks review items in the
  edited lines as "Corrected".

## 4. Precise word timing (optional, Settings › Advanced)
- WhisperX-style CTC forced alignment, without PyTorch: Meta's Omnilingual ASR 300M CTC model
  (1,600+ languages incl. Hindi, Apache-2.0) via ONNX Runtime + a NumPy Viterbi aligner.
- Applies to Whisper output (Hindi and other languages). English via Parakeet already has acoustic timings.
- Measured on a 5-minute earnings call against Parakeet's acoustic timings (930 words):

| Word timings | median start error | 90th pct | within 100 ms |
|---|---|---|---|
| Spread evenly in each line (no word times) | 432 ms | 1,071 ms | 13 % |
| ±150 ms jitter (typical attention-based estimates) | 99 ms | 227 ms | 51 % |
| After alignment (either starting point) | **50 ms** | **130 ms** | **81 %** |

- Cost: about 1 s of processing per 5 s of audio on the 2-core test machine (much faster on M-series);
  that is why it is off by default. 330 MB model, downloaded once when first used.
