"""
Provider-agnostic LLM client.

Two providers, one interface, chosen with LLM_PROVIDER in .env:

    gemini  - hosted, accurate, rate-limited
    ollama  - local, unlimited, weaker

Both take TEXT, not images. These filings carry a real text layer (~2,000
characters a page), so rendering a page to PNG and asking a model to read the
pixels throws away text that is already perfect and pays for the privilege --
an image page costs roughly 10-20x its text equivalent in tokens. Text input is
also what makes a local fallback practical: a text model needs a fraction of the
resources of a vision model of the same quality.

The image path still exists in extract.py for filings that are scans and have no
text layer to read.
"""

import json
import os
import re
from typing import Optional

import requests


class LLMError(RuntimeError):
    pass


def _strip_fences(text: str) -> str:
    """Remove markdown code fences the model may wrap JSON in."""
    text = re.sub(r"```(?:json)?\s*", "", text)
    return text.replace("```", "").strip()


def parse_json(text: str) -> dict:
    """Parse a model response as JSON, tolerating fences and surrounding prose."""
    cleaned = _strip_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fall back to the outermost {...} block.
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise LLMError(f"No JSON object in response: {text[:200]}")
        return json.loads(match.group(0))


class GeminiProvider:
    """Google Gemini via REST (no SDK dependency)."""

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.timeout = int(os.getenv("LLM_TIMEOUT", "120"))
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY not set")

    @property
    def name(self) -> str:
        return f"gemini:{self.model}"

    def complete(self, system: str, user: str, image_b64: Optional[str] = None) -> str:
        parts = [{"text": f"{system}\n\n{user}"}]
        if image_b64:
            parts.append({"inline_data": {"mime_type": "image/png", "data": image_b64}})

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        response = requests.post(
            url,
            params={"key": self.api_key},
            json={
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                },
            },
            timeout=self.timeout,
        )
        if response.status_code == 429:
            raise LLMError("Gemini rate limit (429) - set LLM_PROVIDER=ollama to fall back")
        if response.status_code != 200:
            raise LLMError(f"Gemini HTTP {response.status_code}: {response.text[:200]}")

        data = response.json()
        if not data.get("candidates"):
            raise LLMError(f"Gemini returned no candidates: {str(data)[:200]}")
        return data["candidates"][0]["content"]["parts"][0]["text"]


class OllamaProvider:
    """Local model served by Ollama. Text only."""

    def __init__(self):
        self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        self.model = os.getenv("OLLAMA_MODEL", "qwen3:8b")
        self.timeout = int(os.getenv("LLM_TIMEOUT", "600"))  # local runs are slow

    @property
    def name(self) -> str:
        return f"ollama:{self.model}"

    def complete(self, system: str, user: str, image_b64: Optional[str] = None) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",          # Ollama constrains output to valid JSON
            "options": {"temperature": 0, "num_ctx": 16384},
        }
        if image_b64:
            payload["messages"][1]["images"] = [image_b64]

        try:
            response = requests.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout)
        except requests.exceptions.ConnectionError:
            raise LLMError(f"Cannot reach Ollama at {self.host} - is `ollama serve` running?")

        if response.status_code == 404:
            raise LLMError(f"Model {self.model!r} not pulled. Run: ollama pull {self.model}")
        if response.status_code != 200:
            raise LLMError(f"Ollama HTTP {response.status_code}: {response.text[:200]}")

        return response.json()["message"]["content"]


def get_provider(name: Optional[str] = None):
    """Build the provider named by LLM_PROVIDER (default gemini)."""
    name = (name or os.getenv("LLM_PROVIDER", "gemini")).lower()
    if name == "gemini":
        return GeminiProvider()
    if name == "ollama":
        return OllamaProvider()
    raise LLMError(f"Unknown LLM_PROVIDER {name!r} (expected 'gemini' or 'ollama')")


def get_provider_with_fallback():
    """Primary provider, plus the fallback named by LLM_FALLBACK_PROVIDER (if any).

    Returns (primary, fallback_or_None). The caller decides when to switch, so a
    rate limit costs one wasted call rather than silently changing which model
    produced a number -- the eval scorecard has to be able to say which one it was.
    """
    primary = get_provider()
    fallback_name = os.getenv("LLM_FALLBACK_PROVIDER", "").strip().lower()
    if not fallback_name:
        return primary, None
    fallback = get_provider(fallback_name)
    return primary, (None if fallback.name == primary.name else fallback)
