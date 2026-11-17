#!/usr/bin/env bash
# Install the launcher entry and app icon so GNOME shows the icon in the dash.
#
# The .desktop file name must equal APP_ID in main.py: GNOME matches the
# running window to its launcher entry by the Wayland app-id.

set -euo pipefail

APP_ID="com.iboalali.GeminiGemShortcut"
DATA_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
RUN_SH="$(dirname "$DATA_DIR")/run.sh"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS_DIR="$DATA_HOME/applications"
ICON_THEME_DIR="$DATA_HOME/icons/hicolor"
ICON_DIR="$ICON_THEME_DIR/scalable/apps"

# Exec= values inside double quotes need ", `, $ and \ escaped.
EXEC_PATH="$(printf '%s' "$RUN_SH" | sed -e 's/[\\"`$]/\\&/g')"

mkdir -p "$APPS_DIR" "$ICON_DIR"
install -m 0644 "$DATA_DIR/$APP_ID.svg" "$ICON_DIR/$APP_ID.svg"
sed -e "s|@RUN_SH@|$(printf '%s' "$EXEC_PATH" | sed -e 's/[|&\\]/\\&/g')|" \
    "$DATA_DIR/$APP_ID.desktop.in" > "$APPS_DIR/$APP_ID.desktop"
chmod 0644 "$APPS_DIR/$APP_ID.desktop"

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$APPS_DIR/$APP_ID.desktop"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR"
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache --force --ignore-theme-index "$ICON_THEME_DIR" >/dev/null
fi

echo "Installed $APPS_DIR/$APP_ID.desktop"
echo "Installed $ICON_DIR/$APP_ID.svg"
