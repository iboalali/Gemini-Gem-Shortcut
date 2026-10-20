"""Streaming wrapper around the Gemini generativelanguage REST API."""
from __future__ import annotations

import json
import re
from typing import Callable, Iterator

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

DEFAULT_TIMEOUT = 60.0
# Short, so a missing network fails fast instead of looking like a slow model.
CONNECT_TIMEOUT = 10.0

# Phases reported through `on_status`. The API sends its response headers
# together with the first token, so between WAITING and STREAMING nothing
# arrives at all: a slow model and a stalled one look the same on the wire.
CONNECTING = "connecting"
WAITING = "waiting"
STREAMING = "streaming"


class GeminiError(RuntimeError):
    """Raised when the API returns an error or the response can't be parsed.

    `reason` is a few words fit for a status line; the message has the detail.
    """

    def __init__(self, message: str, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason or message


def stream_generate(
    api_key: str,
    model: str,
    system_instruction: str,
    contents: list[dict],
    thinking: bool | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    on_usage: Callable[[dict], None] | None = None,
    on_status: Callable[[str], None] | None = None,
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

    `on_usage` is called once with the response's `usageMetadata` dict
    (token counts) after the last delta, and not at all if the stream ends
    before the API reports one. It runs on the caller's thread.

    `on_status` is called with CONNECTING, WAITING and STREAMING as the
    request progresses, also on the caller's thread. A thinking-level retry
    starts again from CONNECTING.
    """
    if not api_key:
        raise GeminiError(
            "API key is not set. Open settings (gear icon) to add one.", "no API key"
        )

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
            yield from _stream_once(api_key, model, body, timeout, on_usage, on_status)
            return
        except _UnsupportedThinkingLevel:
            if i == len(levels) - 1:
                raise GeminiError(
                    f"Model {model} rejected every thinking level, including none.",
                    "thinking level rejected",
                )
            continue


class _UnsupportedThinkingLevel(Exception):
    """The model rejected the requested `thinkingLevel` (HTTP 400)."""


def _stream_once(
    api_key: str,
    model: str,
    body: dict,
    timeout: float,
    on_usage: Callable[[dict], None] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> Iterator[str]:
    url = ENDPOINT.format(model=model)
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    params = {"alt": "sse"}

    # Every SSE chunk carries a `usageMetadata`, and the counts are cumulative
    # for the reply so far (`candidatesTokenCount` grows chunk by chunk,
    # `promptTokenCount` stays put). The last one seen is therefore the total
    # for the whole reply, and reporting only that one keeps the caller from
    # adding up the same tokens several times.
    last_usage: dict | None = None

    def report(status: str) -> None:
        if on_status is not None:
            on_status(status)

    def trace(event: str, _info: dict) -> None:
        if event == "connection.connect_tcp.started":
            report(CONNECTING)
        elif event.endswith(".send_request_body.complete"):
            report(WAITING)

    streaming = False
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=CONNECT_TIMEOUT)) as client, \
                client.stream(
                    "POST", url, headers=headers, params=params, json=body,
                    extensions={"trace": trace},
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
                raise GeminiError(
                    _format_http_error(r.status_code, detail),
                    _http_reason(r.status_code, detail),
                )

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

                usage = chunk.get("usageMetadata")
                if isinstance(usage, dict):
                    last_usage = usage

                text = _extract_text(chunk)
                if text:
                    if not streaming:
                        streaming = True
                        report(STREAMING)
                    yield text
    except httpx.ConnectTimeout as e:
        raise GeminiError(
            f"Could not reach Google within {CONNECT_TIMEOUT:.0f} s. Check the network.",
            "can't reach Google",
        ) from e
    except httpx.ConnectError as e:
        raise GeminiError(
            f"Could not connect to Google: {e}. Check the network.", "no connection"
        ) from e
    except httpx.ReadTimeout as e:
        if streaming:
            raise GeminiError(
                f"{model} stopped sending for {timeout:.0f} s in the middle of the reply.",
                "reply stalled",
            ) from e
        raise GeminiError(
            f"{model} sent nothing for {timeout:.0f} s, so the request was dropped. "
            "The model is probably overloaded: try again or pick another model.",
            "no answer from the model",
        ) from e
    except httpx.HTTPError as e:
        raise GeminiError(f"Network error: {e}", "network error") from e
    finally:
        # Also runs when the consumer abandons the generator (window closed
        # mid-stream), which is why it must not touch anything but the callback.
        if last_usage is not None and on_usage is not None:
            on_usage(last_usage)


def _extract_text(chunk: dict) -> str:
    candidates = chunk.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict))


def _http_reason(status: int, body: str) -> str:
    if status == 503:
        return "model overloaded"
    if status == 429:
        # `limit: 0` is a hard zero allowance (e.g. Pro on the free tier),
        # not a throttle that waiting would lift.
        if "limit: 0" in body:
            return "not on your plan"
        wait = re.search(r"retry in ((?:\d+[hm])*\d+)(?:\.\d+)?s", body)
        return f"rate limit reached, retry in {wait.group(1)}s" if wait else "rate limit reached"
    if status in (400, 403) and "api key" in body.lower():
        return "API key rejected"
    if status == 404:
        return "model not found"
    if status >= 500:
        return "server error at Google"
    return f"HTTP {status}"


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
