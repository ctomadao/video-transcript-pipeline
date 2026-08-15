"""CLI entrypoint: vtp discover | run | export | status | retry-failed | reset-running."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from vtp import __version__
from vtp.discover import discover
from vtp.export import build_index, package_for_grok
from vtp.paths import (
    DEFAULT_AUDIO,
    DEFAULT_DB,
    DEFAULT_GROK,
    DEFAULT_INPUT,
    DEFAULT_TRANSCRIPTS,
    DEFAULT_VIDEO_ROOT,
)
from vtp.pipeline import run_transcription
from vtp.state import StateDB
from vtp.transcribe import DEFAULT_ASR_MODEL, resolve_device

console = Console()


def _db(path: Path) -> StateDB:
    return StateDB(path)


@click.group()
@click.version_option(__version__, prog_name="vtp")
def main() -> None:
    """Video Transcript Pipeline — Atlas Brasileiro (transcription first, analysis later)."""


@main.command("discover")
@click.option(
    "--input",
    "input_root",
    type=click.Path(path_type=Path),
    default=DEFAULT_INPUT,
    show_default=True,
    help="Video root (symlink or Windows directory junction is fine).",
)
@click.option(
    "--db",
    "db_path",
    type=click.Path(path_type=Path),
    default=DEFAULT_DB,
    show_default=True,
)
@click.option("--limit", type=int, default=None, help="Max files to register (smoke tests).")
def cmd_discover(input_root: Path, db_path: Path, limit: int | None) -> None:
    """Scan input for videos and register pending jobs."""
    if not input_root.exists():
        raise click.ClickException(
            f"Input not found: {input_root}\n"
            "Point at the video library without copying it:\n"
            f"  Linux:   ln -sfn '{DEFAULT_VIDEO_ROOT}' '{DEFAULT_INPUT}'\n"
            "  Windows: New-Item -ItemType Junction -Path data\\input "
            f"-Target '{DEFAULT_VIDEO_ROOT}'\n"
            "Or pass --input / set VTP_VIDEO_ROOT to the library folder."
        )
    db = _db(db_path)
    n = discover(input_root, db, limit=limit)
    console.print(f"Discovered/updated [bold]{n}[/bold] video(s). DB: {db_path}")
    _print_counts(db)


@main.command("run")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option("--audio-dir", type=click.Path(path_type=Path), default=DEFAULT_AUDIO)
@click.option(
    "--export-dir",
    "transcripts_dir",
    type=click.Path(path_type=Path),
    default=DEFAULT_TRANSCRIPTS,
)
@click.option(
    "--model",
    "model_name",
    default=DEFAULT_ASR_MODEL,
    show_default=True,
    help="Whisper model (faster-whisper). Prefer large-v3-turbo for bulk.",
)
@click.option("--language", default="pt", show_default=True)
@click.option(
    "--device",
    default="auto",
    show_default=True,
    type=click.Choice(["auto", "cpu", "cuda"], case_sensitive=False),
)
@click.option("--limit", type=int, default=None, help="Max pending jobs this run.")
@click.option(
    "--workers",
    type=int,
    default=4,
    show_default=True,
    help="Parallel ASR processes (1 = sequential). Suggest 2–6 on 7900X3D.",
)
@click.option(
    "--cpu-threads",
    type=int,
    default=4,
    show_default=True,
    help="CTranslate2 CPU threads per worker. Aim workers*threads ≈ 12–20.",
)
@click.option("--keep-audio/--no-keep-audio", default=False, show_default=True)
@click.option("--beam-size", type=int, default=5, show_default=True)
@click.option(
    "--reset-running/--no-reset-running",
    default=True,
    show_default=True,
    help="Re-queue stuck 'running' jobs from an interrupted previous run.",
)
@click.option(
    "--progress-interval",
    type=float,
    default=5.0,
    show_default=True,
    help="Seconds between progress lines (parallel runs). Sequential prints after each job.",
)
def cmd_run(
    db_path: Path,
    audio_dir: Path,
    transcripts_dir: Path,
    model_name: str,
    language: str,
    device: str,
    limit: int | None,
    workers: int,
    cpu_threads: int,
    keep_audio: bool,
    beam_size: int,
    reset_running: bool,
    progress_interval: float,
) -> None:
    """Transcribe pending videos only (no analysis — avoids VRAM conflicts)."""
    db = _db(db_path)
    dev, ct = resolve_device(device)
    console.print(
        f"Preferred device: [bold]{dev}[/bold] compute_type=[bold]{ct}[/bold] "
        f"(falls back to cpu/int8 if CUDA init fails)"
    )
    if workers * cpu_threads > 24:
        console.print(
            f"[yellow]Warning:[/yellow] workers×cpu_threads="
            f"{workers * cpu_threads} > 24 logical CPUs; may thrash."
        )
    run_transcription(
        db,
        audio_dir=audio_dir,
        transcripts_dir=transcripts_dir,
        model_name=model_name,
        language=language,
        device=device,
        limit=limit,
        keep_audio=keep_audio,
        beam_size=beam_size,
        unload_after=True,
        workers=workers,
        cpu_threads=cpu_threads,
        reset_running=reset_running,
        progress_interval=progress_interval,
    )
    _print_counts(db)


@main.command("export")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option(
    "--transcripts-dir",
    type=click.Path(path_type=Path),
    default=DEFAULT_TRANSCRIPTS,
)
@click.option(
    "--out",
    "out_dir",
    type=click.Path(path_type=Path),
    default=DEFAULT_GROK,
    show_default=True,
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["grok", "index"], case_sensitive=False),
    default="grok",
    show_default=True,
)
@click.option(
    "--include-json/--no-include-json",
    default=False,
    show_default=True,
    help="Ignored for grok packs (JSON is local-only).",
)
@click.option(
    "--bundle-max-mb",
    type=float,
    default=6.0,
    show_default=True,
    help="Max UTF-8 size of each packs/pack-NNN.md (Grok project upload).",
)
def cmd_export(
    db_path: Path,
    transcripts_dir: Path,
    out_dir: Path,
    fmt: str,
    include_json: bool,
    bundle_max_mb: float,
) -> None:
    """Build INDEX and bundled timestamped Grok packs (video id + [HH:MM:SS] per line)."""
    db = _db(db_path)
    if fmt == "index":
        path = build_index(db, out_dir / "INDEX.md")
        console.print(f"Wrote {path}")
    else:
        path = package_for_grok(
            db,
            transcripts_dir,
            out_dir,
            include_json=include_json,
            bundle_max_mb=bundle_max_mb,
        )
        console.print(f"Grok pack ready: {path}")


@main.command("status")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option("--failed", is_flag=True, help="List failed jobs.")
def cmd_status(db_path: Path, failed: bool) -> None:
    """Show job counts and optional failure details."""
    if not db_path.exists():
        console.print(f"[yellow]No DB yet:[/yellow] {db_path}")
        return
    db = _db(db_path)
    _print_counts(db)
    if failed:
        rows = db.list_by_status("failed")
        if not rows:
            console.print("No failures.")
            return
        table = Table(title="Failed jobs")
        table.add_column("id")
        table.add_column("title")
        table.add_column("error")
        for j in rows[:50]:
            table.add_row(j.id, j.title[:40], (j.error or "")[:80])
        console.print(table)


@main.command("retry-failed")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB)
def cmd_retry_failed(db_path: Path) -> None:
    """Reset failed jobs to pending."""
    db = _db(db_path)
    n = db.reset_failed_to_pending()
    console.print(f"Reset [bold]{n}[/bold] failed job(s) to pending.")
    _print_counts(db)


@main.command("reset-running")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB)
def cmd_reset_running(db_path: Path) -> None:
    """Reset stuck running jobs to pending (after interrupt/crash)."""
    db = _db(db_path)
    n = db.reset_running_to_pending()
    console.print(f"Reset [bold]{n}[/bold] running job(s) to pending.")
    _print_counts(db)


@main.command("analyze")
def cmd_analyze() -> None:
    """Placeholder: run only after all transcriptions are done (separate stage)."""
    raise click.ClickException(
        "Analysis stage not implemented yet.\n"
        "Policy: finish ALL transcriptions first, unload ASR, then analyze via Ollama.\n"
        "See REQUIREMENTS.md Phase 2."
    )


def _print_counts(db: StateDB) -> None:
    counts = db.counts()
    total = db.total()
    table = Table(title=f"Jobs (total={total})")
    table.add_column("status")
    table.add_column("count", justify="right")
    for status in ("pending", "running", "hold", "done", "failed"):
        if status in counts:
            table.add_row(status, str(counts[status]))
    for status, n in sorted(counts.items()):
        if status not in {"pending", "running", "hold", "done", "failed"}:
            table.add_row(status, str(n))
    console.print(table)


if __name__ == "__main__":
    main()
