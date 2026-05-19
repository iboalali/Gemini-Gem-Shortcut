"""Streaming wrapper around the Gemini generativelanguage REST API."""
from __future__ import annotations

import json
from typing import Iterator

import httpx

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent"


class GeminiError(RuntimeError):
    """Raised when the API returns an error or the response can't be parsed."""


def stream_generate(
    api_key: str,
    model: str,
    system_instruction: str,
    contents: list[dict],
    timeout: float = 60.0,
) -> Iterator[str]:
    """Yield text deltas from a streamGenerateContent call.

    `contents` is the conversation so far as the API expects it:
        [{"role": "user", "parts": [{"text": "..."}]},
         {"role": "model", "parts": [{"text": "..."}]}, ...]
    """
    if not api_key:
        raise GeminiError("API key is not set. Open settings (gear icon) to add one.")

    body: dict = {"contents": contents}
    if system_instruction.strip():
        body["system_instruction"] = {"parts": [{"text": system_instruction}]}

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
