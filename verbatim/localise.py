# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Module 04 — Video Localise: one film in, every language out.

    transcribe (speakers) → [keep each speaker's own voice, with consent] → for every language:
    translate → direct the performance → voice → keep the original music & effects → mux the dubbed film
    → subtitles (soft track and/or burned in) → optional lip-sync on the Cloud GPU → Master Log.

Each language is an ordinary Voice Studio job, so any line can be opened, re-directed and re-rendered later.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from .platform_info import IS_WINDOWS, ffmpeg_path

ISO3 = {"en": "eng", "hi": "hin", "bn": "ben", "ta": "tam", "te": "tel", "mr": "mar", "gu": "guj", "kn": "kan",
        "ml": "mal", "pa": "pan", "ur": "urd", "es": "spa", "fr": "fra", "de": "deu", "it": "ita", "pt": "por",
        "ar": "ara", "ja": "jpn", "zh": "zho", "ko": "kor", "ru": "rus", "he": "heb", "tr": "tur", "nl": "nld",
        "pl": "pol", "id": "ind", "th": "tha", "vi": "vie", "sv": "swe", "uk": "ukr"}


@dataclass
class LocaliseRequest:
    video: str
    languages: list = field(default_factory=lambda: ["hi"])
    voice_mode: str = "own"             # own = each speaker's own voice (consent) · studio = studio voices
    consent_person: str = ""            # who confirmed the rights to the speakers' voices
    translator: str = "translategemma"  # translategemma | claude | opus
    translator_model: str = ""
    style: str = "natural"
    direct: bool = True                 # performance direction (emotion / emphasis per line)
    keep_background: bool = True        # keep the original music & effects under the new voices
    subtitles_soft: bool = True         # subtitle track inside the MP4 (switchable in players)
    subtitles_burn: bool = False        # subtitles drawn into the picture
    lipsync: bool = False               # re-time the mouths
    lipsync_mode: str = "auto"          # auto (cloud if set up, else this computer) | local | cloud
    voices: dict = field(default_factory=dict)   # speaker -> voice id chosen by the user (Feature Film)
    names: dict = field(default_factory=dict)    # speaker -> actor name
    kind: str = "video"                 # video (Video Localise) | film (Feature Film)
    transcript: str = ""                # reuse an analysed transcript
    quality: str = "studio"
    clone_engine: str = "auto"
    vocabulary: str = ""


def _run(args: list[str]) -> tuple[int, str]:
    flags = 0x08000000 if IS_WINDOWS else 0
    r = subprocess.run([ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args],
                       capture_output=True, text=True, errors="replace", creationflags=flags)
    return r.returncode, r.stderr[-500:]


# ---------------------------------------------------------------------- steps
def transcribe(video: Path, settings, progress) -> str:
    """Transcript JSON for the film (re-uses a finished transcript — the Master Log resume)."""
    from .pipeline import BatchRunner

    s = settings
    s.diarize = True
    out: dict = {}
    last = [""]

    def st(_n, f, m):
        last[0] = m
        progress(f, m)
    BatchRunner([video], s, st, lambda n, r: out.update(r.outputs or {})).run()
    js = out.get("json")
    if not js or not Path(js).exists():
        raise RuntimeError(f"Transcription did not finish — {last[0] or 'see the Activity Log'}")
    return js


def speaker_voices(json_path: str, media: str, consent_id: str, progress=None, max_s: float = 45.0,
                   names: dict | None = None) -> dict:
    """One custom voice per speaker, cut from the film itself (their clearest 45 s), music removed."""
    from .dub import new_job
    from .voicelab import create_from_recording, decode, library, write_wav

    job = new_job(json_path, "en")
    have = {cv.source: cv for cv in library()}
    sr = 44100
    audio = None
    out = {}
    speakers = job.speakers()
    for k, spk in enumerate(speakers):
        tag = f"{Path(media).stem} · {(names or {}).get(spk) or spk}"
        if tag + ".wav" in have:                                   # already made for this film
            out[spk] = have[tag + ".wav"].id
            continue
        if audio is None:
            audio = decode(media, sr, 2)
        spans = sorted(((ln.end - ln.start, ln.start, ln.end) for ln in job.lines if ln.speaker == spk), reverse=True)
        pieces, total = [], 0.0
        for dur, s, e in spans:
            if total >= max_s:
                break
            pieces.append(audio[int(s * sr):int(e * sr)])
            total += dur
        if total < 3.0:
            continue
        clip = np.concatenate(pieces)
        tmp = Path(tempfile.mkdtemp()) / f"{tag}.wav"
        write_wav(tmp, clip.mean(1), sr)
        if progress:
            progress(k / max(1, len(speakers)), f"Learning {spk}'s voice…")
        cv = create_from_recording(tmp, tag, character=f"from {Path(media).name}", lang=job.src_lang,
                                   owner=spk, rights="Confirmed in Video Localise", consent_id=consent_id,
                                   remove_music=None)
        out[spk] = cv.id
    return out


def mux_subtitles(video: Path, srt: Path, lang: str, out: Path, burn: bool = False) -> tuple[Path, str]:
    """Soft subtitle track (mov_text) — or burned into the picture when `burn` (needs ffmpeg with libass)."""
    if burn:
        esc = str(srt).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
        code, err = _run(["-i", str(video), "-vf", f"subtitles='{esc}':force_style='FontName=Hanken Grotesk,"
                          "FontSize=20,Outline=1,Shadow=0,MarginV=28'", "-c:a", "copy", str(out)])
        if code == 0:
            return out, ""
        burn_err = "Burned-in subtitles need ffmpeg with libass — added a subtitle track instead. " + err[-120:]
    else:
        burn_err = ""
    code, err = _run(["-i", str(video), "-i", str(srt), "-map", "0:v", "-map", "0:a", "-map", "1:0", "-c:v", "copy",
                      "-c:a", "copy", "-c:s", "mov_text", "-metadata:s:s:0", f"language={ISO3.get(lang, 'und')}",
                      str(out)])
    if code != 0:
        return video, (burn_err + " " + err).strip()
    return out, burn_err


def lipsync(video: Path, audio: Path, out: Path, progress=None, mode: str = "auto",
            soundtrack: Path | None = None) -> Path:
    """Lip-sync the dubbed film: on the Cloud GPU (LatentSync, best) or on this computer (ONNX, any Mac/PC)."""
    from .cloud import active_for

    if mode == "cloud" or (mode == "auto" and active_for("lipsync")):
        from .runtimes import EngineHost

        if not active_for("lipsync"):
            raise RuntimeError("Cloud lip-sync needs a Cloud GPU — set one up in Settings › Cloud GPU.")
        EngineHost.get("lipsync", progress).request("lipsync", progress=progress, video=str(video), audio=str(audio),
                                                    out=str(out))
        return out
    from . import lipsync as local

    local.sync(video, audio, out, progress, soundtrack=soundtrack)
    return out


# ---------------------------------------------------------------------- the whole film
def run(req: LocaliseRequest, settings, progress=None, stop=lambda: False) -> dict:
    from . import dub
    from .consent import ConsentRegister
    from .translate import LANG_NAMES, build
    from .tts import Synth, default_voices

    say = progress or (lambda f, m: None)
    video = Path(req.video)
    if not video.exists():
        raise FileNotFoundError(video)
    n = max(1, len(req.languages))
    say(0.01, "Listening to the film…")
    src_json = req.transcript if req.transcript and Path(req.transcript).exists() else \
        transcribe(video, settings, lambda f, m: say(0.15 * f, "Transcribing — " + m))
    own: dict = {}
    if req.voice_mode == "own":
        if not req.consent_person.strip():
            raise RuntimeError("Keeping the speakers' own voices needs a rights confirmation (who confirmed it).")
        reg = ConsentRegister()
        entry = reg.add_declaration(req.consent_person.strip(),
                                    f"I confirm Infinite Story LLP holds the rights and consent of every speaker in "
                                    f"“{video.name}” to re-voice them in other languages for this film.",
                                    scope=f"Video Localise — {video.name}", recorded_by=req.consent_person.strip(),
                                    notes="Video Localise")
        own = speaker_voices(src_json, str(video), entry["id"], lambda f, m: say(0.15 + 0.1 * f, m),
                             names=req.names)
    own.update({k: v for k, v in (req.voices or {}).items() if v})
    tr = build(req.translator, req.translator_model or "claude-sonnet-5-5", lambda f, m: None)
    results: dict = {}
    for k, lang in enumerate(req.languages):
        if stop():
            break
        base = 0.25 + 0.75 * k / n
        span = 0.75 / n
        name = LANG_NAMES.get(lang, lang)

        def p(f, m, base=base, span=span, name=name):
            say(base + span * max(0.0, min(1.0, f)), f"{name}: {m}")

        job = dub.new_job(src_json, lang)
        job.style, job.quality, job.clone_engine = req.style, req.quality, req.clone_engine
        job.keep_background = req.keep_background
        if not any(ln.text.strip() for ln in job.lines):
            p(0.02, "translating…")
            dub.translate_job(job, tr, req.vocabulary, lambda f, m: p(0.35 * f, m))
        if req.direct:
            dub.direct_job(job, tr if req.translator == "claude" else None, only_empty=True)
        spk = job.speakers()
        fallback = default_voices(lang, len(spk))
        for i, s in enumerate(spk):
            job.voices.setdefault(s, own.get(s) or fallback[i])
        job.save()
        notes = []

        def voice_it():
            return dub.render(job, Synth(progress=lambda f, m: p(0.4 + 0.4 * f, m), quality=job.quality,
                                         clone_engine=job.clone_engine), lambda f, m: p(0.4 + 0.45 * f, m),
                              mix=True, video=True)
        try:
            out = voice_it()
        except RuntimeError as exc:
            if not own or "To speak" not in str(exc):
                raise
            # this language has no engine for cloned voices on this computer yet → studio voices, with a note
            for i, s in enumerate(spk):
                if job.voices.get(s, "").startswith("my:"):
                    job.voices[s] = fallback[i]
            job.save()
            notes.append(f"Studio voices used — {exc}")
            out = voice_it()
        film = Path(out["video"]) if out.get("video") else None
        if film and req.lipsync:
            try:
                p(0.86, "lip-sync on the Cloud GPU…")
                synced = lipsync(film, Path(out["voice"]), film.with_name(film.stem + " (lip-sync raw).mp4"),
                                 lambda f, m: p(0.86 + 0.08 * f, m), req.lipsync_mode, soundtrack=film)
                final = film.with_name(film.stem + " (lip-sync).mp4")
                code, err = _run(["-i", str(synced), "-i", str(film), "-map", "0:v", "-map", "1:a", "-c", "copy",
                                  "-shortest", str(final)])    # the synced picture + the full dubbed mix
                film = final if code == 0 else synced
                out["lipsync"] = str(film)
            except Exception as exc:
                notes.append(f"Lip-sync skipped: {exc}")
        if film and out.get("srt") and (req.subtitles_soft or req.subtitles_burn):
            p(0.95, "subtitles…")
            final = film.with_name(film.stem.replace(" (lip-sync)", "") + " — localised.mp4")
            film2, note = mux_subtitles(film, Path(out["srt"]), lang, final, burn=req.subtitles_burn)
            if note:
                notes.append(note)
            film = film2
        out["film"] = str(film) if film else ""
        out["notes"] = notes
        results[lang] = out
        p(1.0, "ready")
    report = video.parent / f"{video.stem} — localisation.json"
    try:
        report = Path(src_json).parent / f"{video.stem} — localisation.json"
        if req.kind == "film":
            report = Path(settings.output_dir) / "Feature Film" / video.stem / "film.json"
            report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"video": str(video), "request": asdict(req), "results": results,
                                      "finished": datetime.now().isoformat(timespec="seconds")},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    say(1.0, "All languages ready.")
    return {"results": results, "report": str(report), "transcript": src_json}


def analyse(video: str | Path, settings, progress=None) -> dict:
    """Feature Film step 1: transcribe with speakers and return who speaks, how much, and a sample of each."""
    from .dub import new_job

    js = transcribe(Path(video), settings, progress or (lambda f, m: None))
    job = new_job(js, "en")
    actors = {}
    for ln in job.lines:
        a = actors.setdefault(ln.speaker, {"speaker": ln.speaker, "lines": 0, "seconds": 0.0, "sample": (0.0, 0.0),
                                            "text": ""})
        a["lines"] += 1
        a["seconds"] += ln.end - ln.start
        if ln.end - ln.start > a["sample"][1] - a["sample"][0] and ln.end - ln.start <= 12:
            a["sample"], a["text"] = (ln.start, ln.end), ln.source[:120]
    ordered = sorted(actors.values(), key=lambda x: -x["seconds"])
    return {"transcript": js, "actors": ordered, "duration": job.duration, "language": job.src_lang}
