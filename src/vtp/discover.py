"""Discover video files under an input root."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from vtp.paths import VIDEO_EXTENSIONS
from vtp.state import StateDB

# Tartube-style: {youtubeId 11 chars}-{title}-NA.ext
# YouTube ids are 11 chars from [A-Za-z0-9_-]; do not use greedy [A-Za-z0-9_-]+
# or the id group swallows the title (e.g. "...-Sinais-NA" → title "NA").
_YT_PREFIX = re.compile(r"^([A-Za-z0-9_-]{11})-(.+?)(?:-NA)?$")


def stable_id(source_path: Path, size_bytes: int, mtime_ns: int) -> str:
    """Stable-ish id from path + size + mtime (detects renames poorly but is cheap)."""
    raw = f"{source_path.resolve()}|{size_bytes}|{mtime_ns}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def parse_title(path: Path) -> tuple[str, str | None]:
    """Return (display_title, youtube_id_or_none)."""
    stem = path.stem
    m = _YT_PREFIX.match(stem)
    if m:
        title = m.group(2).strip()
        # Strip trailing -NA if non-greedy left it in
        if title.endswith("-NA"):
            title = title[:-3].rstrip("-")
        return title or stem, m.group(1)
    # Fallback: strip trailing -NA from Tartube names
    if stem.endswith("-NA"):
        return stem[:-3], None
    return stem, None


def iter_videos(input_root: Path) -> list[Path]:
    root = Path(input_root).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Input root does not exist: {root}")
    found: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
            found.append(p)
    return found


def discover(
    input_root: Path,
    db: StateDB,
    *,
    limit: int | None = None,
) -> int:
    """Scan input root and upsert into state DB. Returns number of files seen."""
    root = Path(input_root).resolve()
    videos = iter_videos(root)
    if limit is not None:
        videos = videos[:limit]

    count = 0
    for path in videos:
        st = path.stat()
        rel = str(path.relative_to(root))
        title, yt_id = parse_title(path)
        vid = stable_id(path, st.st_size, st.st_mtime_ns)
        db.upsert_discovered(
            video_id=vid,
            source_path=str(path),
            rel_path=rel,
            size_bytes=st.st_size,
            mtime_ns=st.st_mtime_ns,
            title=title,
            meta={"youtube_id": yt_id} if yt_id else {},
        )
        count += 1
    return count
