#!/usr/bin/env bash
# Headless command-line entry point. Safe to symlink into ~/.local/bin.
set -e
HERE="$(dirname "$(readlink -f "$0")")"
VENV="$HERE/.venv"

if [ ! -d "$VENV" ]; then
    echo "venv not found at $VENV, run setup first (see README.md)." >&2
    exit 1
fi

exec "$VENV/bin/python" "$HERE/cli.py" "$@"
