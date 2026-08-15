# Definition and setup — Atlas Brasileiro video pipeline

Practical path from a clone of this repo → local transcription CLI → files you upload to the Grok Account Project **Atlas Brasileiro**.

Works on **Linux** and **Windows**. See [README.md](./README.md) for a shorter command list.

## What you are running (two different “projects”)

| Layer | What it is | Purpose |
|--------|------------|---------|
| **Local repo** (this folder) | Transcription utility (`python -m vtp`) | Process 2000+ videos offline, write Markdown |
| **Grok Project** ([grok.com/project](https://grok.com/project)) | Web workspace + custom instructions + uploaded files | Chat against books + transcripts |

The IDE (Zed, VS Code, Cursor, etc.) is only for developing the utility. The Grok Account Project is where you upload **outputs** (text), not the raw videos.

---

## 1. Prerequisites

### Both operating systems

- **Python 3.11+**
- **ffmpeg** and **ffprobe** on `PATH` (the CLI calls them by name)
- **Git**
- A **video library** on disk (Tartube-style `{youtubeId}-{title}-NA.mp4` is the expected layout). Do **not** copy the library into `data/`.

### Linux

```bash
# Debian / Ubuntu
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg git
```

Optional: ROCm for **Ollama** on AMD GPUs (analysis stage later). **faster-whisper / CTranslate2 does not use ROCm** — on the original AMD host ASR is CPU. NVIDIA CUDA is used when `ctranslate2.get_supported_compute_types("cuda")` succeeds.

### Windows

1. Install [Python 3.11+](https://www.python.org/downloads/). Enable **Add python.exe to PATH**.
2. Install [Git for Windows](https://git-scm.com/download/win).
3. Install ffmpeg so `ffmpeg` and `ffprobe` work in a **new** terminal:

   ```powershell
   winget install Gyan.FFmpeg
   ```

   Or unzip a [Gyan full build](https://www.gyan.dev/ffmpeg/builds/) and add its `bin` folder to the user PATH.
4. Install the [Microsoft Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) (CTranslate2 / faster-whisper).
5. Optional NVIDIA CUDA toolkit if you want `--device cuda`. **AMD GPUs on Windows: use CPU** (no ROCm).
6. If PowerShell refuses to activate the venv:

   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```

7. If extract/discover fails on very long Tartube names, enable Win32 long paths.

Check:

```text
python --version     # or: py -3 --version
ffmpeg -version
ffprobe -version
```

---

## 2. Create the virtualenv and install the package

### Linux

```bash
cd /path/to/video-transcript-pipeline
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

### Windows (PowerShell)

```powershell
cd C:\path\to\video-transcript-pipeline
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

### Windows (cmd)

```bat
cd C:\path\to\video-transcript-pipeline
py -3 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -e .
```

Stay inside the activated venv for every `python -m vtp …` command.

---

## 3. Point `data/input` at the video library

Never copy thousands of MP4s into the repo. Use a link, or pass `--input`.

Default library on the original Linux host:

`/home/clovis/Downloads/Tartube-new/Atlas Brasileiro - Kim Paim`

Override with env var `VTP_VIDEO_ROOT` or `--input`.

### Linux (symlink)

```bash
mkdir -p data
ln -sfn "/home/clovis/Downloads/Tartube-new/Atlas Brasileiro - Kim Paim" data/input
# or:
# ln -sfn "$VTP_VIDEO_ROOT" data/input
```

### Windows (directory junction — no Administrator)

PowerShell:

```powershell
New-Item -ItemType Directory -Force -Path data | Out-Null
New-Item -ItemType Junction -Path data\input -Target "D:\Videos\Atlas Brasileiro - Kim Paim"
```

cmd:

```bat
mkdir data
mklink /J data\input "D:\Videos\Atlas Brasileiro - Kim Paim"
```

A **junction** is the Windows equivalent of a directory symlink for this purpose. A true symlink (`mklink /D`) needs Developer Mode or an elevated shell; you do not need that.

### No link (either OS)

```bash
python -m vtp discover --input "/absolute/path/to/library"
```

```powershell
python -m vtp discover --input "D:\Videos\Atlas Brasileiro - Kim Paim"
```

---

## 4. Smoke test, then full run

Same CLI on both OS.

```bash
# 3 videos only
python -m vtp discover --limit 3
python -m vtp run --language pt --limit 3 --workers 1 --device cpu
python -m vtp status

# Full library (after smoke looks good)
python -m vtp discover
python -m vtp run --language pt --model large-v3-turbo --workers 4 --cpu-threads 4 --device auto
python -m vtp status
python -m vtp export --format grok
```

On a laptop or first Windows box, start with `--workers 1`. Linux overnight bulk on a 16-core CPU is typically `--workers 4 --cpu-threads 4`.

Bash-only helpers (`scripts/smoke_test.sh`, `scripts/smoke_turbo_parallel.sh`) assume a Unix shell. On Windows use the `python -m vtp` commands above, or run the scripts from **Git Bash** / **WSL** after adjusting `VIDEO_ROOT`.

`run` resets stuck `running` jobs unless you pass `--no-reset-running`.

---

## 5. Recommended utility design (already implemented)

### Stack

| Choice | Why |
|--------|-----|
| **Python 3.11+** | Media + ML ecosystem; works on Linux and Windows |
| **ffmpeg** | Extract/normalize audio; no full video re-encode |
| **faster-whisper** | Local, free at scale; CUDA on NVIDIA, else CPU |
| **SQLite** (`data/state.db`) | Resume, failures, retries |
| **Click** | CLI |

### Directory layout

```text
video-transcript-pipeline/
├── AGENTS.md
├── Definition.md           # this file
├── README.md
├── REQUIREMENTS.md
├── pyproject.toml
├── src/vtp/                # discover, audio, transcribe, export, state
├── data/                   # created locally (gitignored except .gitkeep)
│   ├── input/              # symlink (Linux) or junction (Windows) to the library
│   ├── audio/              # temporary wav (deleted unless --keep-audio)
│   ├── transcripts/        # per-video .md + .json (local)
│   ├── grok-upload/        # INDEX + INSTRUCTIONS + packs/pack-NNN.md
│   └── state.db
└── scripts/                # optional bash smokes; they recreate dirs under data/
```

### Pipeline stages

1. **Discover** — walk `data/input` for video extensions.  
2. **Stable id** — path + size + mtime.  
3. **Extract audio** — `ffmpeg` mono 16 kHz WAV.  
4. **Transcribe** — `faster-whisper`, language `pt`.  
5. **Export for Grok** — bundled Markdown packs + INDEX (see below).  
6. **Mark done** — only after the transcript write succeeds.

---

## 6. Format and package for Grok

Grok.com **Projects** choke on ~2000 loose files and only **partially** scan a single huge zip. This repo therefore exports **~48 Markdown packs** (~6 MB each) plus a catalog.

```bash
python -m vtp export --format grok --out data/grok-upload
```

Upload:

1. `data/grok-upload/INSTRUCTIONS.md` (also **paste** it into project custom instructions)  
2. `data/grok-upload/INDEX.md`  
3. `data/grok-upload/README.md`  
4. Every file under `data/grok-upload/packs/` (`pack-001.md` …)

Do **not** upload `data/transcripts/` (thousands of files) or rely on one zip of the whole corpus.

Each spoken line is:

```text
[youtubeId @ HH:MM:SS] spoken text
```

Watch URL: `https://www.youtube.com/watch?v={youtubeId}&t={seconds}s`

---

## 7. Create / update the Grok Account Project

On [grok.com](https://grok.com/) (signed in):

1. Open **Projects** → **Atlas Brasileiro** (or create it).  
2. Paste `data/grok-upload/INSTRUCTIONS.md` into **custom instructions**.  
3. Upload the files listed in §6.  
4. Chat only inside that project. Cite book location **or** video title + timestamp + YouTube link. If it is not in the files, the answer is that it is not in the corpus.

Books (~3.5 GB from 2023/10) stay in the project. Transcripts **complement** them.

For programmatic RAG at true corpus scale, xAI **Collections** (API/console) is the other path. A grok.com project zip does **not** unzip itself into one indexed file per video.

---

## 8. First-session checklist

| Step | Linux | Windows |
|------|-------|---------|
| Tools on PATH | `ffmpeg -version` | New terminal after winget |
| Venv | `source .venv/bin/activate` | `.\.venv\Scripts\Activate.ps1` |
| Library link | `ln -sfn … data/input` | `New-Item -ItemType Junction …` |
| Smoke 3 videos | `discover --limit 3` then `run --limit 3 --workers 1` | Same |
| Full ASR | `run --workers 4` | Start with `--workers 1` if RAM is tight |
| Grok pack | `export --format grok` | Same |

---

## 9. Decision checklist

| Question | Recommendation |
|----------|----------------|
| Where do videos live? | Link `data/input` → library; don’t copy |
| Language? | Force `pt` |
| Need speakers? | Not in v1; default narrator Kim Paim |
| Need perfect punctuation? | No |
| GPU? | NVIDIA CUDA if available; AMD Windows = CPU; original Linux host = CPU for CTranslate2 |
| Feed Grok? | Bundled `packs/*.md` + INDEX + INSTRUCTIONS, not raw MP4 |

---

## Related

- [README.md](./README.md) — quick start  
- [REQUIREMENTS.md](./REQUIREMENTS.md) — product requirements (original host inventory in §4 is Linux/ROCm)  
- [AGENTS.md](./AGENTS.md) — conventions for coding agents  
