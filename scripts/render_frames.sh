#!/usr/bin/env bash
# Render frames from a built .blend file. Args: <blend> <output_pattern> [start] [end]
# Output pattern uses Blender's #### token, e.g. output/frames/beat25_####
set -euo pipefail

BLEND="$1"
OUT_PATTERN="$2"
START="${3:-1}"
END="${4:-1}"

BLENDER="/Applications/Blender.app/Contents/MacOS/Blender"

mkdir -p "$(dirname "$OUT_PATTERN")"

"$BLENDER" --background "$BLEND" \
    --render-output "$OUT_PATTERN" \
    --render-format PNG \
    --frame-start "$START" \
    --frame-end "$END" \
    --render-anim
