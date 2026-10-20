"""Per-file transcription pipeline and the resumable batch runner.

    decode audio -> VAD speech map -> primary engine -> vocabulary repair ->
    hallucination guard -> (cross-check engine) -> (speakers) -> review queue -> exports -> master log
"""
from __future__ import annotations

import hashlib
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import __version__
from .audio import MEDIA_EXTENSIONS, load_audio, probe, signal_stats
from .engines import build, secondary_for
from .engines.base import DecodeOptions
from .model import Transcript
from .quality import ensure_words, missed_speech, remove_hallucinations, review_items, summary
from .settings import Settings
from .vad import SileroVAD, VadParams, merge_chunks
from .vocabulary import Vocabulary

Status = Callable[[str, float, str], None]  # (file, fraction, message)


@dataclass
class FileResult:
    source: Path
    status: str = "Queued"
    transcript: Transcript | None = None
    info: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)
    review: list[dict] = field(default_factory=list)
    corrections: list[dict] = field(default_factory=list)
    removals: list[dict] = field(default_factory=list)
    crosscheck: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    translation: Transcript | None = None
    error: str = ""
    started: str = ""
    finished: str = ""
    seconds: float = 0.0


def _mmss(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def file_signature(path: Path) -> str:
    """Content fingerprint: size + mtime + hashes of first/last 4 MB (fast on huge videos)."""
    st = path.stat()
    h = hashlib.sha256(f"{st.st_size}|{st.st_mtime_ns}".encode())
    with open(path, "rb") as f:
        h.update(f.read(4 << 20))
        if st.st_size > 8 << 20:
            f.seek(-(4 << 20), 2)
            h.update(f.read())
    return h.hexdigest()


def collect_media(paths: list[str | Path]) -> list[Path]:
    out: list[Path] = []
    seen = set()
    for item in paths:
        p = Path(item)
        cands = sorted((x for x in p.rglob("*") if x.is_file()), key=lambda x: str(x).lower()) if p.is_dir() else [p]
        for x in cands:
            if x.suffix.lower() in MEDIA_EXTENSIONS and not x.name.startswith("._"):
                key = str(x.resolve())
                if key not in seen:
                    seen.add(key)
                    out.append(x)
    return out


_VAD: SileroVAD | None = None


def _vad() -> SileroVAD:
    global _VAD
    if _VAD is None:
        _VAD = SileroVAD()
    return _VAD


def transcribe_file(src: Path, s: Settings, progress: Callable[[float, str], None] | None = None,
                    engine_override=None, secondary_override=None) -> FileResult:
    res = FileResult(src, started=datetime.now().isoformat(timespec="seconds"))
    t0 = time.time()
    say = progress or (lambda f, m: None)
    info = probe(src)
    say(0.02, "Decoding audio…")
    audio = load_audio(src, "normalize" if s.enhancement == "restore" else s.enhancement)
    if s.enhancement == "restore":
        say(0.04, "Restoring audio (AI noise removal)…")
        from .restore import restore

        audio = restore(audio)
    duration = len(audio) / 16000
    res.info = {"duration": duration, "channels": info.channels, "source_sample_rate": info.sample_rate,
                "codec": info.codec, "has_video": info.has_video, **signal_stats(audio)}
    vocab = Vocabulary.parse(s.vocabulary)
    context = ""
    if s.filename_context:
        from .vocabulary import terms_from_filename

        context, name_terms = terms_from_filename(src.stem)
        vocab.terms += [t for t in name_terms if t not in vocab.terms]
    if s.use_vad:
        say(0.05, "Finding speech (Silero VAD)…")
        vad = _vad()
        speech = vad.speech_regions(audio, VadParams())
        chunks = merge_chunks(speech, probs=getattr(vad, "last_probs", None))
        speech_s = sum(e - b for b, e in speech)
        if speech_s < max(1.0, 0.03 * duration) and res.info.get("rms_dbfs", -120) > -50:
            # Safety net: music beds, distant mics or unusual channel layouts can hide speech from
            # the VAD. Never return an empty transcript for an audible file — decode all of it.
            res.info["vad_fallback"] = True
            speech = None
            chunks = [(float(a), float(min(a + 28, duration))) for a in range(0, int(duration) + 1, 28) if a < duration]
    else:
        speech = None
        chunks = [(float(a), float(min(a + 30, duration))) for a in range(0, int(duration) + 1, 30) if a < duration]
    res.info["speech_seconds"] = round(sum(e - b for b, e in speech), 1) if speech else round(duration, 1)
    opts = DecodeOptions(language=s.language, vocabulary=vocab, verbatim=s.verbatim, context=context,
                         diarize=s.diarize, num_speakers=s.num_speakers)
    variant = s.variant
    if s.engine == "parakeet" and s.language and s.language != "en":
        from .engines.sherpa import ParakeetEngine

        if not ParakeetEngine.supports(s.language):
            raise RuntimeError(f"Parakeet does not support language '{s.language}'. "
                               "Choose Whisper large-v3 or ElevenLabs Scribe for this file.")
        variant = "parakeet-v3"
    engine = engine_override or build(s.engine, variant)
    span = 0.75 if s.cross_check else 0.9
    t = engine.transcribe(audio, chunks, opts, lambda f, m: say(0.08 + span * 0.8 * f, m))
    ensure_words(t)
    if s.fuzzy_vocab or vocab.rules or vocab.terms:
        res.corrections = vocab.apply(t, fuzzy_threshold=90.0 if s.fuzzy_vocab else 101)
    res.removals = remove_hallucinations(t, speech)
    if s.precise_timing and t.engine not in ("parakeet", "elevenlabs") and t.segments:
        try:  # Whisper's word times are estimates: re-time every word acoustically (align.py)
            say(0.80, "Precise word timing…")
            from .align import Aligner

            res.info["alignment"] = Aligner(progress=lambda f, m: say(0.80 + 0.08 * f, m)).align(audio, t)
        except Exception as exc:  # never fail a file over timing refinement
            res.info["alignment_error"] = str(exc)
    if s.cross_check:
        pick = secondary_override or secondary_for(s.engine, t.language if t.language not in ("unknown", "auto") else s.language)
        if pick:
            try:
                sec_engine = pick if hasattr(pick, "transcribe") else build(*pick)
                say(0.70, f"Cross-checking with {sec_engine.label}…")
                sec = sec_engine.transcribe(audio, chunks, DecodeOptions(language=t.language, vocabulary=vocab),
                                            lambda f, m: say(0.70 + 0.18 * f, m))
                ensure_words(sec)
                from .crosscheck import cross_check

                res.crosscheck = cross_check(t, sec, fuse=s.fuse)
            except Exception as exc:  # a failed cross-check never fails the file
                res.crosscheck = {"error": str(exc)}
    if s.diarize and s.engine != "elevenlabs":
        try:
            say(0.90, "Labelling speakers…")
            from .diarize import assign_speakers, speaker_turns

            turns = speaker_turns(audio, s.num_speakers)
            res.info["speakers"] = assign_speakers(t, turns)
            if s.speaker_library and turns:
                try:  # voice fingerprints; recognise speakers named in earlier files
                    from .diarize import embedding_model, label_order
                    from .speakers import SpeakerLibrary, fingerprints, rename_in_transcript

                    t.speaker_profiles = fingerprints(audio, turns, label_order(turns), embedding_model())
                    lib = SpeakerLibrary()
                    found = lib.match(t.speaker_profiles) if lib.entries else {}
                    if found:
                        rename_in_transcript(t, {k: v[0] for k, v in found.items()})
                        res.info["recognised_speakers"] = {v[0]: v[1] for v in found.values()}
                        say(0.92, "Recognised: " + ", ".join(v[0] for v in found.values()))
                except Exception as exc:
                    res.info["speaker_library_error"] = str(exc)
        except Exception as exc:
            res.info["diarization_error"] = str(exc)
    elif s.engine == "elevenlabs":
        res.info["speakers"] = len({seg.speaker for seg in t.segments if seg.speaker})
    gaps = missed_speech(t, speech) if speech else []
    res.review = review_items(t, s.review_threshold)
    for g in gaps:
        res.review.append({"start": g[0], "end": g[1], "speaker": "", "text": "", "confidence": "",
                           "context": "Speech detected but no words transcribed", "reason": "possible missed speech"})
    for d in res.crosscheck.get("disagreements", []):
        if not d["fused"]:
            res.review.append({"start": d["start"], "end": d["end"], "speaker": "", "text": d["primary"],
                               "confidence": "", "context": f"Engine A: “{d['primary']}”  |  Engine B: “{d['secondary']}”",
                               "reason": "engine disagreement"})
    res.review.sort(key=lambda r: r["start"])
    res.quality = summary(t, res.review, gaps, s.review_threshold)
    res.info["review_threshold"] = s.review_threshold
    res.quality["agreement"] = res.crosscheck.get("agreement")
    res.quality["corrections"] = len(res.corrections)
    res.quality["removed"] = len(res.removals)
    res.transcript = t
    if s.translate_english and t.language not in ("en", "unknown") and s.engine == "whisper":
        try:  # Whisper's built-in speech translation (large models; turbo was not trained for it)
            say(0.93, "Creating English translation…")
            tr_engine = build("whisper", "large-v3" if "turbo" in variant or variant == "small" else variant)
            res.translation = tr_engine.transcribe(
                audio, chunks, DecodeOptions(language=t.language, task="translate", verbatim=False))
            ensure_words(res.translation)
            remove_hallucinations(res.translation, speech)
        except Exception as exc:
            res.info["translation_error"] = str(exc)
    res.seconds = round(time.time() - t0, 1)
    res.info["realtime_factor"] = round(res.seconds / max(1.0, duration), 3)
    res.finished = datetime.now().isoformat(timespec="seconds")
    res.status = "Completed"
    say(1.0, "Done")
    return res


class BatchRunner:
    """Runs a queue; failures are isolated; finished files are skipped on re-run (resume)."""

    def __init__(self, files: list[Path], settings: Settings, on_status: Status | None = None,
                 on_result: Callable[[str, "FileResult"], None] | None = None):
        self.files = files
        self.s = settings
        self.on_status = on_status or (lambda f, p, m: None)
        self.on_result = on_result or (lambda f, r: None)
        self.stop_requested = False

    def run(self) -> dict:
        from .exporters import export_all
        from .master_log import MasterLog

        out_root = Path(self.s.output_dir)
        out_root.mkdir(parents=True, exist_ok=True)
        log = MasterLog(out_root)
        batch_id = log.start_batch(self.s, len(self.files), __version__)
        done = failed = skipped = 0
        fp = self.s.fingerprint()
        for src in self.files:
            name = str(src)  # status key: full path (file names may repeat across folders)
            if self.stop_requested:
                self.on_status(name, 0, "Not started (batch stopped)")
                continue
            try:
                sig = file_signature(src)
                prev = log.completed_output(sig, fp)
                if prev:
                    skipped += 1
                    try:
                        self.on_result(name, FileResult(src, outputs={"folder": str(Path(prev).parent), "json": prev}))
                    except Exception:
                        pass
                    self.on_status(name, 1, "Already transcribed — skipped (resume)")
                    continue
                self.on_status(name, 0, "Starting…")
                res = transcribe_file(src, self.s, lambda f, m, n=name: self.on_status(n, f, m))
                res.outputs = export_all(res, out_root, self.s.formats, self.s)
                log.record_file(batch_id, res, sig, fp, self.s)
                done += 1
                try:
                    self.on_result(name, res)
                except Exception:
                    pass
                q = res.quality
                agree = f", agreement {q['agreement']:.1%}" if q.get("agreement") is not None else ""
                dur = res.info.get("duration", 0)
                x = dur / max(res.seconds, 0.1)
                speed = f"{x:.1f}× realtime" if x < 10 else f"{x:.0f}× realtime"
                self.on_status(name, 1, f"Completed in {_mmss(res.seconds)} ({_mmss(dur)} of media, {speed}) — "
                                        f"{q['review_items']} to review{agree}")
            except Exception as exc:
                failed += 1
                err = f"{type(exc).__name__}: {exc}"
                log.record_error(batch_id, src, err, traceback.format_exc())
                self.on_status(name, 1, "Failed: " + err[:120])
        log.finish_batch(batch_id, done, failed, skipped, stopped=self.stop_requested)
        xlsx = log.export_excel()
        return {"completed": done, "failed": failed, "skipped": skipped, "excel": str(xlsx), "batch_id": batch_id}
