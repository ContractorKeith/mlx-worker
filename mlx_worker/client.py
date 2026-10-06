"""HTTP client for an OpenAI-compatible MLX LM server (mlx_lm.server)."""

import json
import os
import urllib.error
import urllib.request

class ServerError(Exception):
    """The model server could not be reached or returned an unusable response."""


def base_url() -> str:
    """The model server's base URL, e.g. https://my-server.my-tailnet.ts.net:8443."""
    url = os.environ.get("MLX_WORKER_URL", "").strip().rstrip("/")
    if not url:
        raise ServerError("MLX_WORKER_URL is not set; point it at your model server (no trailing /v1)")
    return url


def _request(path: str, body=None, timeout: float = 30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base_url() + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:300]
        raise ServerError(f"model server returned HTTP {error.code}: {detail}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ServerError(f"could not reach the model server at {base_url()}: {error}") from error


def models() -> list:
    """Model IDs the server is serving."""
    return [model["id"] for model in _request("/v1/models", timeout=10)["data"]]


def chat(messages: list, max_tokens: int = 4096, thinking: bool = False, timeout: float = 1800) -> dict:
    """One chat completion. Returns {content, reasoning, finish_reason, usage}."""
    model = os.environ.get("MLX_WORKER_MODEL") or models()[0]
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": thinking},
    }
    if thinking:
        # Qwen's recommended sampling for thinking mode.
        body.update({"temperature": 1.0, "top_p": 0.95, "top_k": 20})
    result = _request("/v1/chat/completions", body, timeout=timeout)
    choice = result["choices"][0]
    message = choice.get("message") or {}
    return {
        "model": model,
        "content": message.get("content") or "",
        "reasoning": message.get("reasoning") or message.get("reasoning_content") or "",
        "finish_reason": choice.get("finish_reason"),
        "usage": result.get("usage") or {},
    }
