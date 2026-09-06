"""
Provider-agnostic LLM client.

Two providers, one interface, chosen with LLM_PROVIDER in .env:

    gemini  - hosted, accurate, rate-limited
    ollama  - local, unlimited, weaker

Both accept TEXT or IMAGES, and each has its own default (GEMINI_INPUT_MODE,
OLLAMA_INPUT_MODE), because the right choice differs by provider:

  Gemini defaults to IMAGES. A VLM reads a statement's columns and indentation
  directly, which is exactly the context a flattened text layer destroys, and the
  cost of the extra tokens is not borne locally. The committed result was produced
  this way.

  Ollama defaults to TEXT. A local vision model of comparable quality costs far
  more RAM and time than a text model reading the same page as characters, so text
  is what makes a local fallback practical at all.

Images cost roughly 10-20x their text equivalent in tokens, so text remains the
cheaper path wherever layout is not what is being read -- and these filings do
carry a real text layer (~2,000 characters a page), which the confidence layer
reads independently to verify whatever the model saw.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# Loaded here as well as in extract.py, because a provider that only works when some
# other module happened to be imported first is a trap: `from llm import
# GeminiProvider` on its own reported "GEMINI_API_KEY not set" on a machine where the
# key was sitting in .env the whole time.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# Transient capacity failures, worth one more attempt. 429 is handled separately --
# see _rate_limit_wait.
RETRIABLE_STATUS = frozenset({500, 502, 503, 504})

# A 429 is not one thing, and the difference decides whether waiting helps at all.
#
#   requests per MINUTE   a bucket that refills on a clock. Waiting out the window is
#                         exactly the right response, and the only one that works.
#   requests per DAY      a cap that resets at midnight. Sleeping 75 seconds achieves
#                         nothing except a slower failure.
#
# An earlier version of this file refused to retry any 429 at all, reasoning that
# retrying a throttle deepens it. That is true of a daily cap and false of a per-minute
# one, and conflating them made a 65-file batch fail on a limit that would have cleared
# itself in about a minute.
_PER_MINUTE = re.compile(r"per\s*minute|PerMinute|RPM", re.I)
_PER_DAY = re.compile(r"per\s*day|PerDay|daily", re.I)
# Gemini often returns google.rpc.RetryInfo telling you exactly how long to wait.
_RETRY_DELAY = re.compile(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"')


def _rate_limit_wait(body_text: str, default_wait: float):
    """How long to wait out a 429, or None if waiting cannot help.

    The provider's own RetryInfo is preferred when present -- it knows when its bucket
    refills and we do not. A margin is added on top, because sleeping exactly to the
    boundary races the reset and buys a second 429.
    """
    if _PER_DAY.search(body_text) and not _PER_MINUTE.search(body_text):
        return None

    match = _RETRY_DELAY.search(body_text)
    if match:
        return float(match.group(1)) + 5.0
    return default_wait


def _record(usage, provider: str, model: str, reported: Optional[dict], started: float,
            in_key: str, out_key: str) -> None:
    """Log one call's tokens and latency into an accumulator, if one was passed.

    A provider that reports no usage block records the call with `None` tokens and the
    reason, rather than being left out. A missing call would understate the work done;
    a guessed token count would misstate the spend. Saying "this call happened and its
    size is unknown" is the only honest option.
    """
    if usage is None:
        return
    from usage import CallUsage

    latency_ms = int((time.time() - started) * 1000)
    if not reported:
        usage.record(CallUsage(provider, model, None, None, latency_ms,
                               note=f"{provider} reported no token usage for this call"))
        return
    usage.record(CallUsage(
        provider, model,
        input_tokens=reported.get(in_key),
        output_tokens=reported.get(out_key),
        latency_ms=latency_ms,
    ))


class LLMError(RuntimeError):
    """A call failed. May be specific to this page/request."""


class LLMUnavailable(LLMError):
    """The provider itself is unusable: rate limited, bad key, unknown model, down.

    Distinct from LLMError because retrying the next page cannot help -- and on a
    rate limit, retrying actively makes it worse. Callers abandon the provider and
    move to the fallback instead of working through the remaining pages.
    """


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
        self.timeout = int(os.getenv("GEMINI_TIMEOUT", os.getenv("LLM_TIMEOUT", "120")))
        # "image" sends rendered pages to the VLM; "text" sends the text layer.
        self.input_mode = os.getenv("GEMINI_INPUT_MODE", "image").lower()
        # One retry by default: enough to ride out a capacity spike, few enough that a
        # genuinely down provider is discovered quickly rather than after a long stall.
        self.max_retries = int(os.getenv("LLM_MAX_RETRIES", "1"))
        self.retry_backoff = float(os.getenv("LLM_RETRY_BACKOFF_S", "2"))
        # Slightly over a minute: a per-minute bucket refills on the clock, and waiting
        # to the exact boundary races the reset. Set to 0 to fail fast instead.
        self.rate_limit_wait = float(os.getenv("LLM_RATE_LIMIT_WAIT_S", "75"))
        self.rate_limit_retries = int(os.getenv("LLM_RATE_LIMIT_RETRIES", "1"))
        if not self.api_key:
            raise LLMUnavailable("GEMINI_API_KEY not set")

    @property
    def name(self) -> str:
        return f"gemini:{self.model}"

    def list_models(self) -> list:
        """Model ids on this key that support generateContent."""
        try:
            r = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": self.api_key, "pageSize": 200},
                timeout=30,
            )
            if r.status_code != 200:
                return []
            return sorted(
                m["name"].removeprefix("models/")
                for m in r.json().get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
            )
        except Exception:
            return []

    def complete(self, system: str, user: str, images: Optional[list] = None,
                 usage=None) -> str:
        parts = [{"text": f"{system}\n\n{user}"}]
        for image_b64 in images or []:
            parts.append({"inline_data": {"mime_type": "image/png", "data": image_b64}})

        started = time.time()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }

        # One bounded retry, for CAPACITY errors only.
        #
        # This exists because of an observed failure, not a hypothetical one: during a
        # containerised evaluation run Gemini answered one call with
        #   503 "This model is currently experiencing high demand. Spikes in demand are
        #        usually temporary. Please try again later."
        # and the filing lost `kas_dari_aktivitas_operasi` -- a field the model could
        # read perfectly well, on a page it had already been sent. The three documents
        # after it succeeded immediately, which is what "temporary" looked like in
        # practice.
        #
        # 429 is deliberately NOT retried. A 503 says the service is briefly oversubscribed
        # and invites a retry in its own message; a 429 says WE are over our allowance, and
        # retrying spends another unit of the thing we have just run out of. They read
        # alike in a status-code table and behave nothing alike.
        waited_out = 0
        for attempt in range(self.max_retries + 1):
            response = requests.post(url, params={"key": self.api_key}, json=body,
                                     timeout=self.timeout)

            if response.status_code == 429 and waited_out < self.rate_limit_retries \
                    and self.rate_limit_wait > 0:
                wait = _rate_limit_wait(response.text, self.rate_limit_wait)
                if wait is None:
                    break          # a daily cap; waiting a minute changes nothing
                waited_out += 1
                print(f"    ⏳ rate limited (429); the per-minute window resets on a "
                      f"clock, waiting {wait:.0f}s")
                time.sleep(wait)
                continue           # this attempt did not consume a capacity retry

            if response.status_code not in RETRIABLE_STATUS or attempt == self.max_retries:
                break
            delay = self.retry_backoff * (2 ** attempt)
            print(f"    ⏳ {response.status_code} from Gemini (capacity); retrying once "
                  f"in {delay:.0f}s")
            time.sleep(delay)

        if response.status_code == 429:
            raise LLMUnavailable(
                "Gemini rate limit (429) and waiting did not clear it - "
                "either a daily quota, or more than LLM_RATE_LIMIT_RETRIES windows")
        if response.status_code == 404:
            # Guessing model names wastes a round trip each time; ask the API instead.
            available = self.list_models()
            hint = ""
            if available:
                lite = [m for m in available if "lite" in m]
                hint = ("\n  available (lite): " + ", ".join(lite) if lite else "") + \
                       "\n  all: " + ", ".join(available)
            raise LLMUnavailable(f"Model {self.model!r} not found on this key."
                           f" Set GEMINI_MODEL in .env to one of these.{hint}")
        if response.status_code != 200:
            raise LLMError(f"Gemini HTTP {response.status_code}: {response.text[:200]}")

        data = response.json()
        if not data.get("candidates"):
            raise LLMError(f"Gemini returned no candidates: {str(data)[:200]}")

        # Token counts come from the API's own accounting, never from our estimate.
        # Image parts are billed as tokens too, and only Gemini knows how many.
        _record(usage, "gemini", self.model, data.get("usageMetadata"), started,
                in_key="promptTokenCount", out_key="candidatesTokenCount")
        return data["candidates"][0]["content"]["parts"][0]["text"]


class OllamaProvider:
    """Local model served by Ollama. Text only."""

    def __init__(self):
        self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        self.model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
        # Deliberately NOT LLM_TIMEOUT: a hosted API that has not answered in two
        # minutes has failed, but a local model on a laptop may still be working --
        # the first call also pays to load several GB of weights into RAM.
        self.timeout = int(os.getenv("OLLAMA_TIMEOUT", "900"))
        # Reasoning models emit a long <think> block before the answer, which for a
        # fixed-shape JSON extraction is pure latency. Off unless asked for.
        self.think = os.getenv("OLLAMA_THINK", "false").lower() in ("1", "true", "yes")
        self.keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "15m")
        self.num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
        # Text by default: a local vision model of comparable quality costs far more
        # RAM and time than a text model reading the same page as characters.
        self.input_mode = os.getenv("OLLAMA_INPUT_MODE", "text").lower()
        # Checked once, lazily: a text model silently ignoring images is worse than
        # a loud failure, because the answer still looks well-formed.
        self._vision_checked = self.supports_vision() if self.input_mode == "image" else None

    @property
    def name(self) -> str:
        return f"ollama:{self.model}"

    @staticmethod
    def _report_timings(body: dict) -> None:
        """Print Ollama's own breakdown so slowness can be attributed, not guessed.

        load     = reading weights into memory (only on a cold model)
        prompt   = processing the input; scales with how much text we send
        generate = producing the answer; scales with how much JSON comes back

        A low tokens/s on generate points at the model being too big for available
        RAM (spilling to swap); a large prompt time points at us sending too much.
        """
        ns = 1e9
        load = body.get("load_duration", 0) / ns
        p_n, p_t = body.get("prompt_eval_count", 0), body.get("prompt_eval_duration", 0) / ns
        g_n, g_t = body.get("eval_count", 0), body.get("eval_duration", 0) / ns
        total = body.get("total_duration", 0) / ns
        if not total:
            return
        print(f"      load {load:6.1f}s | prompt {p_t:6.1f}s ({p_n:,} tok"
              f"{f', {p_n/p_t:.0f} tok/s' if p_t else ''})"
              f" | generate {g_t:6.1f}s ({g_n:,} tok"
              f"{f', {g_n/g_t:.1f} tok/s' if g_t else ''})"
              f" | total {total:6.1f}s")

    def supports_vision(self) -> Optional[bool]:
        """Ask Ollama whether this model can see. None if it cannot be determined."""
        try:
            r = requests.post(f"{self.host}/api/show", json={"model": self.model}, timeout=15)
            if r.status_code != 200:
                return None
            info = r.json()
            caps = info.get("capabilities") or []
            if caps:
                return "vision" in caps
            families = (info.get("details") or {}).get("families") or []
            return any(f in ("clip", "mllama", "qwen3vl", "gemma3") for f in families)
        except Exception:
            return None

    def complete(self, system: str, user: str, images: Optional[list] = None,
                 usage=None) -> str:
        if images and self._vision_checked is False:
            raise LLMUnavailable(
                f"{self.model!r} is a text-only model but OLLAMA_INPUT_MODE=image. "
                f"It would ignore the images and answer from the prompt alone -- which "
                f"looks like a wrong answer, not an error. "
                f"Pull a vision model (e.g. `ollama pull qwen3-vl:8b`) or set "
                f"OLLAMA_INPUT_MODE=text."
            )

        # Size the context to the actual input instead of always reserving the max.
        # Ollama allocates a KV cache for num_ctx up front, so an oversized value
        # costs RAM and speed on every call even when the prompt is short.
        needed = (len(system) + len(user)) // 3 + 1024      # ~3 chars/token, + room for output
        num_ctx = min(self.num_ctx, max(4096, 1 << (needed - 1).bit_length()))

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",          # Ollama constrains output to valid JSON
            "keep_alive": self.keep_alive,
            "think": self.think,
            "options": {"temperature": 0, "num_ctx": num_ctx},
        }
        if images:
            # Ollama takes several images on one message, so a whole statement can
            # be shown at once instead of a page at a time.
            payload["messages"][1]["images"] = list(images)

        def _post(body):
            try:
                return requests.post(f"{self.host}/api/chat", json=body, timeout=self.timeout)
            except requests.exceptions.ConnectionError:
                raise LLMUnavailable(f"Cannot reach Ollama at {self.host} - is `ollama serve` running?")
            except requests.exceptions.ReadTimeout:
                raise LLMError(
                    f"Ollama did not answer within {self.timeout}s for {self.model!r}. "
                    "Raise OLLAMA_TIMEOUT, or use a smaller / non-reasoning model."
                )

        started = time.time()
        response = _post(payload)
        if response.status_code == 400 and "think" in response.text.lower():
            # Older Ollama builds reject the field; the model simply keeps thinking.
            payload.pop("think", None)
            response = _post(payload)

        if response.status_code == 404:
            raise LLMUnavailable(f"Model {self.model!r} not pulled. Run: ollama pull {self.model}")
        if response.status_code != 200:
            raise LLMError(f"Ollama HTTP {response.status_code}: {response.text[:200]}")

        body = response.json()
        self._report_timings(body)
        # Ollama names its counts differently but reports the same two quantities.
        _record(usage, "ollama", self.model, body, started,
                in_key="prompt_eval_count", out_key="eval_count")
        content = body["message"]["content"]
        # A thinking model that ignored think=false leaves its reasoning inline.
        return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()


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
