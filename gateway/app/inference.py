from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .config import Settings


async def list_models(settings: Settings) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    if settings.models_dir.exists():
        for path in sorted(settings.models_dir.glob("*.gguf")):
            models.append(
                {
                    "id": path.stem,
                    "object": "model",
                    "owned_by": "eigeneai",
                    "path": str(path),
                }
            )
    if not models:
        models.append(
            {
                "id": settings.default_model,
                "object": "model",
                "owned_by": "eigeneai",
            }
        )

    if not settings.use_mock:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{settings.llama_cpp_url.rstrip('/')}/v1/models")
                if resp.status_code == 200:
                    remote = resp.json().get("data") or []
                    if remote:
                        return remote
        except Exception:
            pass
    return models


async def health_backend(settings: Settings) -> dict[str, Any]:
    if settings.use_mock:
        return {"backend": "mock", "ok": True, "detail": "MOCK_INFERENCE aktiv"}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            # llama.cpp server typically exposes /health or /v1/models
            for path in ("/health", "/v1/models"):
                try:
                    resp = await client.get(f"{settings.llama_cpp_url.rstrip('/')}{path}")
                    if resp.status_code < 500:
                        return {
                            "backend": "llama.cpp",
                            "ok": resp.status_code < 400,
                            "url": settings.llama_cpp_url,
                            "status_code": resp.status_code,
                        }
                except Exception:
                    continue
        return {"backend": "llama.cpp", "ok": False, "url": settings.llama_cpp_url}
    except Exception as exc:
        return {"backend": "llama.cpp", "ok": False, "error": str(exc)}


async def stream_chat_completion(
    settings: Settings,
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """Yields SSE `data:` payloads (OpenAI chat.completion.chunk JSON strings)."""
    if settings.use_mock:
        async for chunk in _mock_stream(model, messages):
            yield chunk
        return

    payload: dict[str, Any] = {
        "model": model or settings.default_model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    url = f"{settings.llama_cpp_url.rstrip('/')}/v1/chat/completions"
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data:
                        yield data


async def _mock_stream(model: str, messages: list[dict[str, str]]) -> AsyncIterator[str]:
    last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    reply = (
        f"[Mock-Modus] Hallo! Ich bin EigeneAI ohne echte GPU. "
        f"Dein Model-Alias ist „{model}“. "
        f"Du schriebst: „{last_user[:200]}“. "
        f"Auf der MI50 antwortet hier llama.cpp (ROCm 6.3.3)."
    )
    completion_id = f"chatcmpl-mock-{uuid.uuid4().hex[:8]}"
    created = int(time.time())
    # role chunk
    yield json.dumps(
        {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        },
        ensure_ascii=False,
    )
    # stream by words for realistic SSE
    words = reply.split(" ")
    for i, word in enumerate(words):
        piece = word if i == 0 else f" {word}"
        yield json.dumps(
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
            },
            ensure_ascii=False,
        )
        await _sleep(0.02)
    yield json.dumps(
        {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
        ensure_ascii=False,
    )
    yield "[DONE]"


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
