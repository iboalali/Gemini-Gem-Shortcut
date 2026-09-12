"""Local token accounting for gemini-gem-shortcut.

The Gemini API has no usage or quota endpoint: the only usage it reports is the
`usageMetadata` block on each response, and a 429 names the quota you blew
without saying how much of it you had used. A running total therefore has to be
accumulated client-side, which is what this module does.

Stored at ~/.config/gemini-gem-shortcut/usage.json (0600), bucketed by day and
model:

    {"version": 1,
     "days": {"2026-09-13": {"gemini-3.8-flash": {"requests": 4, ...}}}}

The store is advisory, not authoritative. It only sees replies this app
streamed to completion, so it misses anything cancelled mid-stream and
everything the key was used for elsewhere.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

from config import CONFIG_DIR

USAGE_PATH = CONFIG_DIR / "usage.json"

# Days of history kept. Pruned on every write so the file stays small.
RETENTION_DAYS = 90

# Bucket counter -> the `usageMetadata` field it accumulates. `total_tokens`
# already includes thinking, so summing the other three does not reproduce it.
_COUNTERS: tuple[tuple[str, str], ...] = (
    ("prompt_tokens", "promptTokenCount"),
    ("candidates_tokens", "candidatesTokenCount"),
    ("thoughts_tokens", "thoughtsTokenCount"),
    ("total_tokens", "totalTokenCount"),
)


def _zero_bucket() -> dict:
    return {"requests": 0, **{name: 0 for name, _ in _COUNTERS}}


def load() -> dict:
    """Read the store, returning an empty one if it is missing or unreadable."""
    try:
        with USAGE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "days": {}}
    if not isinstance(data, dict) or not isinstance(data.get("days"), dict):
        return {"version": 1, "days": {}}
    return data


def save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = USAGE_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, USAGE_PATH)


def record(model: str, metadata: dict, when: date | None = None) -> dict:
    """Add one response's `usageMetadata` to the store and return the new store.

    Raises OSError if the store can't be written; callers should treat
    accounting as best-effort and carry on.
    """
    day = (when or date.today()).isoformat()
    data = load()
    buckets = data.setdefault("days", {}).setdefault(day, {})
    # Merge onto a zeroed bucket so a store written by an older version (or
    # hand-edited) can't KeyError here.
    bucket = {**_zero_bucket(), **buckets.get(model or "unknown", {})}
    bucket["requests"] += 1
    for name, field in _COUNTERS:
        bucket[name] += _as_int(metadata.get(field))
    buckets[model or "unknown"] = bucket
    _prune(data)
    save(data)
    return data


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _prune(data: dict) -> None:
    cutoff = (date.today() - timedelta(days=RETENTION_DAYS)).isoformat()
    days = data.get("days", {})
    for day in [d for d in days if d < cutoff]:
        del days[day]


def models_for_day(data: dict, when: date | None = None) -> dict[str, dict]:
    """Per-model buckets for one day, newest-first by total tokens."""
    day = (when or date.today()).isoformat()
    buckets = data.get("days", {}).get(day) or {}
    return dict(
        sorted(buckets.items(), key=lambda kv: _as_int(kv[1].get("total_tokens")), reverse=True)
    )


def totals(data: dict, days: int = 1, end: date | None = None) -> dict:
    """Counters summed across every model over the last `days` days, `end` included."""
    last = end or date.today()
    wanted = {(last - timedelta(days=n)).isoformat() for n in range(days)}
    summed = _zero_bucket()
    for day, buckets in (data.get("days") or {}).items():
        if day not in wanted or not isinstance(buckets, dict):
            continue
        for bucket in buckets.values():
            if not isinstance(bucket, dict):
                continue
            summed["requests"] += _as_int(bucket.get("requests"))
            for name, _ in _COUNTERS:
                summed[name] += _as_int(bucket.get(name))
    return summed


def format_tokens(n: int) -> str:
    """Compact token count: 940, 1k, 1.2k, 13.4k, 2.05M."""
    if n < 1000:
        return str(n)
    thousands = n / 1000
    # Hand over to the M form just before rounding would print "1000k".
    if thousands < 999.95:
        text = f"{thousands:.1f}k"
        return text[:-3] + "k" if text.endswith(".0k") else text
    return f"{n / 1_000_000:.2f}M"


def format_response(metadata: dict) -> str:
    """One-line summary of a single reply, for the response area."""
    total = _as_int(metadata.get("totalTokenCount"))
    parts = [
        f"{_as_int(metadata.get('promptTokenCount'))} in",
        f"{_as_int(metadata.get('candidatesTokenCount'))} out",
    ]
    thoughts = _as_int(metadata.get("thoughtsTokenCount"))
    if thoughts:
        parts.append(f"{thoughts} thinking")
    return f"{total} tokens ({', '.join(parts)})"


def _bucket_line(bucket: dict) -> str:
    """One bucket as `2 requests, 28 in, 322 total (294 thinking)`.

    Input tokens come before the total on purpose: the free tier meters
    requests and *input* tokens per model per day, so those two are the
    numbers with a limit attached. Output and thinking tokens dominate the
    total but count against no token quota.
    """
    requests = _as_int(bucket.get("requests"))
    plural = "" if requests == 1 else "s"
    line = (
        f"{requests} request{plural}, "
        f"{format_tokens(_as_int(bucket.get('prompt_tokens')))} in, "
        f"{format_tokens(_as_int(bucket.get('total_tokens')))} total"
    )
    thoughts = _as_int(bucket.get("thoughts_tokens"))
    if thoughts:
        line += f" ({format_tokens(thoughts)} thinking)"
    return line


def summary(data: dict, when: date | None = None) -> str:
    """Multi-line breakdown for the tooltip behind the running total."""
    today = when or date.today()
    lines = [f"Today, {today.isoformat()}"]
    per_model = models_for_day(data, today)
    if not per_model:
        lines.append("  no requests yet")
    for model, bucket in per_model.items():
        lines.append(f"  {model}: {_bucket_line(bucket)}")

    for days, label in ((7, "Last 7 days"), (30, "Last 30 days")):
        lines.append(f"{label}: {_bucket_line(totals(data, days=days, end=today))}")

    lines.append("")
    lines.append('Free-tier quota counts requests and input ("in") per')
    lines.append("model per day, not the total. Counted locally: the")
    lines.append("Gemini API has no usage endpoint.")
    return "\n".join(lines)
