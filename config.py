"""Config load/save for gemini-gem-shortcut.

Stored at ~/.config/gemini-gem-shortcut/config.json with 0600 perms.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gemini-gem-shortcut"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_CONFIG: dict = {
    "api_key": "",
    "default_model": "gemini-3.1-flash-lite",
    "default_gem": "General",
    "models": [
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash",
        "gemini-3.1-pro-preview",
    ],
    "gems": [
        {
            "name": "General",
            "system_instruction": "",
            "default_model": None,
            "auto_copy": False,
            "auto_paste_clipboard": False,
        },
    ],
}


def load() -> dict:
    if not CONFIG_PATH.exists():
        save(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Fill in any missing top-level keys from defaults so older configs keep working.
    for key, value in DEFAULT_CONFIG.items():
        cfg.setdefault(key, json.loads(json.dumps(value)))
    return cfg


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)


def find_gem(cfg: dict, name: str) -> dict | None:
    for gem in cfg.get("gems", []):
        if gem.get("name") == name:
            return gem
    return None
