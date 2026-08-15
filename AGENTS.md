# AGENTS.md

## Goal

CLI utility that batch-transcribes **Kim Paim** videos (PT-BR), produces structured
transcripts and deep analytical Markdown, and packages outputs for the Grok
project **Atlas Brasileiro** (monthly books already ingested from 2023/10).

See [REQUIREMENTS.md](./REQUIREMENTS.md) for full requirements and
[Definition.md](./Definition.md) for Linux **and** Windows setup.

## Constraints

- Resume-safe (skip already-done files)
- Idempotent outputs
- Never re-encode video unless extracting audio is required
- Prefer local STT + local Ollama LLM over cloud for bulk cost/privacy
- **ASR first, analysis later** — never co-load Whisper + Ollama (VRAM/RAM)
- Default ASR: **faster-whisper `large-v3-turbo`**, language `pt`, **4 workers** / 4 cpu_threads
- Parallel workers claim jobs atomically from SQLite; auto-reset stuck `running` on `run`
- GPU stages sequential vs analysis; original Linux host: CTranslate2 is **CPU-only** (no usable CUDA)
- Windows: NVIDIA may use `--device cuda`; AMD GPUs have **no ROCm** — use `--device cpu`
- Link `data/input` → video library (Linux symlink **or** Windows directory junction); do not copy the library
- Perfect punctuation is not required
- Narrator/author default label: **Kim Paim**
- Grok upload: bundled `packs/pack-NNN.md` + INDEX + INSTRUCTIONS (not 2000 loose files, not one huge zip)

## Stack hints

- Video root (original host): `/home/clovis/Downloads/Tartube-new/Atlas Brasileiro - Kim Paim`
- Override with `VTP_VIDEO_ROOT` or `vtp discover --input …`
- ASR: `faster-whisper` (not Ollama; not paid API)
- Ollama: `http://localhost:11434` (analysis stage only, post-ASR; Linux/ROCm inventory in REQUIREMENTS)
- Analysis models: Qwen3.6 APEX I-Mini / Compact / q3; embeddings: `bge-m3`
- Language: pt-BR
- CLI: `python -m vtp discover|run|export|status|retry-failed`
- ffmpeg + ffprobe must be on `PATH` (Linux packages or Windows winget `Gyan.FFmpeg`)
