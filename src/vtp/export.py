"""Export transcripts to Markdown / JSON and build INDEX for Grok."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vtp.state import StateDB, VideoJob
from vtp.transcribe import Segment, TranscriptResult, format_ts


def duration_hms(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    return format_ts(seconds)


def transcript_markdown(
    job: VideoJob,
    result: TranscriptResult,
    *,
    speaker_default: str = "Kim Paim",
) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    lines = [
        f"# Title: {job.title}",
        f"- Id: `{job.id}`",
        f"- Source: `{job.source_path}`",
        f"- Rel path: `{job.rel_path}`",
        f"- Duration: {duration_hms(result.duration or job.duration_sec)}",
        f"- Language: {result.language} (p={result.language_probability:.2f})",
        f"- Transcribed: {now}",
        f"- ASR model: {result.model_name} ({result.device}/{result.compute_type})",
        f"- Speakers: {speaker_default} (default narrator; diarization not applied)",
        "",
        "## Transcript",
        "",
    ]
    for seg in result.segments:
        lines.append(
            f"[{format_ts(seg.start)}] [{speaker_default}] {seg.text}"
        )
    lines.append("")
    return "\n".join(lines)


def transcript_json(
    job: VideoJob,
    result: TranscriptResult,
    *,
    speaker_default: str = "Kim Paim",
) -> dict[str, Any]:
    return {
        "id": job.id,
        "title": job.title,
        "source_path": job.source_path,
        "rel_path": job.rel_path,
        "duration_sec": result.duration or job.duration_sec,
        "language": result.language,
        "language_probability": result.language_probability,
        "asr_model": result.model_name,
        "device": result.device,
        "compute_type": result.compute_type,
        "speaker_default": speaker_default,
        "segments": [
            {**s.to_dict(), "speaker": speaker_default} for s in result.segments
        ],
        "meta": job.meta,
    }


def write_transcript_outputs(
    job: VideoJob,
    result: TranscriptResult,
    out_dir: Path,
    *,
    keep_json: bool = True,
) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Flat safe filename from id + short slug
    slug = _safe_slug(job.title, max_len=60)
    base = f"{job.id}_{slug}" if slug else job.id
    md_path = out_dir / f"{base}.md"
    md_path.write_text(transcript_markdown(job, result), encoding="utf-8")
    if keep_json:
        json_path = out_dir / f"{base}.json"
        json_path.write_text(
            json.dumps(transcript_json(job, result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return md_path


def build_index(db: StateDB, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    jobs = [j for j in db.list_all() if j.status == "done" and j.transcript_path]
    lines = [
        "# Atlas Brasileiro — Video transcript index",
        "",
        f"Generated: {datetime.now(timezone.utc).replace(microsecond=0).isoformat()}",
        f"Done transcripts: {len(jobs)}",
        "",
        "| id | title | duration | transcript | asr_model |",
        "|----|-------|----------|------------|-----------|",
    ]
    for j in jobs:
        dur = duration_hms(j.duration_sec)
        tpath = Path(j.transcript_path).name if j.transcript_path else ""
        title = j.title.replace("|", "\\|")
        lines.append(
            f"| `{j.id}` | {title} | {dur} | `{tpath}` | {j.asr_model or ''} |"
        )
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def package_for_grok(
    db: StateDB,
    transcripts_dir: Path,
    out_dir: Path,
) -> Path:
    """Copy done transcripts + INDEX into a Grok upload folder."""
    import shutil

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest_tx = out_dir / "transcripts"
    dest_tx.mkdir(exist_ok=True)
    n = 0
    for j in db.list_all():
        if j.status != "done" or not j.transcript_path:
            continue
        src = Path(j.transcript_path)
        if src.exists():
            shutil.copy2(src, dest_tx / src.name)
            n += 1
            # optional companion json
            js = src.with_suffix(".json")
            if js.exists():
                shutil.copy2(js, dest_tx / js.name)
    build_index(db, out_dir / "INDEX.md")
    readme = out_dir / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# Grok upload pack — transcripts only",
                "",
                "Upload `INDEX.md` and files under `transcripts/`.",
                "Analysis Markdown is produced in a **later stage** after all ASR is done",
                "(avoids VRAM contention with large-v3).",
                "",
                f"Transcript files in this pack: {n}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return out_dir


def _safe_slug(text: str, max_len: int = 60) -> str:
    keep = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_"):
            keep.append(ch)
        elif ch.isspace() or ch in (":", ",", ".", "!", "?", "—", "–"):
            keep.append("-")
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:max_len]
