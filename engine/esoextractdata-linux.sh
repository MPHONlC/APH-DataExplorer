#!/bin/bash
# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.

HERE=$(cd "$(dirname "$0")" && pwd)
TOOL="${ESOEXTRACT_DIR:-$HERE}"
ESO="${ESO_DIR:-}"
WINE="${WINE:-wine}"
export WINEPREFIX="${WINEPREFIX:-$HOME/.local/share/wineprefixes/esoextract}"
export WINEDEBUG=-all
mkdir -p "$WINEPREFIX"

if [ ! -f "$TOOL/EsoExtractData.exe" ]; then
	echo "EsoExtractData.exe is not in $TOOL (set ESOEXTRACT_DIR to the folder you unpacked it into)" >&2
	exit 3
fi
if ! command -v "$WINE" > /dev/null 2>&1; then
	echo "Wine was not found ($WINE). Install Wine, or set WINE to a Proton build's files/bin/wine." >&2
	exit 4
fi

WINEPATH_BIN="$(dirname "$(command -v "$WINE")")/winepath"

winpath() {
	local p="$1"
	case "$p" in "~"*) p="$HOME${p:1}" ;; esac
	case "$p" in /*) ;; *) p="$PWD/$p" ;; esac
	local w=""
	if [ -x "$WINEPATH_BIN" ]; then w=$("$WINEPATH_BIN" -w "$p" 2>/dev/null); fi
	if [ -z "$w" ]; then w="Z:${p//\//\\}"; fi
	if [ -d "$p" ]; then w="${w%\\}\\"; fi
	printf '%s' "$w"
}

if [ "$1" = "--maps" ]; then
	if [ -z "$ESO" ]; then echo "Set ESO_DIR to the game folder (the one with depot/ and game/)" >&2; exit 5; fi
	ROOT="${2:-$PWD/EXTRACTED}"
	mkdir -p "$ROOT/MAPS/tiles"
	ROOT=$(cd "$ROOT" && pwd)
	OUT="$ROOT/MAPS/_extract"
	mkdir -p "$OUT"
	set -- "$ESO/depot/eso.mnf" "$OUT" --matchfilename '\art\maps\' --noparsegr2 --noriffconvert
	MAPS=1
fi

args=()
for a in "$@"; do
	case "$a" in
		/*|./*|../*|"~"*) args+=("$(winpath "$a")") ;;
		*) args+=("$a") ;;
	esac
done

cd "$TOOL" || exit 1
"$WINE" EsoExtractData.exe "${args[@]}"
status=$?

if [ -n "$MAPS" ] && [ $status -eq 0 ]; then
	if python3 -c "import PIL" 2>/dev/null; then
		python3 "$HERE/convertdds.py" "$OUT/art/maps"
	else
		uv run --with pillow python "$HERE/convertdds.py" "$OUT/art/maps"
	fi
	cp -a "$OUT/art/maps/." "$ROOT/MAPS/tiles/"
	rm -rf "$ROOT/MAPS/_extract"
fi
exit $status
