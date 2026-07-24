# AGENTS.md

## Goal

CLI utility that batch-transcribes **Kim Paim** videos (PT-BR), produces structured
transcripts and deep analytical Markdown, and packages outputs for the Grok
project **Atlas Brasileiro** (monthly books already ingested from 2023/10).

See [REQUIREMENTS.md](./REQUIREMENTS.md) for full requirements and
[Definition.md](./Definition.md) for setup path.

## Constraints

- Resume-safe (skip already-done files)
- Idempotent outputs
- Never re-encode video unless extracting audio is required
- Prefer local STT + local Ollama LLM over cloud for bulk cost/privacy
- **ASR first, analysis later** — never co-load Whisper + Ollama (VRAM/RAM)
- Default ASR: **faster-whisper `large-v3-turbo`**, language `pt`, **4 workers** / 4 cpu_threads
- Parallel workers claim jobs atomically from SQLite; auto-reset stuck `running` on `run`
- GPU stages sequential vs analysis; on this host CTranslate2 is **CPU-only** (no usable CUDA)
- Symlink `data/input` → video library is valid; do not copy the library
- Perfect punctuation is not required
- Narrator/author default label: **Kim Paim**
- Prefer analyses + INDEX for Grok upload; full transcripts selectively (books already ~3.5 GB)

## Stack hints

- Video root: `/home/clovis/Downloads/Tartube-new/Atlas Brasileiro - Kim Paim`
- ASR: `faster-whisper` (not Ollama; not paid API)
- Ollama: `http://localhost:11434` (analysis stage only, post-ASR)
- Analysis models: Qwen3.6 APEX I-Mini / Compact / q3; embeddings: `bge-m3`
- Language: pt-BR
- CLI: `python -m vtp discover|run|export|status|retry-failed`
