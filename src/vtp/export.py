"""Export transcripts to Markdown / JSON and build INDEX for Grok."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vtp.discover import parse_title
from vtp.state import StateDB, VideoJob
from vtp.transcribe import Segment, TranscriptResult, format_ts

# Existing run() Markdown: [HH:MM:SS] [Speaker] text
# Grok pack also accepts a bare [HH:MM:SS] text line.
_MD_SEG_RE = re.compile(
    r"^\[(\d{2}):(\d{2}):(\d{2})\](?:\s+\[[^\]]+\])?\s*(.*)$"
)


def duration_hms(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    return format_ts(seconds)


def transcript_markdown(
    job: VideoJob,
    result: TranscriptResult,
    *,
    speaker_default: str = "Kim Paim",
) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    lines = [
        f"# Title: {job.title}",
        f"- Id: `{job.id}`",
        f"- Source: `{job.source_path}`",
        f"- Rel path: `{job.rel_path}`",
        f"- Duration: {duration_hms(result.duration or job.duration_sec)}",
        f"- Language: {result.language} (p={result.language_probability:.2f})",
        f"- Transcribed: {now}",
        f"- ASR model: {result.model_name} ({result.device}/{result.compute_type})",
        f"- Speakers: {speaker_default} (default narrator; diarization not applied)",
        "",
        "## Transcript",
        "",
    ]
    for seg in result.segments:
        lines.append(
            f"[{format_ts(seg.start)}] [{speaker_default}] {seg.text}"
        )
    lines.append("")
    return "\n".join(lines)


def transcript_json(
    job: VideoJob,
    result: TranscriptResult,
    *,
    speaker_default: str = "Kim Paim",
) -> dict[str, Any]:
    return {
        "id": job.id,
        "title": job.title,
        "source_path": job.source_path,
        "rel_path": job.rel_path,
        "duration_sec": result.duration or job.duration_sec,
        "language": result.language,
        "language_probability": result.language_probability,
        "asr_model": result.model_name,
        "device": result.device,
        "compute_type": result.compute_type,
        "speaker_default": speaker_default,
        "segments": [
            {**s.to_dict(), "speaker": speaker_default} for s in result.segments
        ],
        "meta": job.meta,
    }


def write_transcript_outputs(
    job: VideoJob,
    result: TranscriptResult,
    out_dir: Path,
    *,
    keep_json: bool = True,
) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Flat safe filename from id + short slug
    slug = _safe_slug(job.title, max_len=60)
    base = f"{job.id}_{slug}" if slug else job.id
    md_path = out_dir / f"{base}.md"
    md_path.write_text(transcript_markdown(job, result), encoding="utf-8")
    if keep_json:
        json_path = out_dir / f"{base}.json"
        json_path.write_text(
            json.dumps(transcript_json(job, result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return md_path


def youtube_id_for(job: VideoJob) -> str | None:
    """YouTube id from discover() meta, else Tartube filename."""
    yt = job.meta.get("youtube_id")
    if isinstance(yt, str) and yt:
        return yt
    _, parsed = parse_title(Path(job.rel_path or job.source_path))
    return parsed


def youtube_watch_url(youtube_id: str, t_seconds: float | int | None = None) -> str:
    url = f"https://www.youtube.com/watch?v={youtube_id}"
    if t_seconds is None:
        return url
    return f"{url}&t={int(max(0, float(t_seconds)))}s"


def hms_to_seconds(hms: str) -> int:
    parts = hms.split(":")
    if len(parts) != 3:
        raise ValueError(f"expected HH:MM:SS, got {hms!r}")
    h, m, s = (int(p) for p in parts)
    return h * 3600 + m * 60 + s


def grok_transcript_markdown(
    job: VideoJob,
    segments: list[tuple[float, str]],
    *,
    language: str | None = None,
    asr_model: str | None = None,
) -> str:
    """Markdown shaped for Atlas Brasileiro retrieval: video + timestamp per line."""
    yt_id = youtube_id_for(job)
    watch = youtube_watch_url(yt_id) if yt_id else ""
    dur = duration_hms(job.duration_sec)
    lang = language or "pt"
    asr = asr_model or job.asr_model or ""
    cite_id = yt_id or job.id
    example_t = 65
    example_url = youtube_watch_url(yt_id, example_t) if yt_id else f"t={example_t}s"

    lines = [
        f"# Title: {job.title}",
        f"- Id: `{job.id}`",
        f"- YouTube: `{yt_id}`" if yt_id else "- YouTube: unknown",
        f"- Watch: {watch}" if watch else "- Watch: unknown",
        f"- Duration: {dur}",
        f"- Language: {lang}",
        f"- ASR model: {asr}",
        "",
        "Cite as: **video title** + `[HH:MM:SS]` + YouTube URL with `&t=<seconds>s`.",
        f"Each line is `[{cite_id} @ HH:MM:SS] spoken text`.",
        f"Example: `[{cite_id} @ 00:01:05]` → {example_url}",
        "",
        "## Transcript",
        "",
    ]
    tag = yt_id or job.id
    for start, text in segments:
        lines.append(f"[{tag} @ {format_ts(start)}] {text}".rstrip())
    lines.append("")
    return "\n".join(lines)


def load_transcript_segments(src_md: Path) -> tuple[list[tuple[float, str]], dict[str, Any]]:
    """Load (start_sec, text) from companion JSON, else parse the Markdown body."""
    js = src_md.with_suffix(".json")
    if js.exists():
        data = json.loads(js.read_text(encoding="utf-8"))
        segs: list[tuple[float, str]] = []
        for item in data.get("segments") or []:
            text = (item.get("text") or "").strip()
            if not text and "start" not in item:
                continue
            segs.append((float(item.get("start") or 0.0), text))
        return segs, data if isinstance(data, dict) else {}

    segs = []
    for raw in src_md.read_text(encoding="utf-8").splitlines():
        m = _MD_SEG_RE.match(raw)
        if not m:
            continue
        h, mi, s, text = m.groups()
        segs.append((hms_to_seconds(f"{h}:{mi}:{s}"), text.strip()))
    return segs, {}


def _utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _resolve_transcript_src(job: VideoJob, transcripts_dir: Path) -> Path | None:
    src = Path(job.transcript_path) if job.transcript_path else None
    if src and src.exists():
        return src
    if src:
        alt = Path(transcripts_dir) / src.name
        if alt.exists():
            return alt
    return None


def pack_video_block(job: VideoJob, body: str) -> str:
    """One video inside a bundle, with hard start/end markers for retrieval."""
    yt = youtube_id_for(job) or job.id
    title = job.title.replace("\n", " ").strip()
    return "\n".join(
        [
            f"# ========== VIDEO START: {yt} ==========",
            f"# Video title: {title}",
            f"- Pack video id: `{job.id}`",
            "",
            body.rstrip(),
            "",
            f"# ========== VIDEO END: {yt} ==========",
            "",
        ]
    )


def assign_packs(
    items: list[tuple[VideoJob, str]],
    *,
    max_bytes: int,
) -> list[list[tuple[VideoJob, str]]]:
    """Greedy pack fill. A single oversized video still gets its own pack."""
    packs: list[list[tuple[VideoJob, str]]] = []
    current: list[tuple[VideoJob, str]] = []
    current_bytes = 0
    for job, block in items:
        size = _utf8_len(block)
        if current and current_bytes + size > max_bytes:
            packs.append(current)
            current = []
            current_bytes = 0
        current.append((job, block))
        current_bytes += size
    if current:
        packs.append(current)
    return packs


def render_pack_markdown(
    pack_name: str,
    pack_index: int,
    pack_count: int,
    items: list[tuple[VideoJob, str]],
) -> str:
    rows = [
        f"# Atlas Brasileiro — transcript pack {pack_index:03d} / {pack_count:03d}",
        "",
        f"- File: `{pack_name}`",
        f"- Videos in this pack: {len(items)}",
        "",
        "Each video is wrapped in `VIDEO START: {youtubeId}` / `VIDEO END: {youtubeId}`.",
        "Spoken lines are `[youtubeId @ HH:MM:SS] text`.",
        "Cite as title + `[HH:MM:SS]` + "
        "`https://www.youtube.com/watch?v={youtubeId}&t={seconds}s`.",
        "",
        "## Contents",
        "",
        "| youtube | title | duration | id |",
        "|---------|-------|----------|----|",
    ]
    for job, _block in items:
        yt = youtube_id_for(job) or ""
        title = job.title.replace("|", "\\|")
        yt_cell = f"[`{yt}`]({youtube_watch_url(yt)})" if yt else ""
        rows.append(
            f"| {yt_cell} | {title} | {duration_hms(job.duration_sec)} | `{job.id}` |"
        )
    rows.extend(["", "---", ""])
    for _job, block in items:
        rows.append(block.rstrip())
        rows.append("")
    rows.append("")
    return "\n".join(rows)


def build_index(
    db: StateDB,
    out_path: Path,
    *,
    pack_by_id: dict[str, str] | None = None,
    pack_summaries: list[dict[str, Any]] | None = None,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    jobs = [j for j in db.list_all() if j.status == "done" and j.transcript_path]
    lines = [
        "# Atlas Brasileiro — Video transcript index",
        "",
        "Transcripts are bundled in `packs/pack-NNN.md` (not one file per video).",
        "Use this catalog to find the **pack** + YouTube id, then search that pack.",
        "Each spoken line is `[youtubeId @ HH:MM:SS] text`.",
        "Cite as: video title + `[HH:MM:SS]` + "
        "`https://www.youtube.com/watch?v={youtubeId}&t={seconds}s`.",
        "",
        f"Generated: {datetime.now(timezone.utc).replace(microsecond=0).isoformat()}",
        f"Done transcripts: {len(jobs)}",
    ]
    if pack_summaries:
        lines.extend(
            [
                f"Packs: {len(pack_summaries)}",
                "",
                "## Packs",
                "",
                "| pack | videos | size | first youtube | last youtube |",
                "|------|--------|------|---------------|--------------|",
            ]
        )
        for info in pack_summaries:
            lines.append(
                f"| `{info['name']}` | {info['videos']} | {info['size_label']} | "
                f"`{info['first_yt']}` | `{info['last_yt']}` |"
            )
    lines.extend(
        [
            "",
            "## Videos",
            "",
            "| id | title | youtube | duration | pack | asr_model |",
            "|----|-------|---------|----------|------|-----------|",
        ]
    )
    pack_map = pack_by_id or {}
    for j in jobs:
        dur = duration_hms(j.duration_sec)
        title = j.title.replace("|", "\\|")
        yt = youtube_id_for(j) or ""
        yt_cell = f"[`{yt}`]({youtube_watch_url(yt)})" if yt else ""
        pack = pack_map.get(j.id, "")
        pack_cell = f"`{pack}`" if pack else ""
        lines.append(
            f"| `{j.id}` | {title} | {yt_cell} | {dur} | {pack_cell} | {j.asr_model or ''} |"
        )
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def package_for_grok(
    db: StateDB,
    transcripts_dir: Path,
    out_dir: Path,
    *,
    include_json: bool = False,
    bundle_max_mb: float = 6.0,
) -> Path:
    """Build a Grok upload folder: bundled timestamped Markdown + INDEX."""
    del include_json  # JSON is local-only; never part of the upload pack.
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest_packs = out_dir / "packs"
    if dest_packs.exists():
        shutil.rmtree(dest_packs)
    dest_packs.mkdir()
    stale_tx = out_dir / "transcripts"
    if stale_tx.exists():
        shutil.rmtree(stale_tx)

    prepared: list[tuple[VideoJob, str]] = []
    n_empty = 0
    for j in db.list_all():
        if j.status != "done" or not j.transcript_path:
            continue
        src = _resolve_transcript_src(j, transcripts_dir)
        if src is None:
            continue
        segments, extra = load_transcript_segments(src)
        if not segments:
            n_empty += 1
        body = grok_transcript_markdown(
            j,
            segments,
            language=extra.get("language") if extra else None,
            asr_model=extra.get("asr_model") if extra else j.asr_model,
        )
        prepared.append((j, pack_video_block(j, body)))

    max_bytes = max(1, int(bundle_max_mb * 1024 * 1024))
    groups = assign_packs(prepared, max_bytes=max_bytes)
    pack_count = len(groups)
    pack_by_id: dict[str, str] = {}
    pack_summaries: list[dict[str, Any]] = []
    digits = max(3, len(str(pack_count)))

    for i, items in enumerate(groups, start=1):
        name = f"pack-{i:0{digits}d}.md"
        text = render_pack_markdown(name, i, pack_count, items)
        (dest_packs / name).write_text(text, encoding="utf-8")
        size = _utf8_len(text)
        first_yt = youtube_id_for(items[0][0]) or items[0][0].id
        last_yt = youtube_id_for(items[-1][0]) or items[-1][0].id
        pack_summaries.append(
            {
                "name": name,
                "videos": len(items),
                "bytes": size,
                "size_label": f"{size / (1024 * 1024):.1f} MB",
                "first_yt": first_yt,
                "last_yt": last_yt,
            }
        )
        for job, _block in items:
            pack_by_id[job.id] = name

    n = len(prepared)
    build_index(
        db,
        out_dir / "INDEX.md",
        pack_by_id=pack_by_id,
        pack_summaries=pack_summaries,
    )
    (out_dir / "README.md").write_text(
        _grok_readme(n, n_empty, pack_summaries),
        encoding="utf-8",
    )
    (out_dir / "INSTRUCTIONS.md").write_text(
        _grok_instructions(n, pack_count),
        encoding="utf-8",
    )
    return out_dir


def _grok_readme(
    n: int,
    n_empty: int,
    pack_summaries: list[dict[str, Any]],
) -> str:
    empty_note = (
        f"Empty-body transcripts (shorts/intros with no spoken lines): {n_empty}\n"
        if n_empty
        else ""
    )
    pack_n = len(pack_summaries)
    return "\n".join(
        [
            "# Grok upload pack — bundled timestamped transcripts",
            "",
            "Upload these files into the Atlas Brasileiro project (do **not** upload "
            "one file per video; that overflows the project file list):",
            "",
            "1. `INSTRUCTIONS.md` — also paste it into project custom instructions",
            "2. `INDEX.md`",
            "3. this `README.md`",
            f"4. every file under `packs/` ({pack_n} Markdown bundles)",
            "",
            "These files let the project answer: *em qual vídeo e em que minuto isso foi dito?*",
            "",
            "## How to use with the monthly books",
            "",
            "The project already has the monthly books. These packs are the video layer.",
            "When the user quotes or paraphrases a book passage:",
            "",
            "1. Look up the video in `INDEX.md` (title / youtube / **pack**).",
            "2. Search the matching `packs/pack-NNN.md` for the closest wording "
            "(ASR may differ from the book).",
            "3. Answer with **video title**, **`[HH:MM:SS]`**, the **YouTube URL with `&t=`**, "
            "and a short quoted line.",
            "4. If several hits exist, list them. Do not invent timestamps.",
            "5. If the book wording is not in any pack, say so.",
            "",
            "## Line format",
            "",
            "```",
            "[youtubeId @ HH:MM:SS] spoken text",
            "```",
            "",
            "Video boundaries inside a pack:",
            "",
            "```",
            "# ========== VIDEO START: youtubeId ==========",
            "...",
            "# ========== VIDEO END: youtubeId ==========",
            "```",
            "",
            "Watch URL: `https://www.youtube.com/watch?v={youtubeId}&t={seconds}s`",
            "where `seconds = HH*3600 + MM*60 + SS`.",
            "Example: `[00:01:05]` → `&t=65s`.",
            "",
            "A pack is many videos. Never treat the pack filename as the video title.",
            "",
            f"Videos: {n}",
            f"Packs: {pack_n}",
            empty_note.rstrip(),
            "",
        ]
    )


def _grok_instructions(n: int, pack_count: int) -> str:
    return "\n".join(
        [
            "# Instruções do agente — Atlas Brasileiro (livros ↔ vídeos)",
            "",
            "Cole este texto nas **instruções personalizadas** do projeto Grok "
            "*Atlas Brasileiro*. Envie também este arquivo com `INDEX.md` e `packs/`.",
            "",
            "---",
            "",
            "Você é um assistente de pesquisa factual do corpus **Atlas Brasileiro** (Kim Paim).",
            "",
            "Seu trabalho é **localizar o que foi publicado** nos livros mensais e/ou nas "
            "transcrições dos vídeos, **cruzar as duas camadas** quando houver correspondência, "
            "e devolver **citações verificáveis** (livro + vídeo com minuto e link). "
            "Você não é comentarista, nem analista político, nem verificador da realidade "
            "externa ao corpus.",
            "",
            "Idioma das respostas: **português do Brasil**, salvo pedido explícito em outro idioma.",
            "",
            "## Fontes permitidas (somente estas)",
            "",
            "1. **Livros mensais** já enviados ao projeto (Atlas Brasileiro, a partir de 2023/10).",
            "2. **Pacotes de transcrição** em `packs/pack-NNN.md` "
            f"({pack_count} arquivos; {n} vídeos no total).",
            "3. O catálogo `INDEX.md` (coluna **pack** + YouTube).",
            "4. Este arquivo e `README.md`, só para regras de citação.",
            "",
            "Não há um arquivo por vídeo. Cada `pack-NNN.md` contém dezenas de vídeos. "
            "Não use o nome do pack como título do vídeo.",
            "",
            "É proibido usar: conhecimento geral do modelo, notícias, Wikipedia, memória de "
            "treino, inferência “óbvia”, ou qualquer fato que não esteja **citável** num "
            "arquivo do projeto.",
            "",
            "Se a informação não estiver nos livros nem nas transcrições, a resposta é: "
            "**não consta neste corpus**. Não complete a lacuna.",
            "",
            "## O que conta como fato publicável aqui",
            "",
            "Um item só pode aparecer na resposta se for **publicado no corpus**:",
            "",
            "- está escrito num livro do projeto, com localização (título/mês, capítulo ou "
            "seção, citação curta); **ou**",
            "- está dito numa transcrição, com título do vídeo, linha "
            "`[youtubeId @ HH:MM:SS]` e link YouTube com `&t=`.",
            "",
            "Isso **não** significa que a afirmação seja verdadeira no mundo. Significa só: "
            "*Kim / o livro / o vídeo publicou isso, neste lugar*. Sempre formule assim.",
            "",
            "Separe sempre:",
            "",
            "| Tipo | Como tratar |",
            "|------|-------------|",
            "| Dado publicado (nome, data, cifra, evento, citação de terceiros **como o autor apresenta**) | Relatar com citação. Não validar fora do corpus. |",
            "| Opinião, juízo, previsão, ironia, enquadramento retórico | Relatar como **opinião ou tese do autor**, com citação. Nunca reescrever como fato neutro. |",
            "| Transcrição ASR duvidosa (nome estranho, cifra instável) | Citar a linha e marcar **incerteza de ASR**. Não “corrigir” com conhecimento externo, salvo se o **mesmo** nome/cifra aparecer de forma clara no livro. |",
            "| Ausente dos arquivos | Declarar não encontrado. |",
            "",
            "Não transforme tese do autor em “fato verificado”. Não transforme silêncio do "
            "corpus em confirmação nem em negação.",
            "",
            "## Como achar o vídeo certo",
            "",
            "1. **Livro.** Ache a passagem. Anote mês/título, seção se houver, e uma citação curta.",
            "2. **Termos.** Extraia nomes, cifras, leis, instituições. Gere variantes de ASR "
            "(ex.: Dilma/Dilmo; cifras faladas vs escritas).",
            "3. **Índice.** Consulte `INDEX.md`: título, `youtubeId` e o arquivo `pack-NNN.md`.",
            "4. **Pack.** Abra/busque esse pack. Os vídeos estão separados por:",
            "   `# ========== VIDEO START: youtubeId ==========`",
            "   e `# ========== VIDEO END: youtubeId ==========`.",
            "5. **Linha.** A prova do minuto é a linha `[youtubeId @ HH:MM:SS] texto`.",
            "6. **Correlação.** alinhado / só no livro / só no vídeo / divergente / correspondência fraca.",
            "7. **Link.** Só monte URL se `youtubeId` e `HH:MM:SS` estiverem na linha recuperada.",
            "",
            "Se a busca no pack devolver um trecho, use o `youtubeId` **dessa linha**, não o "
            "primeiro vídeo do arquivo.",
            "",
            "## Formato da linha e do link",
            "",
            "```",
            "[youtubeId @ HH:MM:SS] texto falado",
            "```",
            "",
            "`https://www.youtube.com/watch?v={youtubeId}&t={segundos}s`",
            "",
            "`segundos = HH*3600 + MM*60 + SS`. Exemplo: `[00:01:05]` → `&t=65s`.",
            "",
            "Não invente `youtubeId`, timestamp, título de vídeo, nome de pack ou localização "
            "de livro. Se a transcrição recuperada não trouxer o relógio, não estime o minuto.",
            "",
            "## Formato da resposta",
            "",
            "Use esta estrutura (omite seções vazias):",
            "",
            "**Pergunta reformulada em uma linha**",
            "",
            "**No livro**",
            "- Obra / mês / seção",
            "- Citação entre aspas",
            "- O que exatamente está publicado ali",
            "",
            "**No vídeo**",
            "- Título (não o nome do pack)",
            "- Arquivo `pack-NNN.md`",
            "- `[HH:MM:SS]`",
            "- Link com `&t=`",
            "- Citação da linha da transcrição",
            "- Relação com o livro: alinhado / só vídeo / divergente / fraca",
            "",
            "**Não encontrado**",
            "- O que foi procurado e não apareceu",
            "",
            "**Limites**",
            "- ASR incerto, correspondência só temática, ou tese do autor",
            "",
            "Se houver vários vídeos, liste os que de fato casam. Não resuma uma narrativa "
            "única no lugar das citações.",
            "",
            "## Regras que não se quebram",
            "",
            "- Não responda com background histórico ou político que não esteja citado no corpus.",
            "- Não confirme nem desminta eventos do mundo real. Só diga o que o livro ou o "
            "vídeo publicou.",
            "- Não preencha nomes, datas, cargos ou cifras que a fonte não traz.",
            "- Título do vídeo e nome do pack não substituem a linha transcrita.",
            "- Não cite timestamp de um vídeo e texto de outro.",
            "- Não apresente hipótese como achado. Sem verificação no corpus, diga "
            "**não verificado neste corpus** e pare, ou mostre a citação mais próxima "
            "rotulada como correspondência fraca.",
            "- Pedido de opinião ou prognóstico seu: recuse e ofereça só o que o corpus publicou.",
            "- Se o usuário colar um trecho, primeiro ache esse trecho (ou o mais próximo) "
            "na fonte, depois correlacione.",
            "",
            "## Exemplo do tom correto",
            "",
            "Errado: “O rombo da meta fiscal é X, como Kim demonstrou.”",
            "",
            "Certo: “No livro de [mês], seção [Y], o texto afirma: «…». No vídeo *<título>* "
            "(`youtubeId`), pack `pack-012.md`, em `[00:00:36]`, a transcrição diz: «…». "
            "Link: https://www.youtube.com/watch?v=…&t=36s. Isso é o que está publicado "
            "nessas duas fontes; não é uma verificação independente do fato.”",
            "",
        ]
    )


def _safe_slug(text: str, max_len: int = 60) -> str:
    keep = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_"):
            keep.append(ch)
        elif ch.isspace() or ch in (":", ",", ".", "!", "?", "—", "–"):
            keep.append("-")
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:max_len]
