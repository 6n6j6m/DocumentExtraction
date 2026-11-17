#!/usr/bin/env python3
"""
Filing downloaded statements by what they contain, not by what they are called.

The archive once held a Q1 report under a Q2 name; these tests make sure the content
decides the quarter, a duplicate is caught by its hash, and nothing is guessed.

Run:  python -m pytest tests/test_organize_filings.py -v
"""

import importlib.util
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("organize_filings",
                                              ROOT / "scripts" / "organize_filings.py")
org = importlib.util.module_from_spec(spec)
spec.loader.exec_module(org)
ARCHIVE = Path.home() / "FinancialReport"


def test_the_current_period_is_the_latest_quarter_end_in_the_header():
    header = "LAPORAN POSISI KEUANGAN\n30 Juni 2024 dan 31 Desember 2023\nJune 30, 2024"
    dates = org.quarter_end_dates(header)
    assert max(dates) == date(2024, 6, 30)
    assert org.QUARTER_OF[(6, 30)] == "Q2"
    # A date that is not a quarter end (an authorisation date) is not a period.
    assert org.quarter_end_dates("diotorisasi pada tanggal 25 Juli 2024") == []
    # A column header split over two lines: the year below "December 31," belongs to
    # the other column, so it is not this date's year.
    split = "30 Juni/ 31 Desember/\nJune 30, Catatan/ December 31,\n2022 Notes 2021"
    assert date(2022, 12, 31) not in org.quarter_end_dates(split)


def test_a_header_extracted_with_glued_words_is_still_read():
    # PGN's 2023 annual statements extract without spaces between words.
    header = ("LAPORANPOSISIKEUANGAN CONSOLIDATED\n"
              "TANGGAL31DESEMBER2023 ASOFDECEMBER31,2023")
    assert org._STATEMENT_TITLE.search(header)
    assert org.quarter_end_dates(header) == [date(2023, 12, 31)] * 2
    # A longer number ending in a day is not a day.
    assert org.quarter_end_dates("No. 131 Desember 2023") == []


def _pdf(ticker, stem):
    path = ARCHIVE / ticker / f"{stem}.pdf"
    if not path.exists():
        pytest.skip("the filing archive is not on this machine")
    return path


def test_a_file_whose_name_claims_the_wrong_quarter_is_filed_by_its_content(tmp_path):
    q1 = _pdf("TRUK", "Q1_2023_TRUK")
    downloads, archive = tmp_path / "dl", tmp_path / "archive"
    downloads.mkdir(); (archive / "TRUK").mkdir(parents=True)
    shutil.copy(q1, downloads / "FinancialStatement-2023-II-TRUK.pdf")   # claims Q2
    shutil.copy(q1, downloads / "LK TW1 TRUK.pdf")                        # same bytes
    rows = org.plan(sorted(downloads.glob("*.pdf")), "TRUK", archive)
    actions = {Path(r["file"]).name: (r["action"], Path(r["target"]).name if r["target"] else "")
               for r in rows}
    assert actions["FinancialStatement-2023-II-TRUK.pdf"] == ("copy", "Q1_2023_TRUK.pdf")
    assert actions["LK TW1 TRUK.pdf"][0] == "skip"          # the duplicate


def test_an_existing_file_is_never_overwritten_silently(tmp_path):
    q2 = _pdf("TRUK", "Q2_2023_TRUK")
    q1 = _pdf("TRUK", "Q1_2023_TRUK")
    downloads, archive = tmp_path / "dl", tmp_path / "archive"
    downloads.mkdir(); (archive / "TRUK").mkdir(parents=True)
    shutil.copy(q1, archive / "TRUK" / "Q2_2023_TRUK.pdf")   # wrong content already there
    shutil.copy(q2, downloads / "x.pdf")
    row = org.plan([downloads / "x.pdf"], "TRUK", archive)[0]
    assert row["action"] == "conflict" and row["target"].endswith("Q2_2023_TRUK.pdf")


def test_without_a_ticker_nothing_is_guessed(tmp_path):
    src = _pdf("GTRA", "Q2_2024_GTRA")
    downloads = tmp_path / "dl"; downloads.mkdir()
    shutil.copy(src, downloads / "laporan_keuangan.pdf")
    row = org.plan([downloads / "laporan_keuangan.pdf"], None, tmp_path / "archive",
                   issuers={})[0]
    assert row["action"] == "skip" and "ticker unknown" in row["reason"]


def test_without_a_ticker_the_idx_listing_names_the_issuer(tmp_path):
    src = _pdf("GTRA", "Q2_2024_GTRA")
    downloads = tmp_path / "dl"; downloads.mkdir()
    shutil.copy(src, downloads / "laporan_keuangan.pdf")
    issuers = {org._company_key("Grahaprima Suksesmandiri Tbk."): "GTRA"}
    row = org.plan([downloads / "laporan_keuangan.pdf"], None, tmp_path / "archive",
                   issuers=issuers)[0]
    assert row["listed_as"] == "GTRA" and row["action"] == "copy"
    assert row["target"].endswith("GTRA/Q2_2024_GTRA.pdf")


def test_ticker_files_only_that_issuer_and_holds_back_another_company(tmp_path):
    """--ticker TRUK on a folder that also holds a PURA download."""
    downloads, archive = tmp_path / "dl", tmp_path / "archive"
    downloads.mkdir(); (archive / "TRUK").mkdir(parents=True)
    shutil.copy(_pdf("TRUK", "Q1_2023_TRUK"), downloads / "a.pdf")
    shutil.copy(_pdf("TRUK", "Q2_2023_TRUK"), downloads / "b.pdf")
    shutil.copy(_pdf("PURA", "Q1_2023_PURA"), downloads / "FinancialStatement-2023-I-PURA.pdf")
    shutil.copy(_pdf("PURA", "Q2_2023_PURA"), downloads / "lk.pdf")      # no ticker in name
    rows = {Path(r["file"]).name: r for r in org.plan(sorted(downloads.glob("*.pdf")),
                                                      "TRUK", archive, issuers={})}
    assert rows["a.pdf"]["action"] == rows["b.pdf"]["action"] == "copy"
    assert rows["FinancialStatement-2023-I-PURA.pdf"]["action"] == "skip"
    assert rows["lk.pdf"]["action"] == "conflict" and "names" in rows["lk.pdf"]["reason"]


def test_files_named_for_the_ticker_set_the_reference_company(tmp_path):
    """Three unnamed PURA downloads must not outvote one TRUK file named for TRUK."""
    downloads, archive = tmp_path / "dl", tmp_path / "archive"
    downloads.mkdir(); (archive / "TRUK").mkdir(parents=True)
    shutil.copy(_pdf("TRUK", "Q1_2023_TRUK"), downloads / "FinancialStatement-2023-I-TRUK.pdf")
    for i, stem in enumerate(["Q1_2023_PURA", "Q2_2023_PURA", "Q3_2023_PURA"]):
        shutil.copy(_pdf("PURA", stem), downloads / f"unnamed{i}.pdf")
    rows = {Path(r["file"]).name: r for r in org.plan(sorted(downloads.glob("*.pdf")),
                                                      "TRUK", archive, issuers={})}
    assert rows["FinancialStatement-2023-I-TRUK.pdf"]["action"] == "copy"
    assert all(rows[f"unnamed{i}.pdf"]["action"] == "conflict" for i in range(3))


def test_the_trading_code_is_read_as_printed_in_the_notes():
    printed = "didaftarkan di Bursa Efek Indonesia dengan kode perdagangan “ELSA”/"
    assert org._TRADING_CODE.search(printed).group(1) == "ELSA"
    assert org._TRADING_CODE.search("Kode saham: TRUK").group(1) == "TRUK"
    # The English column's "ticker" sits next to a share count, not a code.
    assert org._TRADING_CODE.search("ticker 7.298.500.000 100") is None


def test_a_printed_trading_code_outweighs_a_majority_of_other_companies(tmp_path):
    """One Elnusa report printing "ELSA" against two unnamed PURA downloads: the code
    decides which company ELSA is, and a PURA download asked for as ELSA is held back."""
    downloads, archive = tmp_path / "dl", tmp_path / "archive"
    downloads.mkdir(); (archive / "ELSA").mkdir(parents=True)
    shutil.copy(_pdf("ELSA", "Q1_2022_ELSA"), downloads / "elnusa.pdf")
    shutil.copy(_pdf("PURA", "Q1_2023_PURA"), downloads / "x1.pdf")
    shutil.copy(_pdf("PURA", "Q2_2023_PURA"), downloads / "x2.pdf")
    rows = {Path(r["file"]).name: r for r in org.plan(sorted(downloads.glob("*.pdf")),
                                                      "ELSA", archive, issuers={})}
    assert rows["elnusa.pdf"]["code"] == "ELSA" and rows["elnusa.pdf"]["action"] == "copy"
    assert rows["x1.pdf"]["action"] == rows["x2.pdf"]["action"] == "conflict"
    assert "trading code" in rows["x1.pdf"]["reason"]


def test_a_file_printing_another_trading_code_is_skipped(tmp_path):
    downloads = tmp_path / "dl"; downloads.mkdir()
    shutil.copy(_pdf("ELSA", "Q1_2022_ELSA"), downloads / "lk.pdf")
    row = org.plan([downloads / "lk.pdf"], "PURA", tmp_path / "archive", issuers={})[0]
    assert row["action"] == "skip" and "trading code ELSA" in row["reason"]


def test_a_misprinted_comparative_header_does_not_move_the_period(tmp_path):
    """TRUK's 2022 interims head the audited column "31 Desember 2021" in Indonesian and
    "December 31, 2022" in English; the title line still says which quarter it is."""
    downloads = tmp_path / "dl"; downloads.mkdir()
    shutil.copy(_pdf("TRUK", "Q1_2022_TRUK"), downloads / "lk.pdf")
    row = org.plan([downloads / "lk.pdf"], "TRUK", tmp_path / "archive")[0]
    assert row["period"] == "Q1 2022" and row["action"] == "copy"


def test_the_idx_listing_holds_back_a_download_of_another_issuer(tmp_path):
    """A PURA report that prints no trading code, asked for as TRUK: the listing says
    whose it is, so no majority is needed."""
    downloads = tmp_path / "dl"; downloads.mkdir()
    shutil.copy(_pdf("PURA", "Q2_2023_PURA"), downloads / "lk.pdf")
    issuers = {org._company_key("Putra Rajawali Kencana Tbk."): "PURA"}
    row = org.plan([downloads / "lk.pdf"], "TRUK", tmp_path / "archive", issuers=issuers)[0]
    assert row["action"] == "skip" and "listed on IDX as PURA" in row["reason"]


def test_company_names_match_across_spellings():
    key = org._company_key
    assert key("PT Bukit Asam (Persero) Tbk") == key("Bukit Asam Tbk.")
    assert key("PP London Sumatra Indonesia Tb") == key("PT PP London Sumatra Indonesia Tbk")
    assert key("PT ELNUSA TBK") == key("Elnusa Tbk.")
    assert key("PT AKR Corporindo Tbk") != key("PT Elnusa Tbk")


def test_overwrite_never_files_a_company_conflict(tmp_path, monkeypatch):
    """--overwrite replaces a target holding another document; it must not turn a
    held-back download (no target) into a copy."""
    rows = [{"file": str(tmp_path / "x.pdf"), "action": "conflict", "target": "",
             "replaces": "", "reason": "the PDF names another company"}]
    monkeypatch.setattr(org, "plan", lambda *a, **k: rows)
    (tmp_path / "x.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(sys, "argv", ["organize_filings.py", str(tmp_path / "x.pdf"),
                                      "--ticker", "TRUK", "--apply", "--overwrite",
                                      "--manifest", str(tmp_path / "m.csv")])
    monkeypatch.chdir(tmp_path)
    assert org.main() == 0
    assert rows[0]["action"] == "conflict"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["m.csv", "x.pdf"]


def test_a_name_cut_at_idx_width_still_finds_its_issuer(tmp_path):
    book = tmp_path / "issuers.json"
    book.write_text('{"issuers": [{"ticker": "KSIX", "name": "Kentanix Supra International T"},'
                    ' {"ticker": "ELSA", "name": "Elnusa Tbk."}]}')
    issuers = org.load_issuers([book])
    assert org.issuer_of("PT Kentanix Supra International Tbk", issuers) == "KSIX"
    assert org.issuer_of("PT ELNUSA TBK", issuers) == "ELSA"
    # A complete name is never a prefix: "Elnusa" must not claim "Elnusa Petrofin".
    assert org.issuer_of("PT Elnusa Petrofin Tbk", issuers) == ""


def test_the_issuer_name_is_read_from_the_statement_heading():
    glued = "PT ELNUSATBKDAN ENTITAS ANAKNYA PT ELNUSA TBK AND ITS SUBSIDIARIES"
    assert org._COMPANY.search(glued).group(0) == "PT ELNUSA TBK"
    assert org._company_key("Perusahaan Perkebunan London Sumatra Indonesia Tbk") != \
        org._company_key("PP London Sumatra Indonesia Tbk"), "an alias is needed, and kept"
