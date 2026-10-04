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
from dataclasses import dataclass, field
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

    A 429 is "Too Many Requests", and on Gemini it covers three different limits:
    requests per minute (RPM), input tokens per minute (TPM) and requests per day (RPD).
    The body names which one was hit in its quotaId ("...PerMinute..." / "...PerDay...").

    Any per-day violation fails fast, even when a per-minute one is listed beside it:
    once the day's allowance is gone, a minute's sleep ends in the same 429.

    Otherwise the wait is the configured cooldown, lengthened -- never shortened -- by
    the provider's own RetryInfo plus a margin. Gemini sometimes says "retry in 20s";
    trusting that alone buys a second 429 when the window has not actually reset, and
    a cooldown the user chose should not be undercut by a hint.
    """
    if _PER_DAY.search(body_text):
        return None

    match = _RETRY_DELAY.search(body_text)
    if match:
        return max(float(match.group(1)) + 5.0, default_wait)
    return default_wait


# Which models are resting, and until when (time.monotonic()). Shared by every
# provider object in the process, because the chain is rebuilt for each document: a
# model that was throttled on document 3 must still be skipped on document 4, or every
# document pays one wasted call rediscovering the same limit.
_COOLDOWN_UNTIL: dict = {}
# A per-day quota does not come back within a batch. Resting the model for the rest of
# the run is the honest reading; a fresh process starts clean.
DAILY_COOLDOWN_S = 24 * 3600


def _cool(model: str, seconds: float) -> None:
    """Rest a model for `seconds`, never shortening a rest it is already on."""
    until = time.monotonic() + max(seconds, 0)
    _COOLDOWN_UNTIL[model] = max(_COOLDOWN_UNTIL.get(model, 0.0), until)


def cooling_down(model: str) -> bool:
    """True while a model is inside a rest it earned on an earlier call."""
    return _COOLDOWN_UNTIL.get(model, 0.0) > time.monotonic()


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


# --- tool calling ----------------------------------------------------------------
#
# A second conversation shape, added beside complete() rather than inside it. complete()
# is one request and one JSON string, which is all the pipeline ever needs; an agent
# needs a transcript it can append to, and a model turn that may be a tool call rather
# than an answer. Keeping them apart means the pipeline's contract -- relied on by
# extract.py twice and by the API's stub provider -- cannot be broken by work on the
# loop.

@dataclass
class ToolCall:
    """One tool the model asked for, with the arguments it supplied."""
    name: str
    args: dict = field(default_factory=dict)


@dataclass
class AssistantTurn:
    """What the model did on one turn: tool calls, prose, or neither."""
    tool_calls: list = field(default_factory=list)
    text: Optional[str] = None
    # The provider-native content block, appended back to the transcript verbatim. A
    # part shape we did not anticipate -- a second functionCall, a thought part --
    # round-trips instead of being silently dropped on re-serialisation.
    raw: dict = field(default_factory=dict)
    finish_reason: Optional[str] = None


class ToolsUnsupported(LLMUnavailable):
    """This provider cannot drive a tool loop. Skip it, do not fail the document."""


class GeminiProvider:
    """Google Gemini via REST (no SDK dependency)."""

    def __init__(self, model: Optional[str] = None):
        self.api_key = os.getenv("GEMINI_API_KEY")
        # A model can be named explicitly so the same class serves every Gemini model in
        # the fallback chain -- see get_provider_chain.
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.timeout = int(os.getenv("GEMINI_TIMEOUT", os.getenv("LLM_TIMEOUT", "120")))
        # "markdown" rebuilds each page as a table from its word geometry and sends that;
        # "image" sends rendered pages to the VLM; "text" sends the flattened text layer.
        # Markdown is the default because it is the only one of the three that states
        # which column is the current period -- see src/pagemd.py. A filing whose text
        # layer is unreadable falls back to images per document, in extract.py.
        self.input_mode = os.getenv("GEMINI_INPUT_MODE", "markdown").lower()
        # One retry by default: enough to ride out a capacity spike, few enough that a
        # genuinely down provider is discovered quickly rather than after a long stall.
        self.max_retries = int(os.getenv("LLM_MAX_RETRIES", "1"))
        self.retry_backoff = float(os.getenv("LLM_RETRY_BACKOFF_S", "2"))
        # Slightly over a minute: a per-minute bucket refills on the clock, and waiting
        # to the exact boundary races the reset. Set to 0 to fail fast instead.
        self.rate_limit_wait = float(os.getenv("LLM_RATE_LIMIT_WAIT_S", "70"))
        # The configured rest, kept separately: get_provider_chain zeroes
        # rate_limit_wait on models that hand over, but the ledger still needs to know
        # how long such a model should be skipped.
        self.cooldown_s = self.rate_limit_wait
        self.rate_limit_retries = int(os.getenv("LLM_RATE_LIMIT_RETRIES", "1"))
        # Set by get_provider_chain when another Gemini model follows this one: a 429
        # then hands the document over instead of cooling down.
        self.hands_over = False
        # Gemini's REST API supports functionDeclarations on every current model.
        self.supports_tools = True
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
        """One request, one JSON string back. The contract three call sites rely on."""
        parts = [{"text": f"{system}\n\n{user}"}]
        for image_b64 in images or []:
            parts.append({"inline_data": {"mime_type": "image/png", "data": image_b64}})

        data = self._request({
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }, usage=usage)
        if not data.get("candidates"):
            raise LLMError(f"Gemini returned no candidates: {str(data)[:200]}")
        return data["candidates"][0]["content"]["parts"][0]["text"]

    def complete_with_tools(self, system: str, contents: list, tools: list,
                            usage=None) -> AssistantTurn:
        """One turn of a tool-calling conversation.

        `contents` is the running transcript in Gemini's own wire shape and is owned by
        the caller -- appending the model's turn and the tool results is the loop's job,
        because only the loop knows whether a tool was allowed to run.

        Three differences from complete(), each of which breaks the request if missed:

          * no responseMimeType. "application/json" and tools are mutually exclusive on
            generateContent, and sending both returns a 400 that reads like a schema
            error rather than a conflict;
          * every contents entry carries a role. One turn without one is legal; a
            transcript without them is not;
          * the system prompt goes in systemInstruction. Concatenated into turn one it
            becomes a user message the model can argue with three turns later.
        """
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "tools": [{"functionDeclarations": tools}],
            "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
            "generationConfig": {"temperature": 0},
        }
        data = self._request(body, usage=usage)
        if not data.get("candidates"):
            raise LLMError(f"Gemini returned no candidates: {str(data)[:200]}")

        candidate = data["candidates"][0]
        content = candidate.get("content") or {}
        calls, texts = [], []
        # Every part, not parts[0]. The old reader indexed straight into ["text"], which
        # is a KeyError the moment a model answers with a functionCall -- and parts is
        # absent entirely when finishReason is MAX_TOKENS or SAFETY, which the loop
        # handles as a turn that said nothing rather than as a crash.
        for part in content.get("parts") or []:
            if "functionCall" in part:
                call = part["functionCall"] or {}
                calls.append(ToolCall(name=call.get("name") or "",
                                      args=call.get("args") or {}))
            elif "text" in part:
                texts.append(part["text"])
        return AssistantTurn(
            tool_calls=calls,
            text="\n".join(texts) or None,
            raw={"role": "model", "parts": content.get("parts") or []},
            finish_reason=candidate.get("finishReason"))

    def _request(self, body: dict, usage=None) -> dict:
        """POST one generateContent body under the retry, 429 and hand-over policy.

        Extracted from complete() unchanged, because it is the only reason a
        three-hour corpus pass survives a throttled afternoon -- and a second entry
        point (the tool-calling loop below) that reimplemented any of it would drift
        from this one silently. Everything here is transport: what the body says and
        what the parts mean belong to the caller.
        """
        started = time.time()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

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
        # A 429 is handled separately, above the capacity retry: a per-minute limit is
        # cooled down and retried (LLM_RATE_LIMIT_WAIT_S), a per-day limit fails at
        # once. The wait does not consume the capacity retry -- they are different
        # failures and one should not use up the other's allowance.
        waited_out = 0
        # A while loop, not `for attempt in range(...)`: waiting out a per-minute 429 must
        # not use up a capacity retry, and a `continue` inside a for loop does exactly
        # that. With two cooldowns and three retries configured, the for loop spent two
        # of the four passes on cooldowns and gave up on a 503 it had been told to retry.
        attempt = 0
        while True:
            try:
                response = requests.post(url, params={"key": self.api_key}, json=body,
                                         timeout=self.timeout)
            except requests.RequestException as exc:
                # A read timeout or dropped connection is the same condition as a 503 --
                # the service did not answer -- and used to escape this method as a raw
                # requests exception. The image path catches exceptions per statement
                # group and moves on, so an overloaded model spent the full timeout on
                # every group of the document in turn, lost each group's fields, and
                # never handed the document to the next model. Observed on
                # gemini-3.7-flash: "Read timed out. (read timeout=120)" on the balance
                # sheet, then again on the income statement.
                if attempt < self.max_retries:
                    delay = self.retry_backoff * (2 ** attempt)
                    print(f"    \u23f3 {type(exc).__name__} from Gemini; retry {attempt + 1}/{self.max_retries} in "
                          f"{delay:.0f}s")
                    time.sleep(delay)
                    attempt += 1
                    continue
                if self.hands_over:
                    _cool(self.model, self.cooldown_s)
                    raise LLMUnavailable(
                        f"Gemini did not answer on {self.model} ({type(exc).__name__}) "
                        f"after {self.max_retries} retry; handing over to the next model"
                    ) from exc
                raise LLMError(f"Gemini did not answer on {self.model}: "
                               f"{type(exc).__name__}: {exc}") from exc

            if response.status_code == 429 and waited_out < self.rate_limit_retries \
                    and self.rate_limit_wait > 0:
                wait = _rate_limit_wait(response.text, self.rate_limit_wait)
                if wait is None:
                    break          # a daily cap; waiting a minute changes nothing
                waited_out += 1
                print(f"    ⏳ 429 per-minute limit (RPM/TPM); cooling down {wait:.0f}s "
                      f"for the window to reset")
                time.sleep(wait)
                continue           # this attempt did not consume a capacity retry

            if response.status_code not in RETRIABLE_STATUS or attempt == self.max_retries:
                break
            delay = self.retry_backoff * (2 ** attempt)
            print(f"    ⏳ {response.status_code} from Gemini (capacity); retry {attempt + 1}/{self.max_retries} "
                  f"in {delay:.0f}s")
            time.sleep(delay)
            attempt += 1

        if response.status_code == 429:
            # Say which of the three situations this is. They need different responses
            # from whoever reads the log -- wait until tomorrow, do nothing, or raise the
            # retry count -- and one catch-all sentence left them to guess.
            if _PER_DAY.search(response.text):
                reason = "daily quota (RPD) used up; waiting cannot clear it"
                _cool(self.model, DAILY_COOLDOWN_S)
            elif self.hands_over:
                reason = "per-minute limit (RPM/TPM); handing over to the next model"
                _cool(self.model, self.cooldown_s)
            elif self.rate_limit_wait <= 0:
                reason = "per-minute limit (RPM/TPM); cooldown disabled (LLM_RATE_LIMIT_WAIT_S=0)"
            else:
                reason = (f"per-minute limit (RPM/TPM) still hit after "
                          f"{self.rate_limit_retries} cooldown(s)")
            raise LLMUnavailable(f"Gemini rate limit (429) on {self.model}: {reason}")
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
        if response.status_code in RETRIABLE_STATUS and self.hands_over:
            # "High demand" that outlived its retry. Raised as LLMUnavailable so the
            # document moves to the next model. As a plain LLMError it was caught per
            # statement group and skipped: the model stayed in charge of the document
            # and one statement's fields went missing without anyone being told why.
            # Only when another model follows -- for the last one, losing a group is
            # still better than losing the document.
            _cool(self.model, self.cooldown_s)
            raise LLMUnavailable(
                f"Gemini {response.status_code} (capacity) on {self.model} after "
                f"{self.max_retries} retry; handing over to the next model")
        if response.status_code != 200:
            raise LLMError(f"Gemini HTTP {response.status_code}: {response.text[:200]}")

        data = response.json()

        # Token counts come from the API's own accounting, never from our estimate.
        # Image parts are billed as tokens too, and only Gemini knows how many.
        _record(usage, "gemini", self.model, data.get("usageMetadata"), started,
                in_key="promptTokenCount", out_key="candidatesTokenCount")
        return data


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
        # Ollama's /api/chat does carry tools, but a 7B local model driving a
        # fourteen-turn loop with eight tool schemas produces far more malformed calls
        # than useful ones -- and a silent stream of them costs more than it buys. Off
        # by default for the same reason a text-only model refuses images below: a
        # refusal that names the reason beats an expensive stream of garbage.
        self._tools_enabled = os.getenv("AGENT_ALLOW_OLLAMA", "false").lower() in (
            "1", "true", "yes")
        # Checked once, lazily: a text model silently ignoring images is worse than
        # a loud failure, because the answer still looks well-formed.
        self._vision_checked = self.supports_vision() if self.input_mode == "image" else None

    @property
    def name(self) -> str:
        return f"ollama:{self.model}"

    @property
    def supports_tools(self) -> bool:
        return self._tools_enabled

    def complete_with_tools(self, system: str, contents: list, tools: list,
                            usage=None) -> "AssistantTurn":
        """Refuse clearly rather than stream malformed tool calls.

        The chain skips a provider that says it cannot do this, so
        LLM_FALLBACK_PROVIDER=ollama degrades at step zero with a reason instead of
        exploding at step five.
        """
        raise ToolsUnsupported(
            f"{self.name} is not enabled for the agent loop: a local 7B model driving a "
            f"tool loop produces malformed calls far more often than useful ones. "
            f"Set AGENT_ALLOW_OLLAMA=true to measure that claim rather than take it.")

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


def get_provider_chain() -> list:
    """Every provider to try for one document, in order.

        GEMINI_MODEL  ->  each of GEMINI_FALLBACK_MODELS  ->  LLM_FALLBACK_PROVIDER

    Gemini counts its rate limits PER MODEL, so a second model has its own RPM, TPM and
    RPD allowance. When the first model is throttled, that makes another Gemini model a
    better next step than a local one: same prompt, same image input, seconds instead of
    minutes per document.

    Every Gemini model except the last is given no cooldown. Sleeping 70 seconds on a 429
    while a model with spare quota is one call away would be waiting for nothing. The
    last Gemini model keeps its cooldown, because the only thing after it is a local
    model that is slower still.

    Duplicates are dropped, so listing the primary model among the fallbacks is harmless.
    A document is always extracted by ONE provider from start to finish: if a model fails
    partway through, the document restarts on the next one rather than mixing answers,
    and the result records which provider it came from.
    """
    chain = [get_provider()]
    if chain[0].name.startswith("gemini:"):
        for model in os.getenv("GEMINI_FALLBACK_MODELS", "").split(","):
            model = model.strip()
            if model and all(p.name != f"gemini:{model}" for p in chain):
                chain.append(GeminiProvider(model=model))

    fallback_name = os.getenv("LLM_FALLBACK_PROVIDER", "").strip().lower()
    if fallback_name:
        fallback = get_provider(fallback_name)
        if all(p.name != fallback.name for p in chain):
            chain.append(fallback)

    gemini = [p for p in chain if p.name.startswith("gemini:")]
    others = [p for p in chain if not p.name.startswith("gemini:")]
    if chain[0].name.startswith("gemini:"):
        # Rotation. A model still resting from an earlier document moves to the back of
        # the Gemini queue, soonest-back-first, instead of being asked again and
        # answering 429 again. It is not dropped: if every model is resting, the one
        # closest to returning is still tried last, with its cooldown, before anything
        # local.
        ready = [p for p in gemini if not cooling_down(p.model)]
        resting = sorted((p for p in gemini if cooling_down(p.model)),
                         key=lambda p: _COOLDOWN_UNTIL[p.model])
        gemini = ready + resting
        chain = gemini + others
    for provider in gemini[:-1]:
        provider.rate_limit_wait = 0
        provider.hands_over = True

    # Patience. Handing over at once is right for a model that is merely one of several
    # equals, but not for the cheap, fast models at the front of the queue: the next ones
    # cost three times as much and answer several times slower. A model named in
    # GEMINI_PATIENT_MODELS therefore waits out a per-minute 429 (cooling down up to
    # GEMINI_PATIENT_RATE_LIMIT_RETRIES times) and retries a 503, 500 or timeout up to
    # GEMINI_PATIENT_RETRIES times with a longer backoff, before handing over. A daily
    # quota still hands over immediately -- no amount of waiting brings it back.
    patient = {m.strip() for m in os.getenv("GEMINI_PATIENT_MODELS", "").split(",") if m.strip()}
    for provider in gemini:
        if provider.model in patient:
            provider.rate_limit_wait = provider.cooldown_s
            provider.rate_limit_retries = int(os.getenv("GEMINI_PATIENT_RATE_LIMIT_RETRIES", "2"))
            provider.max_retries = int(os.getenv("GEMINI_PATIENT_RETRIES", "3"))
            provider.retry_backoff = float(os.getenv("GEMINI_PATIENT_BACKOFF_S", "5"))
    return chain


def get_provider_with_fallback():
    """(first, second_or_None) from the chain, for callers that only need the primary.

    Extraction itself walks the whole chain via get_provider_chain.
    """
    chain = get_provider_chain()
    return chain[0], (chain[1] if len(chain) > 1 else None)
