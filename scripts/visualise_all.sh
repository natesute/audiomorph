#!/usr/bin/env bash
# Run audiomorph over every audio file in a directory.
# Usage: ./scripts/visualise_all.sh <directory> [pipeline-options...]
#
# All trailing options are forwarded to ./scripts/visualise.sh, so you can
# do e.g.: ./scripts/visualise_all.sh ~/Downloads/Stems --start 30 --end 60
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <directory> [pipeline-options...]"
    exit 1
fi

DIR="$1"
shift
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -d "$DIR" ]]; then
    echo "not a directory: $DIR"
    exit 1
fi

shopt -s nullglob nocaseglob
FILES=("$DIR"/*.wav "$DIR"/*.mp3 "$DIR"/*.flac "$DIR"/*.aiff "$DIR"/*.m4a)
shopt -u nocaseglob

if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "no audio files found in $DIR"
    exit 1
fi

for f in "${FILES[@]}"; do
    echo ""
    echo "==================================================================="
    echo "==  $(basename "$f")"
    echo "==================================================================="
    "$ROOT/scripts/visualise.sh" "$f" "$@" || {
        echo "  ! failed on $f, continuing"
        continue
    }
done

echo ""
echo "all done — outputs in $ROOT/output/"
