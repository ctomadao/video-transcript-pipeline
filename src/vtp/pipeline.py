"""Orchestration: audio extract → ASR → export. Analysis is a separate later stage."""

from __future__ import annotations

import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rich.console import Console

from vtp.audio import extract_wav, probe_duration
from vtp.export import write_transcript_outputs
from vtp.progress import (
    ProgressMonitor,
    batch_snapshot,
    format_duration,
    format_progress_line,
)
from vtp.state import StateDB, VideoJob
from vtp.transcribe import (
    DEFAULT_ASR_MODEL,
    configure_thread_env,
    unload_models,
    transcribe_file,
)

console = Console()


@dataclass
class JobPayload:
    """Picklable job snapshot for worker processes."""

    id: str
    source_path: str
    rel_path: str
    size_bytes: int
    mtime_ns: int
    title: str
    duration_sec: float | None
    status: str
    error: str | None
    asr_model: str | None
    transcript_path: str | None
    audio_path: str | None
    created_at: str
    updated_at: str
    meta_json: str | None = None

    @classmethod
    def from_job(cls, job: VideoJob) -> JobPayload:
        return cls(
            id=job.id,
            source_path=job.source_path,
            rel_path=job.rel_path,
            size_bytes=job.size_bytes,
            mtime_ns=job.mtime_ns,
            title=job.title,
            duration_sec=job.duration_sec,
            status=job.status,
            error=job.error,
            asr_model=job.asr_model,
            transcript_path=job.transcript_path,
            audio_path=job.audio_path,
            created_at=job.created_at,
            updated_at=job.updated_at,
            meta_json=job.meta_json,
        )

    def to_job(self) -> VideoJob:
        return VideoJob(**asdict(self))


def process_one(
    job: VideoJob,
    db: StateDB,
    *,
    audio_dir: Path,
    transcripts_dir: Path,
    model_name: str = DEFAULT_ASR_MODEL,
    language: str = "pt",
    device: str = "auto",
    keep_audio: bool = False,
    beam_size: int = 5,
    cpu_threads: int = 4,
    already_running: bool = False,
    quiet: bool = False,
) -> bool:
    if not already_running:
        db.mark(job.id, "running")
    audio_path = Path(audio_dir) / f"{job.id}.wav"
    source = Path(job.source_path)

    try:
        if not source.exists():
            raise FileNotFoundError(f"Missing source: {source}")

        duration = job.duration_sec or probe_duration(source)
        if not quiet:
            console.print(
                f"[cyan]→[/cyan] {job.title[:70]}  "
                f"([dim]{job.id}[/dim], {duration or '?'}s)"
            )

        extract_wav(source, audio_path)
        result = transcribe_file(
            audio_path,
            model_name=model_name,
            language=language,
            device=device,
            beam_size=beam_size,
            cpu_threads=cpu_threads,
        )
        md_path = write_transcript_outputs(job, result, transcripts_dir)

        stored_audio: str | None
        if not keep_audio and audio_path.exists():
            audio_path.unlink(missing_ok=True)
            stored_audio = None
        else:
            stored_audio = str(audio_path)

        db.mark(
            job.id,
            "done",
            asr_model=result.model_name,
            transcript_path=str(md_path),
            audio_path=stored_audio,
            duration_sec=result.duration or duration,
            error=None,
        )
        if not quiet:
            console.print(
                f"[green]✓[/green] {len(result.segments)} segments → {md_path.name}"
            )
        return True
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        db.mark(job.id, "failed", error=err[:2000])
        if not quiet:
            console.print(f"[red]✗[/red] {job.id}: {err}")
            console.print(f"[dim]{traceback.format_exc()[-800:]}[/dim]")
        else:
            print(f"FAIL {job.id}: {err}", flush=True)
        if audio_path.exists() and not keep_audio:
            audio_path.unlink(missing_ok=True)
        return False


def _worker_entry(spec: dict[str, Any]) -> dict[str, Any]:
    """
    Process-pool entry: claim jobs until none left or local limit hit.
    Each worker loads its own Whisper model (via process_one → transcribe).
    """
    configure_thread_env(spec["cpu_threads"])
    db = StateDB(Path(spec["db_path"]))
    audio_dir = Path(spec["audio_dir"])
    transcripts_dir = Path(spec["transcripts_dir"])
    worker_id = spec["worker_id"]
    max_jobs = spec.get("max_jobs")  # optional per-worker cap (usually None)

    ok = 0
    failed = 0
    processed = 0

    while True:
        if max_jobs is not None and processed >= max_jobs:
            break
        job = db.claim_one_pending()
        if job is None:
            break
        print(
            f"[w{worker_id}] → {job.title[:60]} ({job.id})",
            flush=True,
        )
        success = process_one(
            job,
            db,
            audio_dir=audio_dir,
            transcripts_dir=transcripts_dir,
            model_name=spec["model_name"],
            language=spec["language"],
            device=spec["device"],
            keep_audio=spec["keep_audio"],
            beam_size=spec["beam_size"],
            cpu_threads=spec["cpu_threads"],
            already_running=True,
            quiet=True,
        )
        processed += 1
        if success:
            ok += 1
            print(f"[w{worker_id}] ✓ {job.id}", flush=True)
        else:
            failed += 1
            print(f"[w{worker_id}] ✗ {job.id}", flush=True)

    unload_models()
    return {
        "worker_id": worker_id,
        "ok": ok,
        "failed": failed,
        "processed": processed,
    }


def run_transcription(
    db: StateDB,
    *,
    audio_dir: Path,
    transcripts_dir: Path,
    model_name: str = DEFAULT_ASR_MODEL,
    language: str = "pt",
    device: str = "auto",
    limit: int | None = None,
    keep_audio: bool = False,
    beam_size: int = 5,
    unload_after: bool = True,
    workers: int = 1,
    cpu_threads: int = 4,
    reset_running: bool = True,
    progress_interval: float = 5.0,
) -> dict[str, int]:
    """
    Transcribe pending jobs. Analysis is intentionally NOT started here.

    workers>1 uses a process pool; each process claims jobs atomically and
    loads its own model. Prefer workers*cpu_threads ≈ 12–20 on a 12c/24t CPU.
    """
    audio_dir = Path(audio_dir)
    transcripts_dir = Path(transcripts_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    stats = {"ok": 0, "failed": 0, "skipped": 0, "reset_running": 0}

    if reset_running:
        n = db.reset_running_to_pending()
        stats["reset_running"] = n
        if n:
            console.print(
                f"[yellow]Reset {n} stuck running job(s) → pending[/yellow]"
            )
        # Recover any jobs left on temporary 'hold' from a crashed limited parallel run
        held = db.list_by_status("hold")
        for j in held:
            db.mark(j.id, "pending")
        if held:
            console.print(
                f"[yellow]Restored {len(held)} held job(s) → pending[/yellow]"
            )

    jobs = db.list_by_status("pending")
    if limit is not None:
        jobs = jobs[:limit]
    if not jobs:
        console.print("[yellow]No pending videos.[/yellow]")
        return stats

    n_jobs = len(jobs)
    batch_ids = {j.id for j in jobs}
    workers = max(1, int(workers))
    cpu_threads = max(1, int(cpu_threads))
    t0 = time.monotonic()

    console.print(
        f"[bold]Transcribing up to {n_jobs} video(s)[/bold] "
        f"with [bold]{model_name}[/bold] "
        f"(device={device}, lang={language}, workers={workers}, "
        f"cpu_threads={cpu_threads})"
    )
    console.print(
        "[dim]Stage policy: ASR only — analysis runs after all transcriptions complete.[/dim]"
    )
    console.print(
        f"[dim]Progress every {progress_interval:.0f}s: "
        f"bar, done/run/pend/fail, elapsed, ETA, active titles.[/dim]"
    )

    if workers == 1:
        configure_thread_env(cpu_threads)
        for i, job in enumerate(jobs, start=1):
            console.print(
                f"[dim]job {i}/{n_jobs}[/dim] "
                f"{job.title[:60] or job.id}"
            )
            ok = process_one(
                job,
                db,
                audio_dir=audio_dir,
                transcripts_dir=transcripts_dir,
                model_name=model_name,
                language=language,
                device=device,
                keep_audio=keep_audio,
                beam_size=beam_size,
                cpu_threads=cpu_threads,
            )
            if ok:
                stats["ok"] += 1
            else:
                stats["failed"] += 1
            snap = batch_snapshot(db, batch_ids)
            console.print(
                format_progress_line(snap, elapsed=time.monotonic() - t0),
                style="blue",
                markup=False,
                highlight=False,
            )
        if unload_after:
            unload_models()
            console.print(
                "[dim]ASR model cache cleared (ready for later analysis stage).[/dim]"
            )
    else:
        # When limit < all pending, park the rest so workers only claim the batch.
        frozen_ids: list[str] = []
        if limit is not None:
            selected_ids = {j.id for j in jobs}
            for j in db.list_by_status("pending"):
                if j.id not in selected_ids:
                    db.mark(j.id, "hold")
                    frozen_ids.append(j.id)

        monitor = ProgressMonitor(
            db.path,
            batch_ids,
            interval=progress_interval,
            start_time=t0,
        )
        try:
            specs = [
                {
                    "worker_id": i,
                    "db_path": str(db.path),
                    "audio_dir": str(audio_dir),
                    "transcripts_dir": str(transcripts_dir),
                    "model_name": model_name,
                    "language": language,
                    "device": device,
                    "keep_audio": keep_audio,
                    "beam_size": beam_size,
                    "cpu_threads": cpu_threads,
                    "max_jobs": None,
                }
                for i in range(workers)
            ]
            monitor.start()
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_worker_entry, s) for s in specs]
                for fut in as_completed(futures):
                    result = fut.result()
                    stats["ok"] += result["ok"]
                    stats["failed"] += result["failed"]
                    console.print(
                        f"[dim]worker {result['worker_id']} finished: "
                        f"ok={result['ok']} failed={result['failed']} "
                        f"processed={result['processed']}[/dim]"
                    )
        finally:
            monitor.stop()
            for vid in frozen_ids:
                db.mark(vid, "pending")

    elapsed = time.monotonic() - t0
    final = batch_snapshot(db, batch_ids)
    console.print(
        f"[bold]Done.[/bold] ok={stats['ok']} failed={stats['failed']} "
        f"wall={format_duration(elapsed)}"
    )
    console.print(
        format_progress_line(final, elapsed=elapsed),
        style="blue",
        markup=False,
        highlight=False,
    )
    return stats

