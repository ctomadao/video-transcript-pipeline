I'll pull the Grok/Zed docs and any project-setup guidance so the answer matches how this environment actually works.

Here’s a practical path from empty folder → batch transcription utility → Grok Account Project.

## What you’re building (two different “projects”)

| Layer | What it is | Purpose |
|--------|------------|---------|
| **Local repo** (Zed folder) | Your transcription utility | Process 2000+ videos offline, produce text/JSON |
| **Grok Project** ([grok.com/project](https://grok.com/project)) | Web workspace with custom instructions + uploaded files | Chat against the transcripts as knowledge |

Zed is only for developing the utility. The Grok Account Project is where you upload the **outputs** (text), not the raw videos.

---

## 1. Create and open a new project in Zed

Zed treats a **folder** as a project. There is no special “New Project” wizard.

```bash
# Pick a location outside your other repos
mkdir -p ~/projects/video-transcript-pipeline
cd ~/projects/video-transcript-pipeline
git init

# Optional: Python scaffolding
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# Open in Zed (install CLI from Zed menu: "Install CLI" if needed)
zed .
# or new window:
zed -n .
```

In Zed:

- **File → Open** / `Ctrl+O` (Linux) → select the folder  
- Or drag the folder onto Zed  

Avoid opening this inside `game-guide-manager` unless you want it mixed with that repo.

---

## 2. Wire Grok into Zed (optional, for coding help)

Grok Build can run as an ACP agent that IDEs (including Zed) talk to:

```bash
grok agent stdio
```

In practice you either:

- Use a Zed extension / agent panel configured for Grok ACP, or  
- Run `grok` in the integrated terminal from this project root  

Add project rules so Grok follows your conventions:

```markdown
# AGENTS.md

## Goal
CLI utility that batch-transcribes video files and writes structured transcripts
for upload into a Grok.com Project.

## Constraints
- Resume-safe (skip already-done files)
- Idempotent outputs
- Never re-encode video unless extracting audio is required
- Prefer faster-whisper / local STT over cloud for bulk cost control
```

---

## 3. Recommended utility design (2000+ videos)

### Stack (simple and scalable)

| Choice | Why |
|--------|-----|
| **Python 3.11+** | Mature media + ML ecosystem |
| **ffmpeg** | Extract/normalize audio from any container |
| **faster-whisper** (or Whisper.cpp) | Local, free at scale, good accuracy |
| **SQLite or JSONL job log** | Track progress, failures, retries |
| **Click / argparse** | Clean CLI |

Cloud STT (Deepgram, AssemblyAI, OpenAI Whisper API) works but gets expensive and rate-limited at 2000+ videos. Local is usually better for bulk.

### Directory layout

```text
video-transcript-pipeline/
├── AGENTS.md
├── README.md
├── pyproject.toml          # or requirements.txt
├── src/
│   └── vtp/
│       ├── cli.py
│       ├── discover.py     # find videos under input roots
│       ├── audio.py        # ffmpeg extract
│       ├── transcribe.py   # whisper
│       ├── export.py       # markdown / json / chunks
│       └── state.py        # job DB
├── data/
│   ├── input/              # or symlink to your video library
│   ├── audio/              # optional intermediate wav/m4a
│   ├── transcripts/        # final .md / .json / .jsonl
│   └── state.db
└── scripts/
    └── run_batch.sh
```

### Pipeline stages

1. **Discover** – walk folders for `.mp4`, `.mkv`, `.mov`, `.webm`, etc.  
2. **Hash / stable ID** – path + size + mtime (or content hash) so renames are detectable.  
3. **Extract audio** – `ffmpeg -i video -vn -ac 1 -ar 16000 audio.wav`  
4. **Transcribe** – language detect or force language; write raw segments with timestamps.  
5. **Export for Grok** – human-readable Markdown + optional JSON.  
6. **Mark done** – only mark success after write is fsynced; failures stay retryable.

### Scale knobs for 2000+

- **Resume**: skip files already in `state.db` with status `done`.  
- **Concurrency**: 1 GPU job at a time (or N CPU workers); don’t spawn 50 Whisper processes.  
- **Model size**: `base`/`small` for speed; `medium`/`large-v3` for quality (much slower).  
- **Queue batches**: e.g. 50–100 videos per run overnight.  
- **Disk**: audio intermediates are large — delete after successful transcript if space is tight.  
- **Failures**: log error + stderr; continue; retry with `--retry-failed`.

Minimal CLI shape:

```bash
python -m vtp discover --input /path/to/videos --db data/state.db
python -m vtp run --workers 1 --model small --export-dir data/transcripts
python -m vtp export --format grok --out data/grok-upload/
python -m vtp status
```

---

## 4. Format transcripts so Grok can use them

Grok Projects accept **uploaded files** as project knowledge (custom workspaces + files). You will hit **file size / count limits**, so don’t upload 2000 raw dumps blindly.

### Per-video Markdown (good default)

```markdown
# Title: Interview with Alice – Episode 12
- Source: /media/videos/ep12.mp4
- Duration: 01:14:22
- Language: en
- Transcribed: 2026-07-23
- Model: faster-whisper small

## Transcript

[00:00:12] Welcome back to the show...
[00:01:05] Today we discuss...
```

### Packaging strategies for Grok upload

| Corpus size | Approach |
|-------------|----------|
| Small (tens of hours) | One `.md` per video, upload folder zip if needed |
| Medium | Group by series/date: `2024-Q1.md`, `channel-name.md` |
| Large (2000+) | **Chunk + index**: many mid-sized files + a master catalog |

**Master catalog** (`INDEX.md`) you always upload:

```markdown
# Video library index
| id | title | date | path | transcript_file | topics (auto) |
|----|-------|------|------|-----------------|---------------|
| v001 | ... | ... | ... | series-a/ep-01.md | ... |
```

Then upload:

1. `INDEX.md`  
2. Themed bundles (`series-a.md`, `series-b.md`, …) of a few hundred KB–few MB each  
3. Optional: short **summaries** per video (Grok or a local LLM) so the Project can navigate without loading every full transcript  

If a single file is too large, split by time (`ep-01-part1.md`, `part2.md`) rather than dumping everything into one blob.

---

## 5. Create the Grok Account Project

On [grok.com](https://grok.com/) (signed in):

1. Open **Projects** → create a new project (e.g. “Video Library Knowledge”).  
2. Add **custom instructions**, for example:

   > You are a research assistant over my video library transcripts.  
   > Always cite video title + timestamp when answering.  
   > Prefer INDEX.md for navigation, then open the matching transcript file.  
   > If the answer is not in the files, say so.

3. **Upload** your prepared `.md` / `.txt` / `.json` files (or zip if the UI allows).  
4. Chat inside that Project only — context is scoped to those files.

**Reality check:** 2000 full transcripts may exceed practical Project upload limits. Prefer:

- summaries + index for day-to-day Q&A,  
- full transcripts for a subset, or  
- rotate sets of files by topic as needed.

For programmatic RAG at true corpus scale, use the **xAI API / Collections** path rather than only the consumer Project UI. For a “small utility + Grok Project” workflow, file packages + index is the right first step.

---

## 6. Suggested first session in Zed

1. Open `~/projects/video-transcript-pipeline` in Zed.  
2. Install system deps:

   ```bash
   # Debian/Ubuntu examples
   sudo apt install ffmpeg
   # GPU optional: install CUDA stack if you have an NVIDIA GPU
   ```

3. Install Python deps:

   ```bash
   pip install faster-whisper tqdm rich
   # or: openai-whisper, whisperx, etc.
   ```

4. Smoke-test on **3 videos**, not 2000.  
5. Verify one Markdown looks good, then scale.  
6. Export a small pack → upload to Grok Project → ask a question that needs a timestamp cite.

---

## 7. Decision checklist

| Question | Recommendation |
|----------|----------------|
| Where do videos live? | Symlink `data/input` → your library; don’t copy 2000 files |
| Language? | Force if known (`en`); auto-detect if mixed |
| Need speakers? | Add diarization later (WhisperX); not for v1 |
| Need perfect punctuation? | Optional second pass; raw segments first |
| GPU? | Strongly preferred for 2000+; CPU is days–weeks |
| Feed Grok? | Markdown + INDEX, not raw MP4 |

---

## Minimal next commands (copy/paste)

```bash
mkdir -p ~/projects/video-transcript-pipeline/{src/vtp,data/{input,transcripts},scripts}
cd ~/projects/video-transcript-pipeline
git init
python3 -m venv .venv && source .venv/bin/activate
printf '%s\n' 'faster-whisper' 'tqdm' 'rich' > requirements.txt
pip install -r requirements.txt
echo "# Video Transcript Pipeline" > README.md
zed .
```

From there, either hand-write the CLI or ask Grok in that folder: *“Scaffold a resume-safe batch video transcription CLI using faster-whisper and ffmpeg.”*

---

If you want, I can scaffold that repo structure and a working `discover` / `run` / `export` CLI next (still as a **new** project, separate from `game-guide-manager`). Tell me:

1. OS GPU situation (NVIDIA / AMD / CPU-only)  
2. Video root path pattern  
3. Preferred languages  
4. Whether Grok should get **full transcripts**, **summaries**, or both
