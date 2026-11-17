"""The Claude Code provider: requests on disk, answers read back, memory kept clean."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import claudecode  # noqa: E402
from claudecode import (AnswerPending, ClaudeCodeProvider, check_answer,  # noqa: E402
                        document, pending_requests, raise_if_pending, request_key,
                        requested_fields)


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def exchange(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_EXCHANGE_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_MEMORY", "off")
    return tmp_path


PROMPT = ("Extract.\n=== THIS REQUEST ONLY ===\nExtract EXACTLY these fields and nothing "
          "else: aset, total_ekuitas, kas_components, period_end_date. Include every key.")


def test_request_written_then_answer_read_back(exchange):
    provider = ClaudeCodeProvider()
    with document("/x/Q4_2025_TRIN.pdf"):
        with pytest.raises(AnswerPending) as pending:
            provider.complete("SYS", PROMPT)
        key = pending.value.keys[0]
        assert key == request_key("SYS", PROMPT, None)
        folder = exchange / "Q4_2025_TRIN"
        assert (folder / f"{key}.request.md").exists()
        assert [p["key"] for p in pending_requests("TRIN")] == [key]
        with pytest.raises(AnswerPending):
            raise_if_pending(provider)

        (folder / f"{key}.answer.json").write_text('{"aset": 5, "total_ekuitas": 2, '
                                                   '"kas_components": null}')
        assert json.loads(provider.complete("SYS", PROMPT))["aset"] == 5
    assert pending_requests("TRIN") == []


def test_images_change_the_key_and_are_saved(exchange):
    import base64
    image = base64.b64encode(b"png-bytes").decode()
    assert request_key("S", "U", [image]) != request_key("S", "U", None)
    provider = ClaudeCodeProvider()
    with document("/x/Q1_2023_ENRG.pdf"), pytest.raises(AnswerPending) as pending:
        provider.complete("S", "U", images=[image])
    saved = exchange / "Q1_2023_ENRG" / f"{pending.value.keys[0]}_img1.png"
    assert saved.read_bytes() == b"png-bytes"


def test_requested_fields_maps_components_not_prefixes():
    assert requested_fields(PROMPT) == ["aset", "kas", "ekuitas"]
    cash_flow = PROMPT.replace("aset, total_ekuitas, kas_components",
                               "kas_dari_aktivitas_operasi")
    assert requested_fields(cash_flow) == ["kas_dari_aktivitas_operasi"]


def test_check_answer_flags_missing_keys_and_bad_json(exchange):
    provider = ClaudeCodeProvider()
    with document("/x/Q4_2025_TRIN.pdf"), pytest.raises(AnswerPending) as pending:
        provider.complete("SYS", PROMPT)
    answer = exchange / "Q4_2025_TRIN" / f"{pending.value.keys[0]}.answer.json"
    answer.write_text("not json")
    assert check_answer(answer)[0].startswith("not JSON")
    answer.write_text('{"aset": 1}')
    assert any("absent" in p for p in check_answer(answer))
    answer.write_text('{"aset": 1, "total_ekuitas": null, "kas_components": null}')
    assert check_answer(answer) == []


def test_memory_lint_rejects_label_values(tmp_path, monkeypatch):
    ce = _script("claude_extract")
    memory = tmp_path / "memory"
    (memory / "issuers").mkdir(parents=True)
    (memory / "MEMORY.md").write_text("# index\n")
    page = memory / "issuers" / "TRIN.md"
    page.write_text("- (verified 2026-11-17; bukti: x hal. 1) tabel di catatan modal\n")
    monkeypatch.setattr(ce, "MEMORY_DIR", memory)
    monkeypatch.setattr(ce, "_label_values", lambda ticker=None: {4_205_476})
    assert ce.lint_memory() == []
    page.write_text("- (verified 2026-11-17; bukti: x hal. 1) beredar 4.205.476\n"
                    "- (kemarin) catatan tanpa format\n")
    problems = ce.lint_memory()
    assert any("label value" in p for p in problems)
    assert any("note without" in p for p in problems)


def test_memory_injected_only_when_enabled(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "fields").mkdir(parents=True)
    (memory / "MEMORY.md").write_text("INDEX")
    (memory / "fields" / "aset.md").write_text("ASET RULE")
    (memory / "fields" / "kas.md").write_text("KAS RULE")
    monkeypatch.setattr(claudecode, "MEMORY_DIR", memory)
    monkeypatch.setattr(claudecode, "ROOT", tmp_path)
    monkeypatch.setenv("CLAUDE_MEMORY", "on")
    text = claudecode.memory_for("TRIN", ["aset"])
    assert "INDEX" in text and "ASET RULE" in text and "KAS RULE" not in text
    monkeypatch.setenv("CLAUDE_MEMORY", "off")
    assert claudecode.memory_for("TRIN", ["aset"]) == ""
