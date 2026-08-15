"""Default paths for the pipeline workspace."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DEFAULT_INPUT = DATA_DIR / "input"
DEFAULT_AUDIO = DATA_DIR / "audio"
DEFAULT_TRANSCRIPTS = DATA_DIR / "transcripts"
DEFAULT_GROK = DATA_DIR / "grok-upload"
DEFAULT_DB = DATA_DIR / "state.db"

# Source library (main storage). Link data/input → this path (symlink or junction).
# Override with VTP_VIDEO_ROOT when the library lives somewhere else (Windows/Linux).
DEFAULT_VIDEO_ROOT = Path(
    os.environ.get(
        "VTP_VIDEO_ROOT",
        "/home/clovis/Downloads/Tartube-new/Atlas Brasileiro - Kim Paim",
    )
)

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".mov",
    ".webm",
    ".m4v",
    ".avi",
    ".ts",
    ".flv",
}
