# Video Transcript Pipeline — Atlas Brasileiro

Local, resume-safe batch transcription of **Kim Paim** videos (PT-BR) for the Grok project **Atlas Brasileiro**.

Runs on **Linux** and **Windows**. Same Python CLI after the venv is active.

**Stage policy:** finish **all** Whisper transcriptions (`large-v3-turbo` by default) **before** any Ollama analysis, so models do not fight for VRAM/RAM.

## Prerequisites

| Need | Linux | Windows |
|------|-------|---------|
| **Python 3.11+** | Distro package or [python.org](https://www.python.org/downloads/) | [python.org](https://www.python.org/downloads/) — tick **Add python.exe to PATH** |
| **ffmpeg** + **ffprobe** on `PATH` | `sudo apt install ffmpeg` (Debian/Ubuntu) or your package manager | `winget install Gyan.FFmpeg` then **open a new terminal**. Or install a [Gyan ffmpeg build](https://www.gyan.dev/ffmpeg/builds/) and add `bin` to PATH |
| **Git** | Distro package | [git-scm.com](https://git-scm.com/) or `winget install Git.Git` |
| **C++ runtime** | Usually already present | [Microsoft Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) (needed by CTranslate2 / faster-whisper) |
| **Video library** | Folder of `.mp4` / `.mkv` / … (Tartube layout is fine) | Same — **do not copy** the library into the repo |

Confirm tools:

```bash
python --version    # Windows: py -3 --version
ffmpeg -version
ffprobe -version
```

### GPU notes

| Hardware | Linux | Windows |
|----------|-------|---------|
| **NVIDIA** | CUDA if CTranslate2 sees it; otherwise CPU | Same. Install a recent [CUDA toolkit](https://developer.nvidia.com/cuda-downloads) that matches your driver if you want `--device cuda` |
| **AMD (ROCm)** | ROCm helps **Ollama**, not faster-whisper. This host is typically **CPU** for CTranslate2 | ROCm is not a Windows option. Use **CPU** (`--device cpu`) |
| **No GPU** | `--device cpu` | `--device cpu` |

`--device auto` already falls back to `cpu/int8` when CUDA is missing.

## Setup

Clone (or open) the repo, then create a venv **in the project root**.

### Linux

```bash
cd /path/to/video-transcript-pipeline
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .

mkdir -p data
# Link the library (no copy). Override the default path if yours differs.
ln -sfn "/home/clovis/Downloads/Tartube-new/Atlas Brasileiro - Kim Paim" data/input
# or: export VTP_VIDEO_ROOT="/your/library" && ln -sfn "$VTP_VIDEO_ROOT" data/input
```

### Windows (PowerShell)

If scripts are blocked once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

```powershell
cd C:\path\to\video-transcript-pipeline
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .

New-Item -ItemType Directory -Force -Path data | Out-Null
# Directory junction — no copy, no Administrator needed
New-Item -ItemType Junction -Path data\input -Target "D:\Videos\Atlas Brasileiro - Kim Paim"
```

Alternatively skip the junction and pass the library every time:

```powershell
$env:VTP_VIDEO_ROOT = "D:\Videos\Atlas Brasileiro - Kim Paim"
python -m vtp discover --input $env:VTP_VIDEO_ROOT
```

Long Tartube filenames: enable **Win32 long paths** (Group Policy or `LongPathsEnabled` in the registry) if discover/extract fails with path-too-long errors.

**cmd.exe** instead of PowerShell:

```bat
cd C:\path\to\video-transcript-pipeline
py -3 -m venv .venv
.venv\Scripts\activate.bat
pip install -e .
mkdir data
mklink /J data\input "D:\Videos\Atlas Brasileiro - Kim Paim"
```

## Run

Same commands on both OS after the venv is active (`source .venv/bin/activate` or `.\.venv\Scripts\Activate.ps1`).

```bash
python -m vtp discover
python -m vtp run --language pt
# or explicit:
python -m vtp run --model large-v3-turbo --workers 4 --cpu-threads 4 --device cpu
python -m vtp status
python -m vtp export --format grok
```

First run should be a **smoke test** (`--limit 3` on discover/run), not the full library.

Export writes `data/grok-upload/` (`INDEX.md`, `INSTRUCTIONS.md`, `README.md`, `packs/pack-NNN.md`). Upload those Markdown files into Atlas Brasileiro — not one file per video, and not a single huge zip if the project only half-indexes archives.

## CLI

| Command | Purpose |
|---------|---------|
| `python -m vtp discover` | Register videos under `data/input` (or `--input`) |
| `python -m vtp run` | ASR only (default **`large-v3-turbo`**, **4 workers**) |
| `python -m vtp export` | Bundled Grok packs (`packs/pack-NNN.md`) + INDEX |
| `python -m vtp status` | Job counts |
| `python -m vtp retry-failed` | Re-queue failures |
| `python -m vtp reset-running` | Re-queue stuck `running` after interrupt |
| `python -m vtp analyze` | Placeholder (post-ASR stage) |

### Parallelism

| Mode | Flags | Use when |
|------|-------|----------|
| Desktop-friendly | `--workers 2 --cpu-threads 6` | Multitasking |
| Overnight bulk | `--workers 4 --cpu-threads 4` | Default sweet spot (e.g. 7900X3D + ~64 GB) |
| Conservative (laptops) | `--workers 1 --cpu-threads 4` | Low RAM / first Windows install |

`run` auto-resets stuck **`running`** jobs unless you pass `--no-reset-running`.

On Windows, keep the venv activated in the **same** terminal that started `run`. Closing that window kills workers.

## Docs

- [Definition.md](./Definition.md) — setup path (Linux + Windows), layout, Grok packaging  
- [REQUIREMENTS.md](./REQUIREMENTS.md) — product requirements  
- [AGENTS.md](./AGENTS.md) — agent conventions  

## Notes

- **Whisper** = free local ASR via `faster-whisper` (not a paid API; not the Ollama chat model named “whisper”).
- Intermediate WAV files are deleted after a successful transcript unless `--keep-audio`.
- `data/input` may be a **symlink** (Linux) or a **directory junction** (Windows). Both are valid.
- Original development host: Linux, AMD GPU, CTranslate2 **CPU-only**. Other machines should pass `--device` and `--workers` that match their RAM/GPU.
