"""
What a document cost to extract, in tokens, money and seconds.

Latency was already visible; cost was not, and the two answer different questions.
Latency tells you whether a user will wait; cost tells you whether the system can be
pointed at ten thousand filings. Both are needed before anyone can decide between the
hosted and the local provider, which is the decision this module exists to inform.

Three deliberate choices:

**Tokens are recorded, never estimated.** Both providers report their own counts --
Gemini in `usageMetadata`, Ollama in `prompt_eval_count`/`eval_count`. When a provider
reports nothing, the count is `None` and the reason is stated. A plausible guess about
spend is worse than an admission of ignorance, for the same reason a guessed exchange
rate is worse than a refusal.

**Prices live in config, not in code.** They change, they differ per account, and they
are not a property of the extraction logic. `config/pricing.json` holds them; a model
with no configured rate yields a null cost carrying the reason, so an unpriced run
still reports its tokens.

**Local models are shown, not hidden.** An Ollama run costs nothing in cash but the
same tokens in work. Printing zero beside the token count is what makes a cloud/local
comparison honest -- omitting the row would read as "no data" rather than "free".
"""

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRICING = ROOT / "config" / "pricing.json"


@dataclass
class CallUsage:
    """One LLM call."""
    provider: str
    model: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: int = 0
    note: Optional[str] = None      # why tokens are missing, when they are


class Usage:
    """Accumulates the calls made while extracting ONE document.

    Passed into `provider.complete()` rather than kept on the provider, because a batch
    runs several documents through the same provider object at once and per-provider
    counters would interleave into a number belonging to nobody.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.calls: list = []
        self.stages: dict = {}          # stage name -> milliseconds

    # -- recording ---------------------------------------------------------------

    def record(self, call: CallUsage) -> None:
        with self._lock:
            self.calls.append(call)

    def stage(self, name: str):
        """Context manager timing one stage: `with usage.stage("select"): ...`"""
        return _Stage(self, name)

    def _add_stage(self, name: str, ms: int) -> None:
        with self._lock:
            self.stages[name] = self.stages.get(name, 0) + ms

    # -- reading -----------------------------------------------------------------

    @property
    def llm_calls(self) -> int:
        return len(self.calls)

    def _sum(self, attribute: str) -> Optional[int]:
        """Total, or None if no call reported it.

        Partial reporting is summed over what is known and flagged in `notes`, rather
        than discarded -- some information about spend beats none, as long as it says
        so.
        """
        values = [getattr(c, attribute) for c in self.calls]
        known = [v for v in values if v is not None]
        return sum(known) if known else None

    @property
    def input_tokens(self) -> Optional[int]:
        return self._sum("input_tokens")

    @property
    def output_tokens(self) -> Optional[int]:
        return self._sum("output_tokens")

    @property
    def notes(self) -> list:
        return sorted({c.note for c in self.calls if c.note})

    def cost(self, pricing: Optional[dict] = None) -> dict:
        """{amount, currency, per_model:[...]} or {amount: None, reason: ...}."""
        pricing = load_pricing() if pricing is None else pricing
        rates = pricing.get("models", {})
        currency = pricing.get("currency", "USD")

        total = 0.0
        per_model = []
        unpriced = []
        for model in sorted({c.model for c in self.calls}):
            calls = [c for c in self.calls if c.model == model]
            rate = rates.get(model)
            tokens_in = sum(c.input_tokens or 0 for c in calls)
            tokens_out = sum(c.output_tokens or 0 for c in calls)
            if rate is None:
                unpriced.append(model)
                per_model.append({"model": model, "input_tokens": tokens_in,
                                  "output_tokens": tokens_out, "amount": None})
                continue
            amount = (tokens_in / 1e6) * float(rate.get("input_per_1m", 0) or 0) \
                   + (tokens_out / 1e6) * float(rate.get("output_per_1m", 0) or 0)
            total += amount
            per_model.append({"model": model, "input_tokens": tokens_in,
                              "output_tokens": tokens_out, "amount": round(amount, 6)})

        if unpriced:
            return {
                "amount": None,
                "currency": currency,
                "per_model": per_model,
                "reason": f"no price configured for {', '.join(unpriced)} - "
                          f"add it to {os.getenv('PRICING_CONFIG', str(DEFAULT_PRICING))}",
            }
        if not self.calls:
            return {"amount": None, "currency": currency, "per_model": [],
                    "reason": "no LLM calls were made (cached result?)"}
        return {"amount": round(total, 6), "currency": currency, "per_model": per_model}

    def to_dict(self, pricing: Optional[dict] = None) -> dict:
        return {
            "llm_calls": self.llm_calls,
            "tokens": {"input": self.input_tokens, "output": self.output_tokens},
            "latency_ms": dict(self.stages),
            "cost": self.cost(pricing),
            "notes": self.notes,
        }

    def merge(self, other: "Usage") -> None:
        """Fold another document's usage into this one, for batch totals."""
        with self._lock:
            self.calls.extend(other.calls)
            for name, ms in other.stages.items():
                self.stages[name] = self.stages.get(name, 0) + ms


class _Stage:
    def __init__(self, usage: Usage, name: str):
        self.usage, self.name = usage, name

    def __enter__(self):
        self.started = time.time()
        return self

    def __exit__(self, *exc):
        self.usage._add_stage(self.name, int((time.time() - self.started) * 1000))
        return False


def load_pricing(path: Optional[str] = None) -> dict:
    """Read the price table. A missing or malformed file is not fatal.

    Cost reporting is an accessory to extraction, not a precondition for it: a broken
    price file must not stop a filing from being read. It degrades to "no price
    configured", which is the same path an unpriced model takes.
    """
    path = Path(path or os.getenv("PRICING_CONFIG") or DEFAULT_PRICING)
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {"currency": "USD", "models": {}}
    if not isinstance(data, dict):
        return {"currency": "USD", "models": {}}
    data.setdefault("currency", "USD")
    data.setdefault("models", {})
    return data
