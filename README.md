# Video Transcript Pipeline — Atlas Brasileiro

Local, resume-safe batch transcription of **Kim Paim** videos (PT-BR) for the Grok project **Atlas Brasileiro**.

**Stage policy:** finish **all** Whisper transcriptions (`large-v3` by default) **before** any Ollama analysis, so models do not fight for VRAM/RAM.

## Quick start

```bash
cd /mnt/data/github/video-transcript-pipeline
source .venv/bin/activate
pip install -e .

# Link video library (no copy)
mkdir -p data
ln -sfn "/home/clovis/Downloads/Tartube-new/Atlas Brasileiro - Kim Paim" data/input

# Discover + transcribe (defaults: large-v3-turbo, 4 workers)
python -m vtp discover
python -m vtp run --language pt
# or explicit:
python -m vtp run --model large-v3-turbo --workers 4 --cpu-threads 4 --device cpu
python -m vtp status
python -m vtp export --format grok
```

## CLI

| Command | Purpose |
|---------|---------|
| `python -m vtp discover` | Register videos under `data/input` |
| `python -m vtp run` | ASR only (default **`large-v3-turbo`**, **4 workers**) |
| `python -m vtp export` | INDEX + Grok pack |
| `python -m vtp status` | Job counts |
| `python -m vtp retry-failed` | Re-queue failures |
| `python -m vtp reset-running` | Re-queue stuck `running` after interrupt |
| `python -m vtp analyze` | Placeholder (post-ASR stage) |

### Parallelism (7900X3D + ~64 GB)

| Mode | Flags | Use when |
|------|-------|----------|
| Desktop-friendly | `--workers 2 --cpu-threads 6` | Multitasking |
| Overnight bulk | `--workers 4 --cpu-threads 4` | Default sweet spot |
| Aggressive | `--workers 6 --cpu-threads 3` | Max throughput experiment |

`run` auto-resets stuck **`running`** jobs unless you pass `--no-reset-running`.

## Docs

- [REQUIREMENTS.md](./REQUIREMENTS.md) — product requirements  
- [Definition.md](./Definition.md) — original setup notes  
- [AGENTS.md](./AGENTS.md) — agent conventions  

## Notes

- **Whisper** = free local ASR via `faster-whisper` (not a paid API; not the Ollama chat model named “whisper”).
- On this ROCm host, CTranslate2 may only support **CPU** today; GPU is used when CUDA compute types are available.
- Intermediate WAV files are deleted after successful transcript unless `--keep-audio`.
