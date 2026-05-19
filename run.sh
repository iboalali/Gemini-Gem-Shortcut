#!/usr/bin/env bash
# Launcher for Gemini Gem Shortcut. Bind a GNOME keyboard shortcut to this file.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/.venv"

if [ ! -d "$VENV" ]; then
    echo "venv not found at $VENV — run setup first (see README.md)." >&2
    exit 1
fi

# Use the venv's python so httpx is importable, but keep system PyGObject available
# via the venv's --system-site-packages flag (set at venv creation time).
exec "$VENV/bin/python" "$HERE/main.py" "$@"
