# VERBATIM 3.7 — Studio

© 2026 Infinite Story LLP. Internal experiment, not a public product.

## The new look

- **Two themes.** *Studio* is dark and is the default. *Clean* is light. Switch with the sun/moon button in the sidebar, or in Settings › Appearance.
- **Sidebar.** Home, then **Create**: Transcribe, Voiceover, Voice Studio, Music, Video Localise, Feature Film. Then **Yours**: Library, Activity, Settings. Jobs that are running show their progress bars at the bottom of the sidebar.
- **Top bar.** The page title, a library search and **Downloads**. Downloads lists every download, render, song and film with a progress bar and the time left. Finished jobs get ⬇ buttons.
- **Look and feel.**
  - *Type:* Manrope.
  - *Accent:* the Infinite Story gradient (violet → magenta → coral).
  - *Icons:* Phosphor.
  - *Covers:* gradient artwork on every item, rounded cards.
- **Home.** Six "Create" tiles, plus *Recent* items you can play and download.
- **Library.** Everything you made: transcripts, voiceovers, songs, videos and feature films. Filter it with chips. Each item has ▶ Play, a **Download** menu with every file (MP3, WAV, MP4, SRT, DOCX…) and Show in folder.
- **Transcribe queue.** Each row now has ▶ (play the original) and ⬇ (Word, text, subtitles, CSV, JSON).

## Player bar (every module)

The player bar runs along the bottom and plays anything in VERBATIM: songs, voiceovers, previews, editor lines, films and actor samples. It has:

- previous / next;
- back 10 s / forward 10 s;
- play / pause;
- a scrubbable timeline with elapsed and total time;
- speed (0.75–2×) and volume / mute;
- download and show in folder.

**Video** plays in a picture-in-picture pane; *Open large* opens a big window. **Shortcuts:** Ctrl+Space (play/pause) and Ctrl+← / → (±10 s).

## Voiceover Creator

1. Paste a script and choose the language, voice and style.
2. You get two results side by side, each with ▶, ⬇ MP3 and ⬇ WAV:
   - **Voice only**;
   - **Voice + music** — the music dips under every word and swells in the pauses.

**Styles.** Seven are built in: Warm narrator, Corporate film, Energetic advert, Documentary, Cinematic trailer, Storyteller, and News & radio. **Learn a style from audio…** creates new styles from reference recordings. VERBATIM measures pace, melody, pauses and tone colour, and saves the result as a reusable style (marked ✦).

**Music** comes from one of three places:
- *Compose a bed* — instant, offline, original. Six moods, including *Indian warmth*.
- *Use my track*.
- *From my songs* — any Music take.

## Music (rebuilt)

- **Sound.** Describe genre, mood, instruments and production, or press *Inspire me* (299 prompts).
- **Lyrics & singers.** The lyrics are a song sheet: one card per section (Verse, Pre-Chorus, Chorus, Bridge, Hook, Rap, Outro…). Each card says who sings it:
  - Male, Female, or Duet (male + female);
  - Chorus · 3 singers, Chorus · 6 singers, or Choir · 12+;
  - Instrumental.
- **Write lyrics with AI.** *Offline* uses Gemma 3 4B on this computer through llama.cpp (one-time 2.5 GB download). *Online* uses Claude. Either way, the AI keeps your section and singer plan. You can also *Paste lyrics* with headers like `[Chorus | Duet]`.
- **Enforce the singers (casting).** After generation, VERBATIM does five things:
  1. separates the vocal;
  2. finds each section (lyrics alignment, falling back to vocal energy);
  3. re-voices each part to its cast singer (OpenVoice tone colour, when that engine is installed);
  4. layers duets and choruses, giving each singer its own timbre, timing, tuning and stereo position (plus reverb for big choirs);
  5. remixes and masters.
- **Learns your taste.** 👍 / 👎 / ♥ / downloads / "use as voiceover music" teach VERBATIM which style words you keep. New prompts add them automatically ("Add what I usually like") and steer away from what you reject.
- **Every take.** ▶, 👍 👎 ♥, **Download** (cast song, song MP3/WAV/FLAC, stems, versions sung in your voice, lyrics TXT), and a menu: reuse, re-roll, remix/extend, re-cast, sing it in my voice, stems, use as voiceover music.

## Local voice cloning and lip-sync (Mac and Windows, no NVIDIA)

- **Voices.** Every speaker gets a custom voice, cut from their clearest 45 s with the music removed. It then speaks through:
  - Chatterbox (23 languages, ONNX, local);
  - OpenVoice tone colour;
  - ZipVoice (English and Chinese).
- **Lip-sync.** Runs in ONNX Runtime + OpenCV:
  1. YOLO-face finds the face;
  2. a steady crop is taken;
  3. Wav2Lip-GAN re-draws the mouth from the dub's mel spectrogram;
  4. a feathered lower-face mask blends it back, with sharpening;
  5. the film is re-encoded with the dubbed mix.

  It uses CoreML on Apple silicon and DirectML on Windows when available. The models are about 160 MB, downloaded once. Measured here: about 7 fps on a plain container CPU. Expect faster on Apple silicon.

## Feature Film

1. **Film.** Drop it in. VERBATIM checks the hardware:
   - this computer: up to **25 min**;
   - a Mac with a 40-core GPU, an NVIDIA PC or the Cloud GPU: longer.
2. **Find the actors.** VERBATIM transcribes with speakers. You can hear a sample of each actor, name them, and choose their **own cloned voice** (default) or another voice.
3. **Languages.**
4. **Rights.** Who confirmed it is recorded in the Consent register with the film.
5. **Dub the film.** For each language:
   - translation (offline or Claude) on the exact timeline (lines fitted to their slots);
   - directed performance;
   - each actor in their own voice;
   - original music and effects kept;
   - lip-sync (best available, this computer only, or off);
   - a subtitle track.

   Results appear in the page and in the Library, ready to play and download.

## Engines and licences (internal use)

Wav2Lip-GAN weights (research licence) and YOLO-face (AGPL) are used for **internal experiments only**, as are the other encumbered models already noted in THIRD_PARTY_NOTICES.md.

Suno, ElevenLabs and other services were studied only through their public product UX. No private APIs, models or code from them are used.
