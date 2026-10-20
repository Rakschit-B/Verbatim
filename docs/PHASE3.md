# VERBATIM 3.2 — Phase 3 (Voice Studio, part 1)

Module **02 Voice Studio** is live: transcript → translation → timed voiceover → exports.

## Translation (choose per job)
- **Offline — free & private:** OPUS-MT models (Argos Translate packages) run with CTranslate2 +
  SentencePiece. Downloaded once per language pair (~100 MB); pairs without a direct model pivot via
  English. Vocabulary terms are protected (kept exactly as written); "a => b" rules are applied.
- **Claude API:** Sonnet 5.5 (recommended), Opus 5.5 or Haiku 5.5, with your API key (system keychain).
  Translates in numbered batches of 40 lines with the previous lines as context, keeps names and your
  vocabulary, writes numbers the way a voice artist reads them, uses everyday spoken Hindi, and keeps
  each line about as long as the original so it fits the time slot. Dropped lines are retried.
- Lines you edit are kept when you translate again (tick "Keep lines I edited").
- Timestamps never change; long transcript paragraphs are split at sentence ends for dubbing.

## Voiceover (stock voices — no cloning)
- Kokoro v1.0 (Apache-2.0) via sherpa-onnx, offline. Voices: English (9), Hindi (4), Spanish, French,
  Italian, Portuguese, Japanese, Chinese. Other languages get translation + subtitles only.
- Pick a voice per speaker (▶ plays a sample) and a pace (0.9× / 1.0× / 1.1×).
- **Timing fit:** each line is spoken in its slot (until the next line starts). If it is longer it is
  re-spoken faster, up to ×1.30. Lines that still overrun are flagged "too long" (orange) — shorten the
  translation and generate again. Voices never overlap.

## Exports ("<output folder>/<file>/Voice Studio/")
voice-only WAV · voiceover mixed over the original (original ducked under the voice) · dubbed MP4
(original picture, new sound) · translated SRT / VTT · translation TXT · timing report CSV · the job
file (.voice.json) for reopening and editing. Each job is listed on the Master Excel Log "Voice Studio"
sheet.

## Voice consent register
Required before any voice cloning (Phase 4). Records person, signed form (copied into VERBATIM's data
folder with its SHA-256), what it covers, signed/expiry dates, project; can be revoked. Listed on the
Master Excel Log "Voice Consent" sheet. Stock voices need no consent.

## Tested here
- Kokoro Hindi: an independent speech recogniser (Omnilingual CTC) recovered the Hindi sentence almost
  word for word from the generated audio.
- 2½-minute earnings-call excerpt → Hindi (hand translation for the test): 19 lines voiced, 16 fit their
  slot (9 as-is, 5 sped up ≤ ×1.28, 2 shifted < 1 s), 3 flagged too long; MP4, mix, WAV and subtitles
  written correctly. Rendering took ~2 min on the 2-core test machine (much faster on M-series).
- Claude and offline translation are covered by tests with simulated responses; live runs need your
  API key / the model download (the build machine cannot reach those servers).
