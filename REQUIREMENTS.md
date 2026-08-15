# Requirements Definition — Atlas Brasileiro Video→Knowledge Pipeline

**Status:** Initial / draft for expansion  
**Date:** 2026-07-23  
**Related:** [Definition.md](./Definition.md) (setup path), [AGENTS.md](./AGENTS.md)  
**Grok Account Project:** **Atlas Brasileiro**  
**Local repo:** `video-transcript-pipeline`

---

## 1. Purpose and problem statement

### 1.1 Purpose

Build a **local, resume-safe pipeline** that:

1. Transcribes a large corpus of videos (author **Kim Paim / KiM PAiM**, language **PT-BR**).
2. Enriches transcripts with optional speaker cues, structure, and analysis.
3. Relates video content to the **monthly books already ingested** in the Grok project *Atlas Brasileiro* (from **2023/10** onward).
4. Produces **Markdown artifacts** suitable for upload into that project and for deep research Q&A.

### 1.2 Problem

- Books are largely derived from the videos of the corresponding month, but the mapping is **incomplete and non-bidirectional**:
  - Books may contain material **not present** (or not present *as-is*) in the videos.
  - Videos may contain material **omitted or rewritten** in the books.
- For research quality, the system must surface **relations** (alignment, gap, expansion) between video and book layers, not only raw transcripts.
- ~**3.5 GB** of book content already occupies Grok file storage; full raw transcripts of a large video set will not fit if uploaded naively. Packaging, summarization, and indexing are first-class requirements.

### 1.3 Success criteria (high level)

| ID | Criterion |
|----|-----------|
| SC-1 | Batch transcription of PT-BR video is resume-safe and idempotent. |
| SC-2 | Outputs are Markdown (and optional JSON) ready for Atlas Brasileiro. |
| SC-3 | Per-video (or per-batch) **structured analytical summaries** cover arguments, evidence, opinions, book links, and extra insights. |
| SC-4 | Explicit attempt to **link** video content to books (month/chapter/topic when possible). |
| SC-5 | Local inference uses existing **Ollama + ROCm** hardware without mandatory cloud STT/LLM. |
| SC-6 | Pipeline does not require copying the full video library (Linux symlink or Windows junction to `data/input` is acceptable). |

---

## 2. Stakeholders and primary user

| Role | Who | Needs |
|------|-----|--------|
| Owner / researcher | User | Deep analysis of Kim Paim corpus; book↔video coherence; Grok project enrichment |
| Author (content) | Kim Paim (narrator/author) | N/A (source identity for diarization defaults) |
| Runtime environment | Local workstation (ROCm) + Grok.com project | Offline bulk processing + online knowledge chat |

---

## 3. Scope

### 3.1 In scope (v1 → v1.5)

| Area | Scope |
|------|--------|
| **Ingest** | Discover videos under configured roots (symlink or junction); stable IDs; job state |
| **Audio** | Extract mono 16 kHz (or model-appropriate) audio via ffmpeg; no full video re-encode |
| **ASR** | Local speech-to-text, language forced/preferred **pt** / **pt-BR** |
| **Optional diarization** | Identify speakers when useful; default narrator = Kim Paim when single-voice or primary track |
| **Export** | Timestamped transcripts (Markdown + optional JSON/JSONL) |
| **Analysis** | Local LLM (Ollama) deep summary per video/batch: arguments, evidence, opinions, book links, expansions |
| **Book linkage** | Heuristic + LLM mapping to monthly books (from 2023/10); cite chapters/topics when recoverable |
| **Grok packaging** | INDEX + chunked/bundled Markdown; summaries preferred for bulk; full transcripts selectively |
| **Ops** | Resume, retry-failed, status, single-GPU-friendly concurrency |

### 3.2 Out of scope (initially)

- Uploading raw video/audio to Grok or any cloud.
- Perfect legal-grade transcription / forensic audio.
- Fully automatic 100% accurate speaker ID across all multi-speaker shows without review.
- Replacing the existing book corpus in Atlas Brasileiro.
- Real-time streaming transcription.
- Mandatory cloud STT (OpenAI, Deepgram, etc.) — optional adapters only if later needed.

### 3.3 Explicit non-goals for punctuation

Perfect punctuation is **not critical**. Prefer semantic clarity; optional light post-processing (capitalization, sentence breaks) is nice-to-have when it improves argument extraction, not a release blocker.

---

## 4. Environment and infrastructure

### 4.1 Local compute

**Original development host (Linux):**

| Item | Spec / note |
|------|-------------|
| GPU | AMD **Radeon RX 7900 XTX**, **ROCm** enabled |
| Practical VRAM budget | Models up to ~**22 GB** VRAM can run efficiently |
| Ollama | `http://localhost:11434` |
| Video storage | **`/home/clovis/Downloads/Tartube-new/Atlas Brasileiro - Kim Paim/`** (~2270 `.mp4`, flat Tartube layout) |
| App / pipeline storage | Separate storage; **`data/input` → symlink** to video root is adequate |
| Grok project storage | ~**3.5 GB** already used by monthly books |

**Portable hosts (Linux or Windows):** the same CLI runs after Python 3.11+, ffmpeg/ffprobe on `PATH`, and a link to the library. Setup steps are in [Definition.md](./Definition.md) and [README.md](./README.md).

| Item | Spec / note |
|------|-------------|
| OS | Linux or Windows 10/11 |
| Python | 3.11+ in a project `.venv` |
| ffmpeg | Must resolve as `ffmpeg` / `ffprobe` (apt, or `winget install Gyan.FFmpeg`) |
| Video library | `--input`, `VTP_VIDEO_ROOT`, Linux **symlink**, or Windows **directory junction** (`mklink /J` / `New-Item -ItemType Junction`). Do not copy the library. |
| ASR device | NVIDIA: `--device cuda` when CTranslate2 sees CUDA. AMD Linux: ROCm is for Ollama, not CTranslate2 (usually `--device cpu`). AMD Windows: **CPU only**. |
| Workers | Default 4×4 threads; use `--workers 1` on laptops / first Windows installs |

### 4.0 Critical architecture: Grok books are NOT visible to local Ollama

| Layer | Sees monthly books? | Sees new transcripts/analyses? |
|-------|---------------------|--------------------------------|
| **Local pipeline** (ffmpeg, ASR, Ollama on `:11434`) | **No** — Project file storage on grok.com is not mounted into Ollama | Yes, after it generates them on disk |
| **Grok Project “Atlas Brasileiro”** (chat on grok.com) | **Yes** — already ingested | **Yes**, only after you **upload** Markdown packs |

**Implication:** the local process does **not** automatically re-read or re-embed the books already in Grok. That avoids re-ingesting ~3.5 GB with a local model.

**Where book knowledge is used:**

1. **Primary (recommended):** Upload **analyses + INDEX** (and selective transcripts) into Atlas Brasileiro. In-project Grok chat then uses **books already there + new video material** together — no local re-ingest of books.
2. **Local analysis step:** By default, the LLM only sees the **transcript** (+ month_key + title). It can emit **link hypotheses** (“likely same month book”, themes) but **cannot cite real chapters** unless book text is provided offline.
3. **Optional offline book mirror:** Only if you later want tighter local chapter citations; **not required** for the Grok-centric workflow and is what would be costly to re-embed locally.

**Do not** re-upload the full book corpus to Grok as part of this pipeline.

### 4.2 Available Ollama models (current)

| Model | Size | Role candidate |
|-------|------|----------------|
| `fredrezones55/Qwen3.6-35B-A3B-APEX:I-Mini` | 15 GB | **Primary analysis / summarization** (fits VRAM) |
| `fredrezones55/Qwen3.6-35B-A3B-APEX:Compact` | 18 GB | Higher-quality analysis when load allows |
| `batiai/qwen3.6-35b:q3` | 13 GB | Faster / lighter analysis fallback |
| `qwen3.5:27b` | 17 GB | Alternate general LLM |
| `nomic-embed-text:latest` | 274 MB | Embeddings (index / similarity) |
| `bge-m3:latest` | 1.2 GB | Multilingual embeddings (strong PT candidate) |

**Note:** Pulling a better-suited model later is allowed (e.g. Whisper-class STT if not via Ollama, or a dedicated PT ASR; embedding model already present for RAG-style local index).

### 4.3 Recommended model allocation (initial)

| Stage | Engine | Model / notes |
|-------|--------|----------------|
| ASR | **faster-whisper `large-v3`** (default); sequential stage only | Quality-first PT-BR; **all transcriptions complete before any analysis** (no VRAM/RAM fight with Ollama) |
| Diarization (optional) | WhisperX / pyannote-style stack | Phase 1.5; fallback: label primary as Kim Paim |
| Embeddings | Ollama | `bge-m3` preferred for PT-BR cross-lingual chunks; `nomic-embed-text` as light alt |
| Analysis / Markdown synthesis | Ollama chat | Start with **I-Mini** or **q3** for throughput; Compact for harder videos |
| Book↔video retrieval (local) | embeddings + metadata month key | Align by calendar month + semantic similarity to book chunks if available offline |

**Constraint:** Avoid running a 18 GB LLM and a large Whisper model simultaneously if VRAM contention causes thrashing; pipeline should **serialize GPU-heavy stages** or allow `--stage` isolation.

---

## 5. Domain model

### 5.1 Core entities

```text
VideoAsset
  id, source_path, stable_hash, duration, title?, date?, month_key (YYYY-MM)

Transcript
  video_id, language, model, created_at, segments[]

Segment
  start, end, text, speaker? (optional)

Book (external, already in Grok)
  month_key, title, chapters/topics (as known from filenames/TOC if available)

VideoBookLink
  video_id, book_month_key, link_type, confidence, evidence (quotes/timestamps/chapter refs)

AnalysisDocument
  video_id, markdown_body, model, schema_version
```

### 5.2 Link types (video ↔ book)

| `link_type` | Meaning |
|-------------|---------|
| `aligned` | Same claim/topic appears in both with similar substance |
| `book_only` | Present in book, not found in this video (or not in corpus month) |
| `video_only` | Present in video, not reflected as-is in book |
| `expanded_in_video` | Book mentions briefly; video develops further |
| `expanded_in_book` | Video mentions briefly; book develops further |
| `rewritten` | Same idea, different framing or wording |
| `uncertain` | Possible relation; needs human review |

### 5.3 Month alignment rule

- Primary join key: **calendar month of the video** ↔ **monthly book** for that month (corpus starts **2023/10**).
- Secondary: semantic match may point to other months (transversal themes); always record both `primary_month` and any `cross_month` links.

---

## 6. Functional requirements

### 6.1 Discovery and state

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-D1 | Walk input roots (Linux symlink or Windows junction OK) for common video extensions (`.mp4`, `.mkv`, `.mov`, `.webm`, …). | Must |
| FR-D2 | Assign stable IDs from path + size + mtime (and/or content hash option). | Must |
| FR-D3 | Persist job state in SQLite (or equivalent): discovered / pending / running / done / failed. | Must |
| FR-D4 | Resume: skip `done`; support `--retry-failed`. | Must |
| FR-D5 | Derive or accept `month_key` (YYYY-MM) from path, filename, or metadata when possible. | Should |

### 6.2 Audio and transcription

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-T1 | Extract audio via ffmpeg without re-encoding full video. | Must |
| FR-T2 | Transcribe in **PT-BR** (force language when reliable). | Must |
| FR-T3 | Produce timestamped segments. | Must |
| FR-T4 | Optional intermediate audio cleanup after successful transcript (disk policy). | Should |
| FR-T5 | Optional speaker diarization; when only/primary narrator, label **Kim Paim**. | Should (v1.5) |
| FR-T6 | Multi-speaker segments labeled `SPEAKER_xx` or resolved names when known. | Could |
| FR-T7 | Light punctuation/normalization pass optional; not required for “done”. | Could |

### 6.3 Analysis (deep summary)

For each video (or batched group), the pipeline **shall** produce a structured Markdown analysis covering:

| ID | Section | Priority |
|----|---------|----------|
| FR-A1 | **Main arguments** — claims the author advances, in prose (not bullet-only). | Must |
| FR-A2 | **Evidence presented** — data, anecdotes, citations, historical/legal/political references as stated. | Must |
| FR-A3 | **Impressions / opinions** — clearly separated from factual claims when the transcript allows. | Must |
| FR-A4 | **Connections with Atlas Brasileiro books** — explicit and transversal; cite **month, chapter, or topic** when possible. | Must |
| FR-A5 | **Additional insights** — video content that **fits and expands** the books (video_only / expanded_in_video). | Must |
| FR-A6 | **Gaps / divergences** — likely book_only relative to this video, or rewritten framing (best-effort). | Should |
| FR-A7 | Timestamp citations for key claims (`[HH:MM:SS]`). | Should |
| FR-A8 | Metadata header: video id, source path, duration, ASR model, LLM model, month_key, generated_at. | Must |

Analysis language: **PT-BR** (match corpus), unless a flag requests EN for tooling.

### 6.4 Export and Grok packaging

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-E1 | Per-video transcript Markdown with timestamps. | Must |
| FR-E2 | Per-video (or per-month) **analysis Markdown** ready to feed Atlas Brasileiro. | Must |
| FR-E3 | Master `INDEX.md` (or equivalent catalog): id, title, date/month, paths, transcript file, analysis file, topics. | Must |
| FR-E4 | Bundling strategy for large corpus: monthly or thematic packs; avoid single multi-GB dumps. | Must |
| FR-E5 | Prefer uploading **analyses + index + selective full transcripts** given ~3.5 GB already used by books. | Must |
| FR-E6 | Optional JSON/JSONL for machine reuse (segments, links). | Should |
| FR-E7 | Chunk long transcripts for local embedding index without breaking timestamps. | Should |

### 6.5 Book relation (local + Grok)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-B1 | Associate each video with candidate book month(s). | Must |
| FR-B2 | When book text is available offline (export/copy from project or user-provided mirror), compute semantic/chapter-level links. | Should |
| FR-B3 | When book text is **only** in Grok storage, analysis prompts must still emit **structured link hypotheses** for the user to validate inside Atlas Brasileiro. | Must |
| FR-B4 | Prompt / schema for Grok Project custom instructions: always cite video timestamp **and** book month/chapter when answering. | Should |

### 6.6 CLI (minimal surface)

```text
vtp discover   --input ... --db ...
vtp run        --stage audio|asr|analyze|all --workers 1 ...
vtp export     --format grok|markdown|json --out ...
vtp status
vtp retry-failed
```

Priorities: discover + run(asr) + export first; analyze as second milestone; diarization third.

---

## 7. Non-functional requirements

| ID | Category | Requirement |
|----|----------|-------------|
| NFR-1 | Scale | Designed for **1000s** of videos; overnight batch runs. |
| NFR-2 | Resume | Crash mid-batch does not lose completed work. |
| NFR-3 | Idempotence | Re-run does not corrupt outputs; overwrite only with explicit flag or content-version bump. |
| NFR-4 | GPU | Single GPU job at a time by default; no 50 concurrent Whisper processes. |
| NFR-5 | Disk | Configurable keep/delete of intermediate audio. |
| NFR-6 | Privacy | Default local-only processing; no video leaves machine. |
| NFR-7 | Observability | Per-file status, error message, duration, model versions. |
| NFR-8 | Quality vs cost | Prefer local ASR/LLM; cloud optional later. |
| NFR-9 | Storage split | Symlink from app data dir to video root is supported and documented. |
| NFR-10 | Grok limits | Packaging and summary-first strategy respect project file quotas. |

---

## 8. Output specifications

### 8.1 Transcript Markdown (per video)

```markdown
# Title: <title or filename>
- Id: <stable_id>
- Source: <path>
- Duration: HH:MM:SS
- Language: pt-BR
- Month: YYYY-MM
- Transcribed: ISO-8601
- ASR model: <name>
- Speakers: Kim Paim | multi | unknown

## Transcript

[00:00:12] [Kim Paim] ...
[00:01:05] [SPEAKER_01] ...
```

### 8.2 Analysis Markdown (per video) — target schema for LLM

```markdown
# Análise: <title>
- Video id: ...
- Month key: YYYY-MM
- Livro(s) candidato(s): Atlas Brasileiro <mês/ano>
- ASR / LLM: ...

## 1. Contexto e resumo executivo
Prose paragraph(s).

## 2. Argumentos principais
Detailed structured prose: each major argument developed (not only a topic list).

## 3. Evidências apresentadas
What is offered as support (facts cited, examples, references), with timestamps when possible.

## 4. Impressões e opiniões do autor
Authorial stance, judgments, rhetorical framing — separated from reported facts.

## 5. Conexões com os livros (Atlas Brasileiro)
### 5.1 Explícitas / do mesmo mês
### 5.2 Transversais (outros meses / temas recorrentes)
Cite chapter or topic when possible; mark confidence (alta/média/baixa).

## 6. Insights adicionais (expansão do livro)
Content that fits the book’s themes but goes further, or appears only in the video.

## 7. Lacunas e divergências (best-effort)
Likely omissions vs book; rewritten points; uncertain links.

## 8. Metadados de ligação (máquina)
- link_type entries, timestamps, book refs
```

### 8.3 INDEX.md (catalog)

Columns at minimum: `id | title | month | duration | transcript_path | analysis_path | primary_book | topics | status`.

### 8.4 Upload packages (Grok)

| Package | Contents | When |
|---------|----------|------|
| `pack-index` | INDEX.md + README of corpus | Always |
| `pack-analysis-YYYY-MM` | All analyses for that month | Primary bulk feed |
| `pack-transcripts-YYYY-MM` | Full transcripts for month | Selective / on demand |
| `pack-theme-<slug>` | Cross-month thematic bundle of analyses | Research focus |

---

## 9. Grok Project “Atlas Brasileiro” integration requirements

### 9.1 Existing assets

- Monthly books from **2023/10** already uploaded (~**3.5 GB**).
- New material must **complement**, not replace, books.

### 9.2 Custom instructions (draft to expand later)

> You are a research assistant for the **Atlas Brasileiro** corpus (Kim Paim).  
> Knowledge includes monthly books and video-derived transcripts/analyses.  
> Prefer analyses for synthesis; open full transcripts when exact wording or timestamps matter.  
> Always cite: (1) book month/chapter/topic when used; (2) video title + `[HH:MM:SS]` when used.  
> Distinguish: aligned content, video-only expansions, and book-only material.  
> Language: respond in **pt-BR** unless the user asks otherwise.  
> If uncertain about a book↔video link, say so and give best hypothesis.

### 9.3 Research use cases the pipeline must support

1. “What did Kim argue in video X, and how does the month’s book treat it?”
2. “List video-only expansions for 2024-03 relative to the book.”
3. “Trace theme T across months (transversal) with book + video citations.”
4. “Summarize evidence offered for claim C across sources.”

---

## 10. Pipeline stages (logical architecture)

```text
[Video library] --symlink/junction--> data/input
        |
        v
   (1) Discover + state.db
        |
        v
   (2) Audio extract (ffmpeg)
        |
        v
   (3) ASR (+ optional diarization)
        |
        v
   (4) Transcript export (.md / .json)
        |
        +--> (5a) Embeddings (bge-m3) --> local chunk index
        |
        v
   (5) Analysis via Ollama (Qwen family)
        |     inputs: transcript + month_key + optional book excerpts
        v
   (6) Analysis Markdown + link records
        |
        v
   (7) Package for Grok (INDEX + monthly packs)
        |
        v
   [Atlas Brasileiro project upload — manual or scripted]
```

Stages 3 and 5 are **GPU-critical** and should not contend by default.

---

## 11. Phased delivery

### Phase 0 — Foundations (done / in progress)

- Repo skeleton, Definition.md, requirements, AGENTS.md.
- Confirm ffmpeg, ROCm (Linux/AMD host), Ollama, symlink or junction to video root.

### Phase 1 — Transcription MVP

- discover / run ASR / export transcript Markdown / status / resume.
- Force pt-BR; smoke-test on **3 videos**.
- No diarization; no LLM analysis yet.

### Phase 2 — Analysis MVP

- Ollama client; prompt template per §8.2.
- Generate analysis Markdown; monthly packs + INDEX.
- Upload small pack to Atlas Brasileiro; validate Q&A quality.

### Phase 3 — Book linkage hardening

- Optional offline book mirror or chapter TOC files for better citations.
- Embeddings (`bge-m3`) for transversal theme retrieval.
- Link_type schema in JSON sidecar.

### Phase 4 — Speakers and quality

- Diarization; default Kim Paim; optional punctuation pass.
- Quality sampling rubric (WER spot-check, analysis faithfulness).

### Phase 5 — Scale ops

- Overnight batch tooling, failure dashboards, model A/B (I-Mini vs Compact vs q3).
- Selective full-transcript upload policy under Grok storage budget.

---

## 12. Open decisions (to resolve in design/spec)

| # | Decision | Options / notes | Default lean |
|---|----------|-----------------|--------------|
| D1 | ASR stack on ROCm | **Not** `karanchopda333/whisper` (that tag is Llama 3.2 text, not ASR). Prefer faster-whisper / openai-whisper / Whisper.cpp / WhisperX with ROCm or CPU | Spike real Whisper stack; document winner |
| D1b | Video root path | Fixed: `/home/clovis/Downloads/Tartube-new/Atlas Brasileiro - Kim Paim/` | Symlink `data/input` → that path |
| D2 | Co-residency of ASR + LLM | Sequential stages vs smaller concurrent models | **Sequential** |
| D3 | Analysis model default | I-Mini vs Compact vs q3 | **I-Mini** for batch; Compact for flagged videos |
| D4 | Book text access for linkage | Manual excerpts, full offline mirror, Grok-only hypotheses | Start **Grok-only hypotheses** + month metadata; add mirror if available |
| D5 | Diarization necessity | Many monologue videos vs multi-guest | Kim Paim default; diarize when multi-speaker detected |
| D6 | Filename/date conventions | How `month_key` is derived from library layout | Document after inspecting real paths |
| D7 | Grok storage budget | Max new upload size; summary-only policy | Analyses first; full transcripts by month on demand |
| D8 | Pull better model? | Dedicated PT ASR or stronger instruct model within 22 GB | Evaluate after Phase 1 quality sample |

---

## 13. Risks and mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Grok storage exhausted | Cannot upload full transcripts | Summary-first packs; rotate months; local RAG optional |
| Book↔video false links | Misleading research | Confidence labels; human review queue; timestamp evidence |
| PT-BR ASR quality | Bad analysis downstream | Model spike; glossary of proper names (Kim Paim, recurring terms) |
| VRAM OOM | Failed batches | Sequential stages; smaller models; clear Ollama/Whisper before next stage |
| Path/symlink breakage | Empty discover | Startup checks; document absolute targets |
| Analysis hallucination | Fabricated book chapters | Instruct “only cite chapters if present in context”; else topic-level only |
| Author name variants | Metadata inconsistency | Canonical: **Kim Paim** (aliases: KiM PAiM, etc.) |

---

## 14. Acceptance criteria (MVP)

### Transcription MVP

- [ ] Discover finds videos via symlink or junction without copying library.
- [ ] 3-video smoke test produces timestamped PT-BR Markdown.
- [ ] Re-run skips completed jobs; failed jobs retryable.
- [ ] `status` reports counts by state.

### Analysis MVP

- [ ] For each smoke-test video, analysis Markdown contains sections §8.2 (1–6 at minimum).
- [ ] Month key and candidate book reference present.
- [ ] Output is valid UTF-8 Markdown suitable for Grok upload.
- [ ] INDEX lists transcript + analysis paths.

### Integration smoke

- [ ] Upload index + analyses for smoke set into Atlas Brasileiro.
- [ ] Project answers one question with video timestamp and book month reference (even if chapter unknown).

---

## 15. Glossary

| Term | Definition |
|------|------------|
| **Atlas Brasileiro** | Grok Account Project holding monthly books and (future) video-derived knowledge |
| **Month key** | `YYYY-MM` alignment between videos and monthly books |
| **Transversal connection** | Theme/argument that spans multiple months or books |
| **Video-only** | Content in video not reflected as-is in the corresponding book |
| **Book-only** | Content in book not found in the related videos |
| **Stable ID** | Deterministic identifier for a video asset across renames (as far as policy allows) |

---

## 16. Next specification work (expansion checklist)

Use this requirements doc to drive:

1. **Library path inspection** — real folder patterns, naming, date extraction rules.  
2. **ASR design note** — ROCm-capable stack choice and VRAM budget table.  
3. **Prompt library** — versioned Ollama prompts for analysis + link extraction (JSON sidecar).  
4. **Export schemas** — formal JSON Schema for segments and VideoBookLink.  
5. **Grok packaging runbook** — size limits, pack naming, update procedure when new months arrive.  
6. **Evaluation set** — 5–10 videos with human-reviewed transcripts/analyses as gold sample.  
7. **CLI and module design** — map FR-* to `src/vtp/*` modules from Definition.md.

---

## 17. Traceability to prior Definition.md

| Definition.md theme | This document |
|---------------------|---------------|
| Two layers: local repo + Grok project | §1, §9 |
| Resume-safe batch STT | §6.1, §6.2, NFR-2 |
| Symlink input | §4.1, FR-D1, NFR-9 |
| Markdown + INDEX for Grok | §6.4, §8 |
| Diarization later | FR-T5, Phase 4 |
| Punctuation optional | §3.3, FR-T7 |
| GPU-friendly concurrency | §4.3, NFR-4 |
| **New:** Ollama/ROCm inventory | §4 |
| **New:** Atlas Brasileiro + books from 2023/10 | §1, §5, §9 |
| **New:** Deep analysis + book linkage | §6.3, §6.5, §8.2 |
| **New:** Storage budget awareness | FR-E5, NFR-10, risks |

---

*End of initial requirements definition. Ready to expand into detailed design (ASR choice, prompts, CLI contract) and implementation phases.*
