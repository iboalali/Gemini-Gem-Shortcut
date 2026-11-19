"""Headless command-line front end: one prompt in, one streamed reply out.

Three modes, chosen by the first argument:

    cli.py [options] PROMPT...            Gem mode: a Gem and model from the config
    cli.py ask MODEL SYSTEM QUESTION...   plain API call: only the config's API key
    cli.py models [--refresh]             models the API key can use, cached

Every call is a single turn with no conversation history. Token usage goes
into the same store as the window's.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import config
import gemini_client
import usage
from gemini_client import GeminiError

VERSION = "0.1.0"

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "gemini-gem-shortcut"
MODELS_CACHE_PATH = CACHE_DIR / "models.json"
MODELS_CACHE_TTL = 24 * 60 * 60

_STATUS_TEXT = {
    gemini_client.CONNECTING: "connecting…",
    gemini_client.WAITING: "waiting for the model…",
}


# ── argument parsing ────────────────────────────────────────────────────


def _add_reply_options(parser: argparse.ArgumentParser, thinking_help: str) -> None:
    parser.add_argument(
        "--thinking", action=argparse.BooleanOptionalAction, default=None, help=thinking_help
    )
    parser.add_argument(
        "-c", "--copy", action="store_true", help="also copy the full reply to the clipboard (wl-copy)"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="print the model and token usage to stderr"
    )


def _gem_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gemini-gem",
        description=(
            "Send a prompt to Gemini using a Gem from the Gemini Gem Shortcut config. "
            "With no prompt argument, the prompt is read from stdin. A '-' argument "
            "inserts stdin at that spot, e.g. cat notes.txt | gemini-gem 'Summarize:' -"
        ),
        epilog=(
            "Subcommands: 'gemini-gem ask MODEL SYSTEM QUESTION...' calls the API with "
            "only the API key from the config, and 'gemini-gem models' lists the models "
            "the key can use. Run either with -h for details. To send a prompt that "
            "starts with one of those words in Gem mode, put '--' first."
        ),
    )
    parser.add_argument(
        "prompt", nargs="*", help="prompt text (words are joined with spaces, '-' is stdin)"
    )
    parser.add_argument("--version", action="version", version=f"gemini-gem {VERSION}")
    parser.add_argument("-g", "--gem", help="Gem name (default: the config's default_gem)")
    parser.add_argument("-m", "--model", help="model ID (default: the Gem's default model)")
    _add_reply_options(parser, "override the Gem's thinking setting")
    parser.add_argument("--list-gems", action="store_true", help="list Gem names and exit")
    parser.add_argument(
        "--list-models", action="store_true", help="list the models in the config and exit"
    )
    parser.add_argument(
        "--usage", action="store_true", help="print the local token usage summary and exit"
    )
    return parser


def _ask_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gemini-gem ask",
        usage=(
            "gemini-gem ask [options] MODEL SYSTEM QUESTION...\n"
            "       gemini-gem ask [options] --system-file FILE MODEL QUESTION..."
        ),
        description=(
            "Call the Gemini API directly. Only the API key is taken from the config; "
            "no Gem, model default or other setting applies. The system instruction is "
            "the argument after MODEL, or the contents of --system-file, in which case "
            "that argument is left out. Put '--' before MODEL when SYSTEM may start with '-'."
        ),
    )
    parser.add_argument(
        "model", metavar="MODEL", help="model ID, e.g. gemini-3.8-flash (see 'gemini-gem models')"
    )
    parser.add_argument(
        "rest",
        nargs="*",
        metavar="SYSTEM QUESTION",
        help="system instruction ('' for none), then the question "
        "(words are joined with spaces, '-' is stdin)",
    )
    parser.add_argument(
        "-s",
        "--system-file",
        metavar="FILE",
        help="read the system instruction from FILE (UTF-8) instead of the SYSTEM argument",
    )
    _add_reply_options(
        parser, "ask for the model's highest or lowest thinking level (default: the model's own)"
    )
    return parser


def _read_system_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as e:
        reason = e.strerror or str(e)
        raise GeminiError(f"Could not read the system file {path}: {reason}", "bad system file") from e
    except UnicodeDecodeError as e:
        raise GeminiError(f"The system file {path} is not UTF-8 text.", "bad system file") from e


def _models_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gemini-gem models",
        description=(
            "List the models the API key can use for generateContent. The list is cached "
            f"for {MODELS_CACHE_TTL // 3600} h in {MODELS_CACHE_PATH}."
        ),
    )
    parser.add_argument("-r", "--refresh", action="store_true", help="ignore the cache and ask the API")
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "-l", "--long", action="store_true", help="also show display name and token limits"
    )
    output.add_argument("--json", action="store_true", help="print the API's model entries as JSON")
    return parser


# ── shared helpers ──────────────────────────────────────────────────────


def _resolve_prompt(words: list[str]) -> str:
    # Stdin is read only on request: a caller's stdin can be a pipe that never
    # closes, and an unconditional read would block forever.
    words = words or ["-"]
    if "-" not in words:
        return " ".join(words).strip()
    if sys.stdin.isatty():
        raise GeminiError("No prompt given, as an argument or on stdin.", "no prompt")
    stdin_text = sys.stdin.read().strip()
    split = words.index("-")
    before = " ".join(words[:split]).strip()
    after = " ".join(w for w in words[split + 1 :] if w != "-").strip()
    return "\n\n".join(p for p in (before, stdin_text, after) if p)


def _read_api_key() -> str:
    """The API key from the config, without creating a config file when there is none."""
    try:
        with config.CONFIG_PATH.open("r", encoding="utf-8") as f:
            key = json.load(f).get("api_key", "")
    except FileNotFoundError:
        key = ""
    except (OSError, ValueError) as e:
        raise GeminiError(f"Could not read {config.CONFIG_PATH}: {e}", "bad config") from e
    if not key:
        raise GeminiError(
            f"No API key in {config.CONFIG_PATH}. Add one in the app's settings.", "no API key"
        )
    return key


def _record_usage(model: str, metadata: dict) -> None:
    if not metadata:
        return
    try:
        usage.record(model, metadata)
    except OSError as e:
        print(f"warning: could not record token usage: {e}", file=sys.stderr)


def _copy_to_clipboard(text: str) -> None:
    if shutil.which("wl-copy") is None:
        print("warning: wl-copy not found, reply not copied", file=sys.stderr)
        return
    try:
        # wl-copy forks a daemon that serves the clipboard; with inherited stdout
        # it would keep a reader like `cli.sh -c x | less` waiting for EOF.
        subprocess.run(
            ["wl-copy"],
            input=text,
            text=True,
            check=True,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        # Mutter has no data-control protocol, so wl-copy maps a 1x1 window and
        # waits for keyboard focus, which GNOME denies to a process without an
        # activation token.
        print(
            "warning: reply not copied, wl-copy timed out waiting for GNOME to focus it",
            file=sys.stderr,
        )
    except (subprocess.SubprocessError, OSError) as e:
        print(f"warning: copying to the clipboard failed: {e}", file=sys.stderr)


class _StatusLine:
    """Transient progress text on stderr, shown only when stderr is a terminal."""

    def __init__(self) -> None:
        self.enabled = sys.stderr.isatty()
        self.shown = False

    def __call__(self, phase: str) -> None:
        if not self.enabled:
            return
        text = _STATUS_TEXT.get(phase)
        if text is None:
            self.clear()
            return
        sys.stderr.write(f"\r\033[2K{text}")
        sys.stderr.flush()
        self.shown = True

    def clear(self) -> None:
        if self.shown:
            sys.stderr.write("\r\033[2K")
            sys.stderr.flush()
            self.shown = False


def _stream_reply(
    api_key: str,
    model: str,
    system_instruction: str,
    prompt: str,
    thinking: bool | None,
    copy: bool,
    verbose: bool,
) -> None:
    status = _StatusLine()
    usage_meta: dict = {}
    reply: list[str] = []
    stream = gemini_client.stream_generate(
        api_key,
        model,
        system_instruction,
        [{"role": "user", "parts": [{"text": prompt}]}],
        thinking=thinking,
        on_usage=usage_meta.update,
        on_status=status,
    )
    try:
        for delta in stream:
            status.clear()
            reply.append(delta)
            sys.stdout.write(delta)
            sys.stdout.flush()
    finally:
        # Closing fires on_usage for a reply cut off by Ctrl+C; those tokens are billed too.
        stream.close()
        status.clear()
        _record_usage(model, usage_meta)

    text = "".join(reply)
    if not text:
        raise GeminiError("The model returned an empty reply.", "empty reply")
    if not text.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()

    if copy:
        _copy_to_clipboard(text)
    if verbose and usage_meta:
        print(usage.format_response(usage_meta), file=sys.stderr)


# ── Gem mode ────────────────────────────────────────────────────────────


def _pick_gem(cfg: dict, name: str | None) -> dict:
    gems = cfg.get("gems", [])
    if name is not None:
        gem = config.find_gem(cfg, name)
        if gem is None:
            names = ", ".join(g.get("name", "") for g in gems) or "none"
            raise GeminiError(f'No Gem named "{name}". Gems: {names}.', "unknown Gem")
        return gem
    return config.find_gem(cfg, cfg.get("default_gem", "")) or (gems[0] if gems else {})


def _pick_model(cfg: dict, gem: dict, override: str | None) -> str:
    if override:
        return override
    models = cfg.get("models", [])
    gem_default = gem.get("default_model")
    return gem_default if gem_default in models else cfg.get("default_model", "")


def _run_gem(argv: list[str]) -> int:
    args = _gem_parser().parse_args(argv)
    cfg = config.load()

    if args.list_gems:
        for gem in cfg.get("gems", []):
            print(gem.get("name", ""))
        return 0
    if args.list_models:
        for model in cfg.get("models", []):
            print(model)
        return 0
    if args.usage:
        print(usage.summary(usage.load()))
        return 0

    gem = _pick_gem(cfg, args.gem)
    model = _pick_model(cfg, gem, args.model)
    prompt = _resolve_prompt(args.prompt)
    thinking = bool(gem.get("thinking", False)) if args.thinking is None else args.thinking
    if args.verbose:
        print(f"gem: {gem.get('name', '')}, model: {model}", file=sys.stderr)
    _stream_reply(
        cfg.get("api_key", ""),
        model,
        gem.get("system_instruction", ""),
        prompt,
        thinking,
        args.copy,
        args.verbose,
    )
    return 0


# ── ask ─────────────────────────────────────────────────────────────────


def _run_ask(argv: list[str]) -> int:
    parser = _ask_parser()
    args = parser.parse_args(argv)
    if args.system_file is None:
        if len(args.rest) < 2:
            parser.error("the following arguments are required: SYSTEM, QUESTION")
        system, question = args.rest[0], args.rest[1:]
    else:
        if not args.rest:
            parser.error("the following arguments are required: QUESTION")
        system, question = _read_system_file(args.system_file), args.rest
    api_key = _read_api_key()
    prompt = _resolve_prompt(question)
    if not prompt:
        raise GeminiError("The question is empty.", "no prompt")
    if args.verbose:
        print(f"model: {args.model}", file=sys.stderr)
    _stream_reply(api_key, args.model, system, prompt, args.thinking, args.copy, args.verbose)
    return 0


# ── models ──────────────────────────────────────────────────────────────


def _key_id(api_key: str) -> str:
    # Ties the cache to the key without storing the key itself.
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def _load_models_cache(api_key: str) -> dict | None:
    try:
        with MODELS_CACHE_PATH.open("r", encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        return None
    if cache.get("key_id") != _key_id(api_key) or not isinstance(cache.get("models"), list):
        return None
    return cache


def _save_models_cache(api_key: str, models: list[dict]) -> None:
    cache = {"fetched_at": time.time(), "key_id": _key_id(api_key), "models": models}
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = MODELS_CACHE_PATH.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, MODELS_CACHE_PATH)
    except OSError as e:
        print(f"warning: could not write the model cache: {e}", file=sys.stderr)


def _get_models(api_key: str, refresh: bool) -> list[dict]:
    cache = _load_models_cache(api_key)
    if cache and not refresh and time.time() - cache.get("fetched_at", 0) < MODELS_CACHE_TTL:
        return cache["models"]
    try:
        models = gemini_client.list_models(api_key)
    except GeminiError as e:
        if cache is None:
            raise
        age_h = (time.time() - cache.get("fetched_at", 0)) / 3600
        print(f"warning: {e} Showing the cached list from {age_h:.0f} h ago.", file=sys.stderr)
        return cache["models"]
    _save_models_cache(api_key, models)
    return models


def _model_id(model: dict) -> str:
    return model.get("name", "").removeprefix("models/")


def _run_models(argv: list[str]) -> int:
    args = _models_parser().parse_args(argv)
    models = _get_models(_read_api_key(), args.refresh)

    if args.json:
        json.dump(models, sys.stdout, indent=2)
        sys.stdout.write("\n")
    elif args.long:
        width = max((len(_model_id(m)) for m in models), default=0)
        for m in models:
            limits = (
                f"in {usage.format_tokens(int(m.get('inputTokenLimit', 0)))}, "
                f"out {usage.format_tokens(int(m.get('outputTokenLimit', 0)))}"
            )
            print(f"{_model_id(m):<{width}}  {m.get('displayName', '')} ({limits})")
    else:
        for m in models:
            print(_model_id(m))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv and argv[0] == "ask":
            return _run_ask(argv[1:])
        if argv and argv[0] == "models":
            return _run_models(argv[1:])
        return _run_gem(argv)
    except GeminiError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
