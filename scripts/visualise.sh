#!/usr/bin/env bash
# audiomorph — full pipeline: analyse + build .blend + render + mux.
#
# Usage:
#   ./scripts/visualise.sh <audio_file> [--start SEC] [--end SEC] [--res 1080] [--samples 24] [--fps 30]
#
# Output goes to ./output/<song-slug>/{features.json, scene.blend, frames/, song-slug.mp4}
set -euo pipefail

usage() {
    cat <<'EOF'
audiomorph
==========
./scripts/visualise.sh <audio_file> [options]

Options:
  --start  SEC      Start time in seconds (default: 0)
  --end    SEC      End time in seconds (default: end-of-song)
  --res    PX       Vertical resolution (default: 1080)
  --samples N       EEVEE TAA samples per frame (default: 24)
  --fps    N        Frames per second (default: 30)
  --skip-analyse    Reuse an existing features.json
  --skip-build      Reuse an existing scene.blend
EOF
}

if [[ $# -lt 1 || "$1" == "-h" || "$1" == "--help" ]]; then
    usage
    exit 1
fi

AUDIO="$1"
shift
START_SEC=0
END_SEC=""
RES=1080
SAMPLES=24
FPS=30
SKIP_ANALYSE=0
SKIP_BUILD=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --start)        START_SEC="$2"; shift 2 ;;
        --end)          END_SEC="$2";   shift 2 ;;
        --res)          RES="$2";       shift 2 ;;
        --samples)      SAMPLES="$2";   shift 2 ;;
        --fps)          FPS="$2";       shift 2 ;;
        --skip-analyse) SKIP_ANALYSE=1; shift ;;
        --skip-build)   SKIP_BUILD=1;   shift ;;
        *) echo "Unknown option: $1"; usage; exit 1 ;;
    esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f "$AUDIO" ]]; then
    echo "audio file not found: $AUDIO"
    exit 1
fi

BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
if [[ ! -x "$BLENDER" ]]; then
    echo "blender not found at $BLENDER (override with BLENDER=...)"
    exit 1
fi

# Slugify the filename (drop extension + master tags + spaces).
NAME="$(basename "$AUDIO")"
SLUG="$(echo "$NAME" \
    | sed 's/\[[^]]*\]//g' \
    | sed -E 's/\.(wav|mp3|flac|aiff|m4a|ogg)$//I' \
    | tr '[:upper:]' '[:lower:]' \
    | tr -cs 'a-z0-9' '-' \
    | sed 's/^-//;s/-$//')"

OUT="$ROOT/output/$SLUG"
mkdir -p "$OUT/frames"

FEATURES="$OUT/features.json"
BLEND="$OUT/scene.blend"
VIDEO="$OUT/$SLUG.mp4"

# 1. Analyse
if [[ $SKIP_ANALYSE -eq 0 || ! -f "$FEATURES" ]]; then
    echo ">> [1/4] analysing audio → $FEATURES"
    "$ROOT/.venv/bin/python" analysis/analyze.py "$AUDIO" "$FEATURES" --fps "$FPS"
fi

# 2. Build scene
START_FRAME=$(python3 -c "print(int($START_SEC * $FPS))")
if [[ -n "$END_SEC" ]]; then
    END_FRAME=$(python3 -c "print(int($END_SEC * $FPS))")
else
    END_FRAME=-1
fi

if [[ $SKIP_BUILD -eq 0 || ! -f "$BLEND" ]]; then
    echo ">> [2/4] building Blender scene → $BLEND"
    "$BLENDER" --background --python blender/build_scene.py -- \
        --features "$FEATURES" \
        --audio "$AUDIO" \
        --out "$BLEND" \
        --start "$START_FRAME" \
        --end "$END_FRAME" \
        --fps "$FPS" \
        --res "$RES" \
        --samples "$SAMPLES"
fi

# 3. Render PNG sequence
echo ">> [3/4] rendering frames → $OUT/frames/"
rm -f "$OUT"/frames/*.png 2>/dev/null || true
"$BLENDER" --background "$BLEND" \
    --render-output "//frames/frame_####" \
    --render-format PNG \
    --render-anim

# 4. Mux audio + video with ffmpeg
echo ">> [4/4] muxing video + audio → $VIDEO"
# Trim audio to the rendered range so it stays in sync.
DURATION=$(python3 -c "
import json
d = json.load(open('$FEATURES'))
n = d['meta']['n_frames']
fps = d['meta']['fps']
start = $START_FRAME
end = ${END_FRAME}
end = (n - 1) if end < 0 else min(end, n - 1)
print((end - start + 1) / fps)
")

ffmpeg -y \
    -framerate "$FPS" -i "$OUT/frames/frame_%04d.png" \
    -ss "$START_SEC" -t "$DURATION" -i "$AUDIO" \
    -c:v libx264 -pix_fmt yuv420p -crf 18 -preset slow \
    -c:a aac -b:a 320k -shortest \
    "$VIDEO"

echo ""
echo "✓ done: $VIDEO"
