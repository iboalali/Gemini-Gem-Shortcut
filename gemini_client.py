"""Streaming wrapper around the Gemini generativelanguage REST API."""
from __future__ import annotations

import json
from typing import Iterator

import httpx

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent"

# Ordered `thinkingLevel` values to try for each checkbox state. The first entry
# is the preferred one; later entries are fallbacks for models that reject it
# with an HTTP 400 mentioning the thinking level. `None` means "send no
# thinkingConfig at all", which every model accepts.
#
# - Thinking on: "high" is accepted by every Gemini model that thinks.
# - Thinking off: "minimal" disables thinking entirely (0 thought tokens) on the
#   Flash-Lite line and most Flash models, but some Flash models refuse it and
#   only go down to "low", which still thinks a little. There is no level below
#   that on those models.
_THINKING_LEVELS_ON: tuple[str | None, ...] = ("high", None)
_THINKING_LEVELS_OFF: tuple[str | None, ...] = ("minimal", "low", None)


class GeminiError(RuntimeError):
    """Raised when the API returns an error or the response can't be parsed."""


def stream_generate(
    api_key: str,
    model: str,
    system_instruction: str,
    contents: list[dict],
    thinking: bool | None = None,
    timeout: float = 60.0,
) -> Iterator[str]:
    """Yield text deltas from a streamGenerateContent call.

    `contents` is the conversation so far as the API expects it:
        [{"role": "user", "parts": [{"text": "..."}]},
         {"role": "model", "parts": [{"text": "..."}]}, ...]

    `thinking` controls `generationConfig.thinkingConfig.thinkingLevel`:
    True asks for the deepest level, False for the shallowest the model
    allows, None leaves the model's default untouched. A level the model
    rejects is retried with the next fallback (see `_THINKING_LEVELS_*`),
    so a Gem's checkbox works across models with different support.
    """
    if not api_key:
        raise GeminiError("API key is not set. Open settings (gear icon) to add one.")

    body: dict = {"contents": contents}
    if system_instruction.strip():
        body["system_instruction"] = {"parts": [{"text": system_instruction}]}

    if thinking is None:
        levels: tuple[str | None, ...] = (None,)
    elif thinking:
        levels = _THINKING_LEVELS_ON
    else:
        levels = _THINKING_LEVELS_OFF

    for i, level in enumerate(levels):
        if level is None:
            body.pop("generationConfig", None)
        else:
            body["generationConfig"] = {"thinkingConfig": {"thinkingLevel": level}}
        try:
            yield from _stream_once(api_key, model, body, timeout)
            return
        except _UnsupportedThinkingLevel:
            if i == len(levels) - 1:
                raise GeminiError(
                    f"Model {model} rejected every thinking level, including none."
                )
            continue


class _UnsupportedThinkingLevel(Exception):
    """The model rejected the requested `thinkingLevel` (HTTP 400)."""


def _stream_once(api_key: str, model: str, body: dict, timeout: float) -> Iterator[str]:
    url = ENDPOINT.format(model=model)
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    params = {"alt": "sse"}

    try:
        with httpx.stream(
            "POST", url, headers=headers, params=params, json=body, timeout=timeout
        ) as r:
            if r.status_code != 200:
                # Drain the body so we can include the message.
                detail = r.read().decode("utf-8", errors="replace")
                # The API answers an unsupported level with e.g.
                # "Thinking level MINIMAL is not supported for this model" or
                # "Thinking level is not supported for this model". Nothing has
                # been yielded yet, so the caller can safely retry.
                if (
                    r.status_code == 400
                    and "generationConfig" in body
                    and "thinking level" in detail.lower()
                ):
                    raise _UnsupportedThinkingLevel()
                raise GeminiError(_format_http_error(r.status_code, detail))

            for line in r.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if not payload:
                    continue
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                text = _extract_text(chunk)
                if text:
                    yield text
    except httpx.HTTPError as e:
        raise GeminiError(f"Network error: {e}") from e


def _extract_text(chunk: dict) -> str:
    candidates = chunk.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict))


def _format_http_error(status: int, body: str) -> str:
    # Gemini API returns JSON like {"error": {"message": "...", "status": "..."}}.
    try:
        parsed = json.loads(body)
        msg = parsed.get("error", {}).get("message")
        if msg:
            return f"HTTP {status}: {msg}"
    except json.JSONDecodeError:
        pass
    snippet = body.strip().replace("\n", " ")[:300]
    return f"HTTP {status}: {snippet}"
