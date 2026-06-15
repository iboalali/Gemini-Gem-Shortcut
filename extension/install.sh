#!/usr/bin/env bash
# Install the Gemini Gem Shortcut Positioner GNOME Shell extension.
#
# Copies the extension into ~/.local/share/gnome-shell/extensions/,
# compiles the gsettings schema, and enables the extension. On Wayland
# (GNOME's default) you must log out and back in for GNOME Shell to
# reload extensions — there is no Alt+F2 + r trick on Wayland.

set -euo pipefail

UUID="gemini-gem-shortcut@iboalali.com"
SRC_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)/$UUID"
DEST_DIR="$HOME/.local/share/gnome-shell/extensions/$UUID"

if [[ ! -d "$SRC_DIR" ]]; then
    echo "Error: source directory not found: $SRC_DIR" >&2
    exit 1
fi

if ! command -v glib-compile-schemas >/dev/null 2>&1; then
    echo "Error: glib-compile-schemas not found. Install libglib2.0-bin:" >&2
    echo "  sudo apt install libglib2.0-bin" >&2
    exit 1
fi

echo "Installing $UUID …"
mkdir -p "$DEST_DIR"
cp -r "$SRC_DIR/." "$DEST_DIR/"

echo "Compiling schemas …"
glib-compile-schemas "$DEST_DIR/schemas/"

echo "Enabling extension …"
gnome-extensions enable "$UUID"

cat <<EOF

Done. Log out and back in to load the extension into GNOME Shell.

After re-login, verify with:
  gnome-extensions info $UUID

Open the preferences dialog with:
  gnome-extensions prefs $UUID
EOF
