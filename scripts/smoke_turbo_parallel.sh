#!/usr/bin/env bash
# Smoke: re-transcribe the 2 finished large-v3 gold videos with large-v3-turbo
# in parallel (2 workers). Writes to a separate dir so gold is not overwritten.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -e . -q

MAIN_DB="${MAIN_DB:-$ROOT/data/state.db}"
SMOKE_IN="$ROOT/data/turbo-smoke-input"
SMOKE_DB="$ROOT/data/turbo-smoke.db"
SMOKE_AUDIO="$ROOT/data/turbo-smoke-audio"
SMOKE_TX="$ROOT/data/turbo-smoke-transcripts"
GOLD_TX="$ROOT/data/transcripts"

rm -rf "$SMOKE_IN" "$SMOKE_AUDIO" "$SMOKE_TX"
rm -f "$SMOKE_DB"
mkdir -p "$SMOKE_IN" "$SMOKE_AUDIO" "$SMOKE_TX"

mapfile -t SOURCES < <(sqlite3 "$MAIN_DB" "SELECT source_path FROM videos WHERE status='done' ORDER BY rel_path LIMIT 2;")
if [[ ${#SOURCES[@]} -lt 1 ]]; then
  echo "No done videos in $MAIN_DB" >&2
  exit 1
fi

echo "Gold sources (${#SOURCES[@]}):"
for s in "${SOURCES[@]}"; do
  echo "  $s"
  ln -sfn "$s" "$SMOKE_IN/$(basename "$s")"
done

echo "=== discover ==="
python -m vtp discover --input "$SMOKE_IN" --db "$SMOKE_DB"

echo "=== run large-v3-turbo workers=2 cpu_threads=6 ==="
START=$(date +%s)
python -m vtp run \
  --db "$SMOKE_DB" \
  --audio-dir "$SMOKE_AUDIO" \
  --export-dir "$SMOKE_TX" \
  --model large-v3-turbo \
  --language pt \
  --device cpu \
  --workers 2 \
  --cpu-threads 6
END=$(date +%s)
echo "WALL_SEC=$((END - START))"

python -m vtp status --db "$SMOKE_DB"

echo "=== compare turbo vs large-v3 gold (text overlap) ==="
python - <<'PY'
import re
from pathlib import Path

def body(md: Path) -> str:
    text = md.read_text(encoding="utf-8")
    if "## Transcript" in text:
        text = text.split("## Transcript", 1)[1]
    # drop timestamps and speaker tags
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\[[0-9:]+\]\s*", "", line)
        line = re.sub(r"^\[Kim Paim\]\s*", "", line)
        lines.append(line)
    return re.sub(r"\s+", " ", " ".join(lines)).strip().lower()

def tokens(s: str) -> set[str]:
    return set(re.findall(r"[\wÀ-ÿ']+", s, flags=re.UNICODE))

gold_dir = Path("data/transcripts")
turbo_dir = Path("data/turbo-smoke-transcripts")
gold_mds = sorted(gold_dir.glob("*.md"))
turbo_mds = sorted(turbo_dir.glob("*.md"))
print(f"gold files: {len(gold_mds)}  turbo files: {len(turbo_mds)}")

# Match by title line
def title_of(p: Path) -> str:
    for line in p.read_text(encoding="utf-8").splitlines()[:5]:
        if line.startswith("# Title:"):
            return line.split(":", 1)[1].strip()
    return p.stem

gold_by_title = {title_of(p): p for p in gold_mds}
for tpath in turbo_mds:
    title = title_of(tpath)
    gpath = gold_by_title.get(title)
    print("---")
    print("title:", title[:80])
    print("turbo:", tpath.name)
    if not gpath:
        print("NO GOLD MATCH")
        continue
    print("gold:", gpath.name)
    gt, tt = body(gpath), body(tpath)
    gt_tok, tt_tok = tokens(gt), tokens(tt)
    if not gt_tok or not tt_tok:
        print("empty token set")
        continue
    inter = len(gt_tok & tt_tok)
    jaccard = inter / len(gt_tok | tt_tok)
    recall = inter / len(gt_tok)
    print(f"gold_chars={len(gt)} turbo_chars={len(tt)}")
    print(f"token_jaccard={jaccard:.3f}  gold_token_recall={recall:.3f}")
    print("turbo preview:", tt[:200].replace("\n", " "))
PY

echo "Smoke turbo parallel complete."
