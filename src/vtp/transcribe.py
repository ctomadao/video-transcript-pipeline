"""ASR via faster-whisper. Default bulk model: large-v3-turbo."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel

DEFAULT_ASR_MODEL = "large-v3-turbo"


@dataclass
class Segment:
    start: float
    end: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "text": self.text}


@dataclass
class TranscriptResult:
    language: str
    language_probability: float
    duration: float | None
    segments: list[Segment]
    model_name: str
    device: str
    compute_type: str


_model_cache: dict[tuple[Any, ...], WhisperModel] = {}


def resolve_device(preferred: str = "auto") -> tuple[str, str]:
    """
    Return (device, compute_type).

    faster-whisper/CTranslate2 uses NVIDIA CUDA, not ROCm. On AMD hosts (or
    machines with broken CUDA stubs), prefer CPU unless CUDA compute types
    probe cleanly.
    """
    if preferred == "cpu":
        return "cpu", "int8"
    if preferred == "cuda":
        return "cuda", "float16"

    try:
        import ctranslate2

        types = ctranslate2.get_supported_compute_types("cuda")
        if not types:
            return "cpu", "int8"
        ct = "float16" if "float16" in types else (
            "int8_float16" if "int8_float16" in types else "default"
        )
        return "cuda", ct
    except Exception:
        return "cpu", "int8"


def get_model(
    model_name: str = DEFAULT_ASR_MODEL,
    *,
    device: str = "auto",
    compute_type: str | None = None,
    cpu_threads: int = 4,
) -> tuple[WhisperModel, str, str]:
    dev, default_ct = resolve_device(device)
    ct = compute_type or default_ct
    key = (model_name, dev, ct, cpu_threads)

    if key not in _model_cache:
        kwargs: dict[str, Any] = {
            "device": dev,
            "compute_type": ct,
        }
        if dev == "cpu":
            kwargs["cpu_threads"] = max(1, int(cpu_threads))
            # Avoid extra internal workers competing with process-level parallelism.
            kwargs["num_workers"] = 1
        try:
            _model_cache[key] = WhisperModel(model_name, **kwargs)
        except Exception as exc:
            msg = str(exc).lower()
            if dev != "cpu" and ("cuda" in msg or "cudnn" in msg or "cublas" in msg):
                dev, ct = "cpu", "int8"
                key = (model_name, dev, ct, cpu_threads)
                if key not in _model_cache:
                    _model_cache[key] = WhisperModel(
                        model_name,
                        device=dev,
                        compute_type=ct,
                        cpu_threads=max(1, int(cpu_threads)),
                        num_workers=1,
                    )
            else:
                raise
    return _model_cache[key], dev, ct


def unload_models() -> None:
    """Drop cached ASR models so VRAM/RAM can be freed before analysis stage."""
    _model_cache.clear()


def format_ts(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def transcribe_file(
    audio_path: Path,
    *,
    model_name: str = DEFAULT_ASR_MODEL,
    language: str = "pt",
    device: str = "auto",
    compute_type: str | None = None,
    beam_size: int = 5,
    vad_filter: bool = True,
    cpu_threads: int = 4,
) -> TranscriptResult:
    model, dev, ct = get_model(
        model_name,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
    )
    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=beam_size,
        vad_filter=vad_filter,
        word_timestamps=False,
    )
    segments = [
        Segment(start=s.start, end=s.end, text=s.text.strip())
        for s in segments_iter
        if s.text and s.text.strip()
    ]
    return TranscriptResult(
        language=info.language or language,
        language_probability=float(getattr(info, "language_probability", 0.0) or 0.0),
        duration=float(info.duration) if getattr(info, "duration", None) else None,
        segments=segments,
        model_name=model_name,
        device=dev,
        compute_type=ct,
    )


def configure_thread_env(cpu_threads: int) -> None:
    """Limit BLAS/OMP threads per process so parallel workers do not thrash."""
    n = str(max(1, int(cpu_threads)))
    for key in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ.setdefault(key, n)
