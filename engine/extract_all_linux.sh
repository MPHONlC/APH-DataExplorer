#!/bin/bash
# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.


HERE=$(cd "$(dirname "$0")" && pwd)
ESO="${ESO_DIR:?Set ESO_DIR to the game folder (the one with depot/ and game/)}"
ROOT="${1:-$HERE/../EXTRACTED}"
START="${2:-0}"
mkdir -p "$ROOT/_raw/game" "$ROOT/_raw/depot"
ROOT=$(cd "$ROOT" && pwd)
PY=python3
python3 -c "import PIL" 2>/dev/null || PY="uv run --with pillow python"

stamp() { echo "[$(date '+%F %T')] $*"; }

if [ ! -d "$ROOT/UI" ]; then
	stamp "game archive"
	"$HERE/esoextractdata-linux.sh" "$ESO/game/client/game.mnf" "$ROOT/_raw/game" -z "$ROOT/_raw/game_zosft.txt" -m "$ROOT/_raw/game_mnf.txt" > "$ROOT/_raw/game.log" 2>&1
	python3 "$HERE/organize_extracted.py" "$ROOT" game
fi

stamp "depot archive from index $START"
args=(-z "$ROOT/_raw/depot_zosft.txt" -m "$ROOT/_raw/depot_mnf.txt")
[ "$START" != 0 ] && args+=(-s "$START")
"$HERE/esoextractdata-linux.sh" "$ESO/depot/eso.mnf" "$ROOT/_raw/depot" "${args[@]}" >> "$ROOT/_raw/depot.log" 2>&1
stamp "depot exit $?"

stamp "sorting"
python3 "$HERE/organize_extracted.py" "$ROOT" depot

stamp "textures to PNG"
for kind in TEXTURES UI MAPS; do [ -d "$ROOT/$kind" ] && $PY "$HERE/convertdds.py" "$ROOT/$kind"; done

stamp "LANG to CSV"
find "$ROOT" -path "$ROOT/_raw" -prune -o -type f -iname "*.lang" -print | while read -r f; do
	[ -f "$f.csv" ] || "$HERE/esoextractdata-linux.sh" -l "$f" -o "$f.csv" > /dev/null 2>&1 && echo "  $f.csv"
done
stamp "done"
