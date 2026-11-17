"""Claude Code as the extraction model: the pipeline asks, a Claude session answers.

Every step of the pipeline stays code -- filing, page selection, the markdown rebuild,
the prompts, the guards and repairs, confidence and abstention, the IDR conversion, the
workbook and the evaluation. Only the one thing a model is needed for changes hands:
`provider.complete(system, user, images)`, which for Gemini is an HTTP call, is here a
file exchange with the Claude Code session running the `claude-extract` skill.

    round 1   the pipeline runs; each prompt it would have sent is written to
              output/claude_exchange/<filing>/<key>.request.md (page images beside it)
              and the filing stops with AnswerPending -- no row is written for it
    answer    Claude reads each request (only the pages code selected) and writes
              <key>.answer.json: the JSON the prompt asks for, nothing else
    round 2+  the pipeline runs again; the same prompts produce the same keys, the
              answers are read back, and follow-up prompts (retries for fields left
              null) become new requests -- until a filing needs none and its row lands

The key is a hash of exactly what a model would have been sent, so an answer can never
be paired with another prompt, and a change in the code that changes a prompt asks again
instead of reusing a stale answer.

Memory (memory/extraction/) is added to the request file for the reader, never to the
hashed prompt: improving a note does not throw away answers already given, and the
prompt the pipeline scores stays the one in src/prompts.py.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
EXCHANGE_DIR = ROOT / "output" / "claude_exchange"
MEMORY_DIR = ROOT / "memory" / "extraction"

_CURRENT = {"pdf": None}


class AnswerPending(Exception):
    """A filing cannot finish until Claude answers the requests written for it.

    Not an LLMError: nothing failed, and no fallback provider should be tried. The
    pipeline lets it through so that no partial row is written in place of an answer.
    """

    def __init__(self, pdf: str, keys: list):
        self.pdf = pdf
        self.keys = list(keys)
        super().__init__(f"{len(self.keys)} request(s) waiting for Claude: "
                         f"{exchange_dir()}/{Path(pdf).stem}/")


def exchange_dir() -> Path:
    return Path(os.getenv("CLAUDE_EXCHANGE_DIR", str(EXCHANGE_DIR))).expanduser()


def memory_digest() -> str:
    """A fingerprint of memory/extraction/ as it is now."""
    digest = hashlib.sha256()
    for path in sorted(MEMORY_DIR.rglob("*.md")) if MEMORY_DIR.exists() else []:
        digest.update(str(path.relative_to(MEMORY_DIR)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def memory_enabled() -> bool:
    return os.getenv("CLAUDE_MEMORY", "on").lower() not in ("0", "off", "false", "no")


@contextmanager
def document(pdf_path):
    """Tell the provider which filing the next prompts belong to."""
    previous = _CURRENT["pdf"]
    _CURRENT["pdf"] = str(pdf_path)
    try:
        yield
    finally:
        _CURRENT["pdf"] = previous


def request_key(system: str, user: str, images: Optional[list]) -> str:
    digest = hashlib.sha256()
    for part in (system, "\x00", user):
        digest.update(part.encode("utf-8"))
    for image in images or []:
        digest.update(b"\x00img\x00")
        digest.update(hashlib.sha256(image.encode("ascii")).digest())
    return digest.hexdigest()[:16]


_TICKER = re.compile(r"_([A-Z]{3,5})$")


def _ticker(pdf: Optional[str]) -> str:
    match = _TICKER.search(Path(pdf).stem) if pdf else None
    return match.group(1) if match else ""


_FIELD_NAMES = ("aset", "total_aset_lancar", "kas", "liabilitas", "utang_bank", "ekuitas",
                "laba_bersih", "pendapatan", "kas_dari_aktivitas_operasi", "total_share")


def requested_fields(user: str) -> list:
    """The scored fields a prompt asks for (its "THIS REQUEST ONLY" line, else all)."""
    match = re.search(r"Extract EXACTLY these fields and nothing else: ([^.]+)\.", user)
    if not match:
        return list(_FIELD_NAMES)
    asked = {name.strip() for name in match.group(1).split(",")}
    # A component key (utang_bank_bagian_lancar_components, kas_components) counts for
    # its field; another scored field that merely shares a prefix (kas_dari_...) does not.
    return [f for f in _FIELD_NAMES
            if f in asked or any((a.startswith(f + "_") or a.endswith("_" + f))
                                 and a not in _FIELD_NAMES for a in asked)]


def memory_for(ticker: str, fields: list) -> str:
    """The notes a reader of this request should see: index, issuer page, field pages.

    Retrieval is by code and deliberately narrow -- the general index, this issuer's
    page and the pages of the fields asked for -- so the injected context stays small
    and one wrong note cannot reach every request.
    """
    if not memory_enabled() or not MEMORY_DIR.exists():
        return ""
    parts = []
    candidates = [MEMORY_DIR / "MEMORY.md"]
    if ticker:
        candidates.append(MEMORY_DIR / "issuers" / f"{ticker}.md")
    candidates += [MEMORY_DIR / "fields" / f"{field}.md" for field in fields]
    for path in candidates:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                parts.append(f"<!-- {path.relative_to(ROOT)} -->\n{text}")
    return "\n\n".join(parts)


_READER_BRIEF = """\
# Permintaan ekstraksi {key}

Filing: `{pdf}` · emiten: {ticker} · field: {fields}

Anda menggantikan model ekstraksi pipeline. Jawab HANYA dari halaman di bawah (dipilih
oleh kode). Jangan membuka PDF lain, CSV hasil, workbook, `data/ground_truth/`, atau
`output/evaluation/`. Tulis jawaban sebagai satu objek JSON persis seperti yang diminta
PROMPT ke `{answer}` (tanpa teks lain), lalu periksa dengan:

    python scripts/claude_extract.py check {answer}

Angka ditulis apa adanya seperti tercetak (skala dan mata uang diurus kode). Field yang
tidak didukung halaman ini = null; jangan menebak.
{images}{memory}
---

## SYSTEM

{system}

## PROMPT

{user}
"""


class ClaudeCodeProvider:
    """complete() answered from files a Claude Code session writes. See module docs."""

    supports_tools = False

    def __init__(self):
        self.model = os.getenv("CLAUDE_CODE_MODEL", "session")
        self.input_mode = os.getenv("CLAUDE_INPUT_MODE", "markdown").lower()
        self.pending: dict = {}           # pdf -> [keys], for this provider's lifetime

    @property
    def name(self) -> str:
        return f"claude-code:{self.model}"

    def complete(self, system: str, user: str, images: Optional[list] = None,
                 usage=None) -> str:
        from llm import _record
        started = time.time()
        pdf = _CURRENT["pdf"] or "unknown"
        key = request_key(system, user, images)
        folder = exchange_dir() / Path(pdf).stem
        answer = folder / f"{key}.answer.json"
        if answer.exists():
            text = answer.read_text(encoding="utf-8")
            _record(usage, "claude-code", self.model, None, started, "", "")
            return text
        self._write_request(folder, key, pdf, system, user, images)
        keys = self.pending.setdefault(pdf, [])
        if key not in keys:
            keys.append(key)
        raise AnswerPending(pdf, keys)

    def _write_request(self, folder: Path, key: str, pdf: str, system: str, user: str,
                       images: Optional[list]) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        request = folder / f"{key}.request.md"
        if request.exists():
            return
        image_lines = ""
        for index, image in enumerate(images or [], 1):
            path = folder / f"{key}_img{index}.png"
            path.write_bytes(base64.b64decode(image))
            image_lines += f"\nGambar halaman {index}: `{path}` (baca dengan Read)"
        if image_lines:
            image_lines = "\nHalaman dikirim sebagai GAMBAR:" + image_lines + "\n"
        fields = requested_fields(user)
        memory = memory_for(_ticker(pdf), fields)
        if memory:
            memory = ("\n## Memori (catatan dari evaluasi sebelumnya; petunjuk, bukan "
                      "jawaban -- halaman di bawah tetap yang menentukan)\n\n" + memory + "\n")
        request.write_text(_READER_BRIEF.format(
            key=key, pdf=pdf, ticker=_ticker(pdf) or "?", fields=", ".join(fields),
            answer=folder / f"{key}.answer.json", images=image_lines, memory=memory,
            system=system, user=user), encoding="utf-8")
        meta = {"key": key, "pdf": pdf, "fields": fields, "images": len(images or []),
                "memory": memory_enabled(),
                # The memory this request was answered WITH; dreaming changes it later.
                "memory_digest": memory_digest() if memory_enabled() else None,
                "created": time.strftime("%Y-%m-%d %H:%M:%S")}
        (folder / f"{key}.meta.json").write_text(json.dumps(meta, indent=1))


def raise_if_pending(provider) -> None:
    """Called by extract_from_pdf once every group has been asked."""
    pending = getattr(provider, "pending", None)
    pdf = _CURRENT["pdf"]
    if pending and pdf and pending.get(pdf):
        raise AnswerPending(pdf, pending[pdf])


def pending_requests(ticker: Optional[str] = None) -> list:
    """[{pdf, key, request, answer}] for every request with no answer yet."""
    root = exchange_dir()
    out = []
    if not root.exists():
        return out
    for request in sorted(root.glob("*/*.request.md")):
        if ticker and not request.parent.name.endswith(f"_{ticker.upper()}"):
            continue
        key = request.name.split(".")[0]
        answer = request.with_name(f"{key}.answer.json")
        if not answer.exists():
            meta_path = request.with_name(f"{key}.meta.json")
            meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
            out.append({"filing": request.parent.name, "key": key,
                        "pdf": meta.get("pdf", ""), "fields": meta.get("fields", []),
                        "images": meta.get("images", 0),
                        "request": str(request), "answer": str(answer)})
    return out


def check_answer(path: Path) -> list:
    """Problems with an answer file; [] when the pipeline will accept it."""
    from llm import parse_json
    from schema import FinancialStatementExtraction
    problems = []
    try:
        data = parse_json(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:                     # noqa: BLE001 - reported to the reader
        return [f"not JSON: {exc}"]
    if not isinstance(data, dict):
        return ["the answer must be one JSON object"]
    try:
        from extract import _coerce_numbers
        clean = dict(data)
        clean.pop("evidence", None)
        FinancialStatementExtraction.from_dict(_coerce_numbers(clean))
    except Exception as exc:                     # noqa: BLE001
        problems.append(f"schema: {type(exc).__name__}: {exc}")
    meta = Path(path).with_name(Path(path).name.replace(".answer.json", ".meta.json"))
    if meta.exists():
        fields = json.loads(meta.read_text()).get("fields", [])
        missing = [f for f in fields if f not in data and not any(
            (k.startswith(f + "_") or k.endswith("_" + f)) and k not in _FIELD_NAMES
            for k in data)]
        if missing:
            problems.append("requested key(s) absent (write null if not on the pages): "
                            + ", ".join(missing))
    return problems
