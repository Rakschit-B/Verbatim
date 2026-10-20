# VERBATIM 3.4 — Voice, emotion, music (Infinite Story LLP)

## What changed and why
Feedback on 3.3: the voiceover was clear but not human — flat pitch, no emotion on the words that matter.
Root cause: Supertonic (3.3's engine) has no emotion or prosody control; it reads every line the same way.
3.4 adds a *performance layer* and engines that can act on it.

### 1. Performance direction (every line)
Each line now carries an emotion (neutral, warm, inspiring, calm, joyful, excited, serious, sad, urgent,
whisper), a strength, and the words to stress. "Direct the performance" fills it in — Claude reads the whole
script and builds an arc (with a Claude key), or built-in rules do it offline. Double-click a line to change it.
Every engine turns the direction into its own controls (direction.py):
- Chatterbox: emotion exaggeration + sampling, per line
- ElevenLabs: audio tags ([warmly], [excited], [whispers]…), CAPS on stressed words, lower stability
- Azure: SSML speaking style + style degree, <emphasis>, pitch/rate prosody
- all engines: pace and breathing room per emotion

### 2. Voices
| Voices | Engine | Languages | Emotion | Offline | Licence |
|---|---|---|---|---|---|
| Studio voices (10) | Supertonic 3 | 31 | pace only | yes (bundled) | OpenRAIL-M |
| Expressive voices (10) + your voices | Chatterbox Multilingual | 23 incl. Hindi, Hebrew | yes | yes (1.6 GB pack) | MIT |
| Your voices, English | ZipVoice | en, zh | from the reference | yes (bundled) | Apache-2.0 |
| Kokoro | Kokoro v1.0 | en, zh, hi, ja, es, fr, it, pt | no | yes (bundled) | Apache-2.0 |
| ElevenLabs (optional) | eleven_v3 / v4 | 70–90+ | yes (audio tags) | no — your key | ElevenLabs terms |
| Azure Neural (optional) | Azure AI Speech | 140+ incl. Bengali, Hebrew | yes (styles) | no — your key | Microsoft terms |

### 3. Voice Lab
Create a voice from any recording: music under the voice is removed (UVR MDX-Net), the cleanest 6–12 s become
the reference, the words are transcribed, and a consent-register entry is recorded. Voices can be exported as a
private `.verbatimvoices` pack and imported on another computer. Your three Suno narrations ship as
"Rakschit voices.verbatimvoices" (not inside the public installer).

### 4. Music bed
Add a track: full in the intro, ducked under speech (look-ahead so the dip lands before the word), swells in
pauses over 1.2 s, lifted or lowered per line by its emotion, swells and fades after the last line; loudness
normalised to about −16 LUFS with a −1 dBFS ceiling. Dubs can also keep the original music & effects (the original
voice is removed) instead of playing it ducked underneath.

### 5. Script voiceovers
"New from script…" voices a written script with no video — sentences follow on with natural pauses, longer
between paragraphs — optionally translated first. Output: voice WAV, voice + music WAV/MP3, SRT/VTT.

## Research notes (public products, docs and official SDKs)
- Murf: per-block pitch/speed/emphasis/pause controls, voice styles, pronunciation library, "Say it my way"
  (record a reading so the AI copies your delivery). → VERBATIM: per-line direction + Voice Lab references.
- ElevenLabs: v3/v4 audio tags inline in the text; stability (lower = more emotional range), similarity, style;
  instant voice clone from a minute of clean audio; CAPS and ellipses as emphasis/pause cues; official JS/Swift
  SDKs and MCP server are thin clients of the same REST API. → VERBATIM calls the REST API directly.
- Azure Speech: SSML `mstts:express-as` styles with `styledegree`, `prosody` pitch/rate/contour, `emphasis`;
  REST endpoint `https://<region>.tts.speech.microsoft.com/cognitiveservices/v1`.
- Coqui TTS: code MPL-2.0, but XTTS-v2 weights are under the Coqui Public Model Licence (non-commercial) — not
  used. Kyutai Pocket TTS ONNX export and k2-fsa OmniVoice weights are non-commercial — not used.
- Ming-3.0-TTS (MIT), Marco-Voice (Apache-2.0) and OpenVoice V2 (MIT) are candidates for a later phase (GPU/PyTorch).
- The Buster wiki page is a CAPTCHA-solver configuration guide — not relevant and not used.
- No proprietary app or service was decompiled or reverse-engineered.

## Roadmap
- Phase 4 — Video Localise: lip-sync, on-screen text, speaker-matched dubbing using the voices above.
- Phase 5 — Music creation: ACE-Step 1.5 (open licence, < 4 GB VRAM, lyrics + vocals, cover/repaint/extend,
  style training from a few songs) for original beds and songs; Stable Audio 3 for long instrumental beds and
  sound design (check its revenue threshold). Music that follows the script's emotion arc, generated to length.
- Ongoing — replace third-party models with Infinite Story fine-tuned models trained on licensed and owned data.
