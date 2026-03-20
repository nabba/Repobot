import httpx
import asyncio
import os
import json
import re

API_URL = "https://openrouter.ai/api/v1/chat/completions"

# High-quality free models on OpenRouter (2025-2026 era)
MODELS = [
    "deepseek/deepseek-chat-v3-0324:free",
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-4-maverick:free",
    "qwen/qwen3-235b-a22b:free",
]

_model_idx = 0


def get_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise RuntimeError("Set OPENROUTER_API_KEY environment variable")
    return key


def next_model() -> str:
    """Round-robin across free models to spread load."""
    global _model_idx
    model = MODELS[_model_idx % len(MODELS)]
    _model_idx += 1
    return model


async def complete(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    retries: int = 3,
) -> str:
    """Call OpenRouter chat completion with automatic retry and model fallback."""
    chosen_model = model or next_model()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": chosen_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    headers = {
        "Authorization": f"Bearer {get_api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/repobot",
        "X-Title": "RepoBot Analyzer",
    }

    last_err = None
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(API_URL, json=payload, headers=headers)
                if resp.status_code == 429 or resp.status_code >= 500:
                    # Switch model and retry
                    chosen_model = next_model()
                    payload["model"] = chosen_model
                    await asyncio.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                # Strip <think>...</think> blocks from reasoning models
                content = re.sub(
                    r"<think>[\s\S]*?</think>", "", content, flags=re.DOTALL
                ).strip()
                return content
        except Exception as e:
            last_err = e
            chosen_model = next_model()
            payload["model"] = chosen_model
            await asyncio.sleep(2 ** attempt)

    return f"[LLM Error after {retries} retries: {last_err}]"
