# VERBATIM 3.6 — "Score"

© 2026 Infinite Story LLP. Proprietary.

## 1 · The new design language: Score

VERBATIM now looks like a film score crossed with an editorial broadsheet. It is built for people who cut, voice
and score films.

| Element | What it is |
|---|---|
| **Grounds** | *Paper* (warm bone `#F2EEE6`) and *Ink* (warm black `#0F0E0C`). Separation comes from hairline rules, not drop shadows. Corners are 4–6 px. |
| **Broadcast colours** | Each module has its own channel colour, and the whole interface re-tints when you switch: **01 Transcribe = Tally** (the red recording light), **02 Voice = Ultramarine**, **03 Music = Saffron**, **04 Video = Jade**. |
| **Type** | *Instrument Serif* for display: module numerals, page titles and italic taglines. *Hanken Grotesk* for the interface. *JetBrains Mono* for timecodes and kicker labels. *Mukta* for Devanagari. All are SIL OFL and bundled, so the app looks identical offline on every Mac and PC. |
| **The Rail** | A dark spine on the left. Shows the big serif numerals 01–04 with a playhead marker on the active module, a vertical book-spine imprint ("INFINITE STORY — VERBATIM 3.6"), and utilities: updates, theme, activity, settings and you. |
| **Masthead** | A mono kicker ("MODULE 02 / 04 · VOICE") above a serif title and an italic tagline in the module colour, e.g. "Voice — *translate, direct and perform.*" Transcribe's chapters (Queue · Library · Projects · Speakers · Vocabulary · Output) sit on the right. |
| **The Ruler** (signature pattern) | A timecode ruler under every masthead. Its playhead, in the module colour, parks at the golden section and tracks real progress while a batch or localisation runs. |
| **Crop marks & speech envelope** | Printer's crop marks frame the drop zones. A hairline speech-envelope bar graph, "played" up to the playhead, is VERBATIM's waveform signature. |
| **Icons** | Phosphor (MIT): light weight on the rail, regular in buttons, fill for the active utility. |
| **Primary actions** | Flat slabs in the module colour ("● Start transcription", "Localise the film", "Create music"). They invert to ink on hover. |

## 2 · Module 04 — Video Localise (Phase 5)

**One film in; a dubbed, subtitled and optionally lip-synced film out for every language you tick.**

1. **Transcribe** with speakers. Earlier runs are reused through the Master Log.
2. **Keep each speaker's own voice.** VERBATIM learns every speaker from their clearest 45 seconds in the film, with music removed. One rights confirmation is written to the Consent register. Or choose *Studio voices*.
3. For every language:
   - translate (TranslateGemma offline, Claude or OPUS-MT);
   - direct the performance (emotion, strength and emphasis per line);
   - voice it;
   - keep the original music and effects (UVR);
   - mux the dubbed film.
4. **Subtitles:** a soft track inside the MP4 (language-tagged) and/or burned into the picture.
5. **Lip-sync (beta, Cloud GPU):** LatentSync 1.6 re-times every mouth to the new language, then the full dubbed mix is laid back over the picture.
6. Every language is a normal Voice Studio job, so you can re-take any line and re-render.

If a language has no cloning engine on this computer yet, VERBATIM switches that language to studio voices and says so.

## 3 · Optional Cloud GPU mode

`engine_host/server.py` runs the heavy engines on your own NVIDIA server. Setup is in `cloud/README.md`: `install.sh` or the Dockerfile, a token, and HTTPS through Caddy or an SSH tunnel.

- **What can run there:** music, voice tone and singing conversion, lip-sync and the quality scorers. You choose each one in Settings › Cloud GPU.
- **What changes in the app:** nothing. The engines are called through the same interface as on your computer, so every feature works either way.
- **What travels:** only the files a job needs. They are deleted on the server when the job returns.

## 4 · Music: "Sing it in my voice"

Pick any take and press **Sing it in my voice…**. VERBATIM does three things:

1. separates the vocals;
2. moves the singer's tone colour to one of your consented Voice Lab voices with OpenVoice V2 (MIT), keeping the melody, timing and phrasing;
3. level-matches, remixes, masters, and writes a WAV and an MP3 next to the take.

*Likeness* sets how close the result sits to your voice.

## 5 · OmniVoice step-down (licence hygiene)

OmniVoice's weights are non-commercial (CC-BY-NC), so it is being retired step by step:

- **3.6:**
  - it is no longer used by "Best available", the Voice Lab pack list or the cloud server;
  - its designed voices are hidden;
  - the clone engine appears only when *Settings › Legacy engines* is switched on;
  - cloned voices that cannot speak a language now fall back to OpenVoice tone colour on a studio performance (MIT);
  - jobs saved with old voice ids still play.
- **Next builds:** remove the legacy option and the omnivoice package from the voice runtime.

## 6 · Fixes

- **Mac compatibility:** 3.5.x bundled Qt for Python 6.12. Its binaries require macOS 26 (Tahoe), so VERBATIM could not open on Macs running macOS 15 or earlier. This was the "won't load on the other MacBook Pro" issue. 3.6 bundles a Qt for Python build that runs on macOS 14 and later, and the Info.plist says so.
- **Crash on quit or while updating:** "QThread: Destroyed while thread is still running" is fixed. Every background job is now owned by one worker registry and is shut down cleanly.
- **Helper:** `If VERBATIM won't open.command` on the DMG clears the download quarantine that macOS adds to apps copied from another Mac or the internet.
- **Labels:** labels containing "&" no longer show a stray underscore.
