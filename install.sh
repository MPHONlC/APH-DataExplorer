#!/bin/sh
# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.
set -e
HERE=$(dirname "$(readlink -f "$0")")
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
ENTRY="$DATA/applications/aph-data-explorer.desktop"
ICON="$DATA/icons/hicolor/256x256/apps/aph-data-explorer.png"

if [ "$1" = "--uninstall" ]; then
	rm -f "$ENTRY" "$ICON"
	update-desktop-database "$DATA/applications" >/dev/null 2>&1 || true
	echo "Removed the app menu entry."
	exit 0
fi

mkdir -p "$DATA/applications" "$(dirname "$ICON")"
QT_QPA_PLATFORM=offscreen python3 "$HERE/main.py" --write-icon "$ICON"
EXEC=$(printf '%s' "$HERE/aph-data-explorer" | sed 's/[\\"`$]/\\\\&/g')
cat > "$ENTRY" <<DESKTOP
[Desktop Entry]
Type=Application
Name=APH Data Explorer
Comment=Browse, search, preview and extract The Elder Scrolls Online's game archives
Exec="$EXEC"
Icon=aph-data-explorer
Terminal=false
Categories=Utility;
StartupWMClass=aph-data-explorer
DESKTOP
update-desktop-database "$DATA/applications" >/dev/null 2>&1 || true
gtk-update-icon-cache -q "$DATA/icons/hicolor" >/dev/null 2>&1 || true
echo "Added APH Data Explorer to your app menu ($ENTRY)."
echo "If you move this folder, run ./install.sh again."
