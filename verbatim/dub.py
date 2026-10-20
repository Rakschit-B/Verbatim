"""Voice Studio jobs: transcript → translation → timed voiceover → exports.

A job lives next to the transcript, in "<output folder>/Voice Studio/", as
"<file> — <Language>.voice.json", so translations can be reopened, edited and re-voiced.

Timing fit: each translated line is spoken in the slot of the original line (until the next line
starts). If the voice is longer than the slot it is re-spoken faster (up to ×1.30); if it still
overruns, the line is flagged "too long — shorten the translation" and starts no earlier than the
previous line ends, so voices never overlap.
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import wave
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from .model import Transcript
from .platform_info import IS_WINDOWS, ffmpeg_path
from .translate import LANG_NAMES

SR = 24000
MAX_SPEEDUP = 1.30
SPLIT_LONGER_THAN = 9.0     # seconds: long transcript segments are split at sentence ends for dubbing


@dataclass
class Line:
    i: int
    start: float
    end: float
    speaker: str
    source: str
    text: str = ""
    edited: bool = False
    fit: str = ""            # "", "ok", "faster ×1.15", "too long +1.2 s", "shifted +0.4 s"
    speed: float = 1.0
    spoken: float = 0.0      # seconds of generated speech


@dataclass
class VoiceJob:
    source_json: str
    media: str
    src_lang: str
    tgt_lang: str
    engine: str = "offline"
    model: str = ""
    lines: list[Line] = field(default_factory=list)
    voices: dict = field(default_factory=dict)     # speaker -> kokoro speaker id
    speed: float = 1.0
    duration: float = 0.0
    created: str = ""
    updated: str = ""
    translated: str = ""
    rendered: str = ""
    outputs: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- persistence
    @property
    def path(self) -> Path:
        src = Path(self.source_json)
        return src.parent / "Voice Studio" / f"{src.stem} — {LANG_NAMES.get(self.tgt_lang, self.tgt_lang)}.voice.json"

    def save(self) -> Path:
        self.updated = datetime.now().isoformat(timespec="seconds")
        p = self.path
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)
        return p

    @staticmethod
    def load(path: str | Path) -> "VoiceJob":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        d["lines"] = [Line(**x) for x in d.get("lines", [])]
        return VoiceJob(**d)

    def speakers(self) -> list[str]:
        out = []
        for ln in self.lines:
            if ln.speaker not in out:
                out.append(ln.speaker)
        return out


# ====================================================================== create
def new_job(source_json: str | Path, tgt_lang: str) -> VoiceJob:
    payload = json.loads(Path(source_json).read_text(encoding="utf-8"))
    t = Transcript.from_dict(payload["transcript"])
    job = VoiceJob(str(source_json), payload.get("source_path", ""), t.language if t.language not in ("unknown", "auto") else "en",
                   tgt_lang, duration=float(payload.get("info", {}).get("duration", 0) or 0),
                   created=datetime.now().isoformat(timespec="seconds"))
    existing = job.path
    if existing.exists():  # reopen previous work on the same language
        return VoiceJob.load(existing)
    for seg in t.segments:
        for s, e, txt in _sentences(seg):
            job.lines.append(Line(len(job.lines), round(s, 3), round(e, 3), seg.speaker or "Speaker", txt))
    return job


def _sentences(seg):
    """Split long segments at sentence ends using word timings."""
    text = seg.text.strip()
    if seg.end - seg.start <= SPLIT_LONGER_THAN or not seg.words:
        return [(seg.start, seg.end, text)] if text else []
    out, cur = [], []
    for w in seg.words:
        cur.append(w)
        dur = cur[-1].end - cur[0].start
        if (re.search(r"[.!?।]$", w.text.strip()) and dur >= 2.0) or dur >= 14.0:
            out.append(cur)
            cur = []
    if cur:
        if out and cur[-1].end - cur[0].start < 1.5:
            out[-1].extend(cur)
        else:
            out.append(cur)
    res = []
    for ws in out:
        txt = " ".join(x.text.strip() for x in ws).strip()
        if txt:
            res.append((ws[0].start, ws[-1].end, txt))
    return res


# ====================================================================== translate
def translate_job(job: VoiceJob, translator, vocabulary: str = "", progress=None, only_empty: bool = False) -> VoiceJob:
    idx = [k for k, ln in enumerate(job.lines) if not (only_empty and ln.text.strip()) and not ln.edited]
    if not idx:
        return job
    src = [job.lines[k].source for k in idx]
    spk = [job.lines[k].speaker for k in idx]
    ctx = Path(job.media).stem if job.media else ""
    out = translator.translate(src, job.src_lang, job.tgt_lang, vocabulary=vocabulary, context=ctx, speakers=spk,
                               progress=progress)
    for k, txt in zip(idx, out):
        job.lines[k].text = txt
        job.lines[k].fit = ""
    job.engine = translator.name
    job.model = getattr(translator, "model", "") or ""
    job.translated = datetime.now().isoformat(timespec="seconds")
    job.save()
    return job


# ====================================================================== voice
def _trim(a: np.ndarray, thr: float = 0.01) -> np.ndarray:
    idx = np.where(np.abs(a) > thr)[0]
    if len(idx) == 0:
        return a[:0]
    s = max(0, idx[0] - int(0.03 * SR))
    e = min(len(a), idx[-1] + int(0.06 * SR))
    return a[s:e]


def render(job: VoiceJob, synth, progress=None, mix: bool = True, video: bool = True) -> dict:
    """Speak every line in its slot, then write voice track, mix, video and subtitles."""
    from .tts import voices_for

    default_sid = voices_for(job.tgt_lang)[0][0] if voices_for(job.tgt_lang) else 0
    dur = max(job.duration, max((ln.end for ln in job.lines), default=0) + 2.0)
    track = np.zeros(int(dur * SR) + SR * 10, dtype=np.float32)
    prev_end = 0.0
    n = len(job.lines)
    for k, ln in enumerate(job.lines):
        if progress:
            progress(k / max(1, n), f"Voicing line {k + 1} of {n}")
        if not ln.text.strip():
            ln.fit, ln.spoken = "no translation", 0.0
            continue
        sid = int(job.voices.get(ln.speaker, default_sid))
        nxt = next((x.start for x in job.lines[k + 1:] if x.text.strip()), dur)
        start = max(ln.start, prev_end + 0.05)       # never overlap the previous voice
        slot = max(ln.end, nxt - 0.08) - start
        speed = job.speed
        a = _trim(synth.speak(ln.text, job.tgt_lang, sid, speed))
        need = len(a) / SR
        for _ in range(3):  # speed up until it fits (speech rate is not exactly proportional to the setting)
            if need <= slot or slot <= 0.3 or speed >= job.speed * MAX_SPEEDUP - 1e-3:
                break
            speed = min(job.speed * MAX_SPEEDUP, speed * need / slot * 1.04)
            a = _trim(synth.speak(ln.text, job.tgt_lang, sid, speed))
            need = len(a) / SR
        shift = start - ln.start
        over = need - slot
        ln.speed, ln.spoken = round(speed, 2), round(need, 2)
        if over > 0.25:
            ln.fit = f"too long +{over:.1f} s"
        elif shift > 0.25:
            ln.fit = f"shifted +{shift:.1f} s"
        elif speed > job.speed * 1.03:
            ln.fit = f"faster ×{speed / job.speed:.2f}"
        else:
            ln.fit = "ok"
        i0 = int(start * SR)
        if i0 + len(a) > len(track):
            track = np.concatenate([track, np.zeros(i0 + len(a) - len(track) + SR, dtype=np.float32)])
        track[i0:i0 + len(a)] += a
        prev_end = start + need
    end = max(int(dur * SR), int(prev_end * SR) + int(0.5 * SR))
    track = track[:end]
    peak = float(np.abs(track).max()) if len(track) else 0
    if peak > 0:
        track *= min(1.0, 0.89 / peak)
    outs = _write_outputs(job, track, mix, video, progress)
    job.outputs = outs
    job.rendered = datetime.now().isoformat(timespec="seconds")
    job.save()
    _log(job)
    if progress:
        progress(1.0, "Voiceover ready")
    return outs


def _write_wav(path: Path, a: np.ndarray, sr: int = SR):
    pcm = (np.clip(a, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def _ffmpeg(args: list[str]) -> tuple[int, str]:
    flags = 0x08000000 if IS_WINDOWS else 0
    r = subprocess.run([ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args],
                       capture_output=True, text=True, errors="replace", creationflags=flags)
    return r.returncode, r.stderr[-400:]


def _write_outputs(job: VoiceJob, track: np.ndarray, mix: bool, video: bool, progress) -> dict:
    lang = LANG_NAMES.get(job.tgt_lang, job.tgt_lang)
    stem = Path(job.source_json).stem
    folder = job.path.parent
    folder.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {"folder": str(folder)}
    voice = folder / f"{stem} — {lang} voiceover.wav"
    _write_wav(voice, track)
    out["voice"] = str(voice)
    media = Path(job.media) if job.media else None
    has_media = bool(media and media.exists())
    if mix and has_media:
        if progress:
            progress(0.96, "Mixing over the original (ducked)…")
        mixed = folder / f"{stem} — {lang} voiceover + original.wav"
        code, err = _ffmpeg(["-i", str(media), "-i", str(voice), "-filter_complex",
                             "[0:a]aresample=48000,pan=mono|c0=0.5*c0+0.5*c1[o];[1:a]aresample=48000,asplit=2[v][sc];"
                             "[o][sc]sidechaincompress=threshold=0.015:ratio=10:attack=15:release=450:makeup=1[d];"
                             "[d]volume=0.55[d2];[d2][v]amix=inputs=2:duration=longest:normalize=0[m]",
                             "-map", "[m]", "-ar", "48000", "-ac", "2", str(mixed)])
        if code != 0:  # mono sources: no c1 channel
            code, err = _ffmpeg(["-i", str(media), "-i", str(voice), "-filter_complex",
                                 "[0:a]aresample=48000,aformat=channel_layouts=mono[o];[1:a]aresample=48000,asplit=2[v][sc];"
                                 "[o][sc]sidechaincompress=threshold=0.015:ratio=10:attack=15:release=450:makeup=1[d];"
                                 "[d]volume=0.55[d2];[d2][v]amix=inputs=2:duration=longest:normalize=0[m]",
                                 "-map", "[m]", "-ar", "48000", "-ac", "2", str(mixed)])
        if code == 0:
            out["mix"] = str(mixed)
        else:
            out["mix_error"] = err
        if video and code == 0 and _has_video(media):
            if progress:
                progress(0.98, "Writing the dubbed video…")
            mp4 = folder / f"{stem} — {lang} voiceover.mp4"
            code2, err2 = _ffmpeg(["-i", str(media), "-i", str(mixed), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                                   "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(mp4)])
            if code2 != 0:  # codec not allowed in MP4: re-encode the picture
                code2, err2 = _ffmpeg(["-i", str(media), "-i", str(mixed), "-map", "0:v:0", "-map", "1:a:0", "-c:v",
                                       "libx264", "-crf", "20", "-preset", "veryfast", "-c:a", "aac", "-b:a", "192k",
                                       "-movflags", "+faststart", "-shortest", str(mp4)])
            if code2 == 0:
                out["video"] = str(mp4)
            else:
                out["video_error"] = err2
    out.update(write_text_outputs(job, folder, stem, lang))
    return out


def _has_video(media: Path) -> bool:
    try:
        from .audio import probe

        return bool(probe(media).has_video)
    except Exception:
        return False


def write_text_outputs(job: VoiceJob, folder: Path, stem: str, lang: str) -> dict:
    from .exporters import stamp

    out = {}
    cues = subtitle_cues(job.lines)
    srt = folder / f"{stem} — {lang}.srt"
    srt.write_text("".join(f"{i}\n{stamp(s, ',')} --> {stamp(e, ',')}\n{t}\n\n" for i, (s, e, t) in enumerate(cues, 1)),
                   encoding="utf-8")
    vtt = folder / f"{stem} — {lang}.vtt"
    vtt.write_text("WEBVTT\n\n" + "".join(f"{stamp(s)} --> {stamp(e)}\n{t}\n\n" for s, e, t in cues), encoding="utf-8")
    txt = folder / f"{stem} — {lang} translation.txt"
    rows = [f"TRANSLATION ({LANG_NAMES.get(job.src_lang, job.src_lang)} → {lang}) OF: {Path(job.media).name or stem}",
            f"Engine: {job.engine}{(' ' + job.model) if job.model else ''} — machine translation, edited lines marked ✎", ""]
    for ln in job.lines:
        rows.append(f"[{stamp(ln.start).split('.')[0]}] {ln.speaker}: {ln.text}{'  ✎' if ln.edited else ''}")
    txt.write_text("\n".join(rows), encoding="utf-8")
    rep = folder / f"{stem} — {lang} timing report.csv"
    with rep.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Line", "Start", "End", "Speaker", "Original", "Translation", "Edited", "Fit", "Speed", "Spoken (s)",
                    "Slot (s)"])
        for ln in job.lines:
            w.writerow([ln.i + 1, stamp(ln.start), stamp(ln.end), ln.speaker, ln.source, ln.text, "yes" if ln.edited else "",
                        ln.fit, ln.speed, ln.spoken, round(ln.end - ln.start, 2)])
    out.update({"srt": str(srt), "vtt": str(vtt), "txt": str(txt), "report": str(rep)})
    return out


def subtitle_cues(lines: list[Line], max_chars: int = 42, max_lines: int = 2) -> list[tuple[float, float, str]]:
    """Translated subtitles: each line split into ≤2×42-character cues, time shared by length."""
    import textwrap

    cues = []
    for ln in lines:
        t = " ".join(ln.text.split())
        if not t:
            continue
        wrapped = textwrap.wrap(t, max_chars) or [t]
        blocks = ["\n".join(wrapped[i:i + max_lines]) for i in range(0, len(wrapped), max_lines)]
        total = sum(len(b) for b in blocks) or 1
        s = ln.start
        span = max(ln.end - ln.start, 0.8 * len(blocks))
        for b in blocks:
            e = s + span * len(b) / total
            cues.append((round(s, 3), round(e, 3), b))
            s = e
    return cues


def _log(job: VoiceJob):
    try:
        from .master_log import MasterLog

        root = Path(job.source_json).parent.parent
        ml = MasterLog(root)
        ml.record_voice_job(job)
        ml.export_excel()
    except Exception:
        pass
