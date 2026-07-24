#!/usr/bin/env bash
# Smoke: 3 short videos, large-v3, transcription only.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source .venv/bin/activate

VIDEO_ROOT="${VIDEO_ROOT:-/home/clovis/Downloads/Tartube-new/Atlas Brasileiro - Kim Paim}"
SMOKE_DIR="$ROOT/data/smoke-input"
DB="$ROOT/data/smoke-state.db"
AUDIO="$ROOT/data/smoke-audio"
TX="$ROOT/data/smoke-transcripts"
GROK="$ROOT/data/smoke-grok"

mkdir -p "$SMOKE_DIR" "$AUDIO" "$TX" "$GROK"
rm -f "$DB"

# Pick 3 of the shortest mp4s for a fast smoke (still large-v3 quality path)
mapfile -t SHORTS < <(
  find "$VIDEO_ROOT" -maxdepth 1 -type f -name '*.mp4' -printf '%s %p\n' \
    | sort -n | head -3 | awk '{ $1=""; sub(/^ /,""); print }'
)

if [[ ${#SHORTS[@]} -lt 1 ]]; then
  echo "No mp4 found under $VIDEO_ROOT" >&2
  exit 1
fi

# Fresh smoke dir: only symlinks to the short samples
find "$SMOKE_DIR" -mindepth 1 -delete
for f in "${SHORTS[@]}"; do
  ln -sfn "$f" "$SMOKE_DIR/$(basename "$f")"
  echo "smoke sample: $(basename "$f")"
done

pip install -e . -q
python -m vtp discover --input "$SMOKE_DIR" --db "$DB"
python -m vtp run \
  --db "$DB" \
  --audio-dir "$AUDIO" \
  --export-dir "$TX" \
  --model large-v3 \
  --language pt \
  --device auto
python -m vtp status --db "$DB"
python -m vtp export --db "$DB" --transcripts-dir "$TX" --out "$GROK" --format grok

echo "--- sample transcript ---"
ls -la "$TX"
head -n 40 "$TX"/*.md | head -n 50
echo "Smoke complete. Grok pack: $GROK"
