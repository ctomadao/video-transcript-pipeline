"""SQLite job state — resume-safe progress tracking."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class VideoJob:
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

    @property
    def meta(self) -> dict[str, Any]:
        if not self.meta_json:
            return {}
        return json.loads(self.meta_json)


class StateDB:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=120.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS videos (
                    id TEXT PRIMARY KEY,
                    source_path TEXT NOT NULL UNIQUE,
                    rel_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    duration_sec REAL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error TEXT,
                    asr_model TEXT,
                    transcript_path TEXT,
                    audio_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    meta_json TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status)"
            )

    def upsert_discovered(
        self,
        *,
        video_id: str,
        source_path: str,
        rel_path: str,
        size_bytes: int,
        mtime_ns: int,
        title: str,
        duration_sec: float | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        now = _utc_now()
        meta_json = json.dumps(meta or {}, ensure_ascii=False)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, status, size_bytes, mtime_ns FROM videos WHERE id = ?",
                (video_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO videos (
                        id, source_path, rel_path, size_bytes, mtime_ns, title,
                        duration_sec, status, created_at, updated_at, meta_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                    """,
                    (
                        video_id,
                        source_path,
                        rel_path,
                        size_bytes,
                        mtime_ns,
                        title,
                        duration_sec,
                        now,
                        now,
                        meta_json,
                    ),
                )
                return

            # File changed → re-queue for transcription unless user force-manages it.
            changed = row["size_bytes"] != size_bytes or row["mtime_ns"] != mtime_ns
            if changed:
                conn.execute(
                    """
                    UPDATE videos SET
                        source_path = ?, rel_path = ?, size_bytes = ?, mtime_ns = ?,
                        title = ?, duration_sec = COALESCE(?, duration_sec),
                        status = 'pending', error = NULL, updated_at = ?, meta_json = ?
                    WHERE id = ?
                    """,
                    (
                        source_path,
                        rel_path,
                        size_bytes,
                        mtime_ns,
                        title,
                        duration_sec,
                        now,
                        meta_json,
                        video_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE videos SET
                        source_path = ?, rel_path = ?, title = ?,
                        duration_sec = COALESCE(?, duration_sec),
                        updated_at = ?, meta_json = ?
                    WHERE id = ?
                    """,
                    (
                        source_path,
                        rel_path,
                        title,
                        duration_sec,
                        now,
                        meta_json,
                        video_id,
                    ),
                )

    def get(self, video_id: str) -> VideoJob | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM videos WHERE id = ?", (video_id,)
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list_by_status(self, status: str) -> list[VideoJob]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM videos WHERE status = ? ORDER BY rel_path",
                (status,),
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def jobs_by_ids(self, ids: set[str] | list[str]) -> list[VideoJob]:
        """Fetch jobs for a batch of ids (chunked for SQLite variable limits)."""
        id_list = list(ids)
        if not id_list:
            return []
        out: list[VideoJob] = []
        chunk_size = 400
        with self._conn() as conn:
            for i in range(0, len(id_list), chunk_size):
                chunk = id_list[i : i + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT * FROM videos WHERE id IN ({placeholders})",
                    chunk,
                ).fetchall()
                out.extend(self._row_to_job(r) for r in rows)
        return out

    def list_all(self) -> list[VideoJob]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM videos ORDER BY rel_path"
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def counts(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM videos GROUP BY status"
            ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def total(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM videos").fetchone()
        return int(row["n"])

    def mark(
        self,
        video_id: str,
        status: str,
        *,
        error: str | None = None,
        asr_model: str | None = None,
        transcript_path: str | None = None,
        audio_path: str | None = None,
        duration_sec: float | None = None,
    ) -> None:
        now = _utc_now()
        fields = ["status = ?", "updated_at = ?", "error = ?"]
        values: list[Any] = [status, now, error]
        if asr_model is not None:
            fields.append("asr_model = ?")
            values.append(asr_model)
        if transcript_path is not None:
            fields.append("transcript_path = ?")
            values.append(transcript_path)
        if audio_path is not None:
            fields.append("audio_path = ?")
            values.append(audio_path)
        if duration_sec is not None:
            fields.append("duration_sec = ?")
            values.append(duration_sec)
        values.append(video_id)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE videos SET {', '.join(fields)} WHERE id = ?",
                values,
            )

    def reset_failed_to_pending(self) -> int:
        now = _utc_now()
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE videos
                SET status = 'pending', error = NULL, updated_at = ?
                WHERE status = 'failed'
                """,
                (now,),
            )
            return cur.rowcount

    def reset_running_to_pending(self) -> int:
        """Re-queue jobs left in 'running' after a crash/interrupt."""
        now = _utc_now()
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE videos
                SET status = 'pending', error = NULL, updated_at = ?
                WHERE status = 'running'
                """,
                (now,),
            )
            return cur.rowcount

    def claim_pending(self, limit: int | None = None) -> list[VideoJob]:
        """Return pending jobs (oldest first). Caller marks running."""
        sql = "SELECT * FROM videos WHERE status = 'pending' ORDER BY rel_path"
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_job(r) for r in rows]

    def claim_one_pending(self) -> VideoJob | None:
        """
        Atomically take one pending job → running.
        Safe for multi-process workers (BEGIN IMMEDIATE + timeout).
        """
        now = _utc_now()
        conn = sqlite3.connect(self.path, timeout=120.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM videos
                WHERE status = 'pending'
                ORDER BY rel_path
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                conn.rollback()
                return None
            cur = conn.execute(
                """
                UPDATE videos
                SET status = 'running', error = NULL, updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (now, row["id"]),
            )
            if cur.rowcount != 1:
                conn.rollback()
                return None
            conn.commit()
            return self._row_to_job(row)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> VideoJob:
        return VideoJob(
            id=row["id"],
            source_path=row["source_path"],
            rel_path=row["rel_path"],
            size_bytes=row["size_bytes"],
            mtime_ns=row["mtime_ns"],
            title=row["title"],
            duration_sec=row["duration_sec"],
            status=row["status"],
            error=row["error"],
            asr_model=row["asr_model"],
            transcript_path=row["transcript_path"],
            audio_path=row["audio_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            meta_json=row["meta_json"],
        )
