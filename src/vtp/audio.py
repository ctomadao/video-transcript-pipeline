"""Extract mono 16 kHz WAV via ffmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path


def probe_duration(source: Path) -> float | None:
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(source),
            ],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
        return float(out) if out else None
    except (subprocess.CalledProcessError, ValueError):
        return None


def extract_wav(
    source: Path,
    dest_wav: Path,
    *,
    sample_rate: int = 16000,
) -> Path:
    dest_wav = Path(dest_wav)
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(dest_wav),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed ({proc.returncode}): {proc.stderr[-2000:]}"
        )
    if not dest_wav.exists() or dest_wav.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg produced empty audio: {dest_wav}")
    return dest_wav
