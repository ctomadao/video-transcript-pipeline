"""Simple batch progress reporting for ASR runs."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from rich.console import Console

from vtp.state import StateDB

console = Console()


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds != seconds:  # NaN
        return "?"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def render_bar(done: int, total: int, width: int = 24) -> str:
    """ASCII bar — avoid '#' (Rich markup) and keep it terminal-safe."""
    if total <= 0:
        return "[" + ("." * width) + "]"
    frac = min(1.0, max(0.0, done / total))
    filled = int(round(frac * width))
    return "[" + ("=" * filled) + ("." * (width - filled)) + "]"


def batch_snapshot(db: StateDB, batch_ids: set[str]) -> dict:
    """Counts and running titles for the current batch only."""
    counts = {"pending": 0, "running": 0, "done": 0, "failed": 0, "other": 0}
    running_titles: list[str] = []
    audio_done = 0.0
    audio_total = 0.0

    for job in db.jobs_by_ids(batch_ids):
        st = job.status
        if st in counts:
            counts[st] += 1
        else:
            counts["other"] += 1
        if job.duration_sec:
            audio_total += float(job.duration_sec)
            if st == "done":
                audio_done += float(job.duration_sec)
        if st == "running":
            running_titles.append(job.title[:48] or job.id)

    finished = counts["done"] + counts["failed"]
    return {
        "counts": counts,
        "finished": finished,
        "total": len(batch_ids),
        "running_titles": running_titles,
        "audio_done": audio_done,
        "audio_total": audio_total,
    }


def format_progress_line(
    snap: dict,
    *,
    elapsed: float,
    prefix: str = "progress",
) -> str:
    total = snap["total"]
    finished = snap["finished"]
    c = snap["counts"]
    bar = render_bar(finished, total)
    pct = (100.0 * finished / total) if total else 0.0

    # ETA from finished jobs (wall clock)
    eta_s: float | None = None
    if finished > 0 and finished < total and elapsed > 0:
        rate = finished / elapsed  # jobs per second
        remaining = total - finished
        eta_s = remaining / rate if rate > 0 else None

    # Prefer audio-based ETA when durations known for finished + remaining
    audio_done = snap["audio_done"]
    audio_total = snap["audio_total"]
    if audio_done > 30 and audio_total > audio_done and elapsed > 0:
        audio_rate = audio_done / elapsed  # audio-seconds per wall-second
        audio_left = audio_total - audio_done
        # Running jobs still contribute unknown progress; ETA is rough.
        eta_audio = audio_left / audio_rate if audio_rate > 0 else None
        if eta_audio is not None:
            eta_s = eta_audio

    run_preview = ""
    if snap["running_titles"]:
        run_preview = " | " + "; ".join(snap["running_titles"][:3])
        if len(snap["running_titles"]) > 3:
            run_preview += "…"

    return (
        f"{prefix} {bar} {finished}/{total} ({pct:5.1f}%) "
        f"| done={c['done']} run={c['running']} pend={c['pending']} fail={c['failed']} "
        f"| elapsed {format_duration(elapsed)} "
        f"| ETA ~{format_duration(eta_s)}"
        f"{run_preview}"
    )


class ProgressMonitor:
    """Background poller that prints a progress line while workers run."""

    def __init__(
        self,
        db_path: Path,
        batch_ids: set[str],
        *,
        interval: float = 5.0,
        start_time: float | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.batch_ids = set(batch_ids)
        self.interval = max(1.0, float(interval))
        self.start_time = start_time if start_time is not None else time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_line = ""

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, name="vtp-progress", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.interval + 2)
        # Final snapshot
        self._emit(force=True)

    def _loop(self) -> None:
        # First line almost immediately so the user sees activity
        self._emit(force=True)
        while not self._stop.wait(self.interval):
            self._emit(force=False)

    def _emit(self, *, force: bool) -> None:
        try:
            db = StateDB(self.db_path)
            snap = batch_snapshot(db, self.batch_ids)
            elapsed = time.monotonic() - self.start_time
            line = format_progress_line(snap, elapsed=elapsed)
            if force or line != self._last_line:
                # markup=False so titles/bars never break Rich rendering
                console.print(line, style="blue", markup=False, highlight=False)
                self._last_line = line
        except Exception as exc:
            console.print(f"progress error: {exc}", style="dim", markup=False)
