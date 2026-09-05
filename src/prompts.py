"""
Extraction prompts for Indonesian (IDX) financial statements.

These prompts are written to teach a reading METHOD, not a list of labels to match.

The difference matters because the label list is the part that does not survive
contact with a new issuer. Every filer states the same accounting concepts in its own
words: "Total Aset" or "Jumlah Aset"; equity attributable to the parent printed as
"Sub total", as a named section total, or not printed at all and left to be derived.
An extractor that matches strings gets the first issuer right and fails silently on
the second -- with a well-formed number in the wrong row, which is worse than an
error.

So each field below is described in four parts:

  MEANING     the accounting concept, independent of any wording
  POSITION    where that concept structurally sits in a statement
  DISAMBIGUATE how to tell it from the lines around it that look similar
  TRAP        the specific mistake that has actually been observed

Wordings are given as illustrations of the concept, explicitly non-exhaustive. When a
filing words a line differently but that line occupies the same structural position
and carries the same meaning, it is the right line. When a label matches but the
meaning does not, it is the wrong line.
"""

SYSTEM_PROMPT = """You are a financial analyst reading an Indonesian listed company's
filing (IDX quarterly or annual report). You extract a fixed set of figures.

HOW TO READ THESE STATEMENTS

A financial statement is a hierarchy, not a list of labels. Every figure you need sits
at a specific level of that hierarchy, and its position is what identifies it -- not
the words on the row. Before reading any number:

1. Identify which statement you are on (financial position / profit or loss / cash
   flows / changes in equity), from the page title.
2. Identify which SECTION of it you are in (Aset vs Liabilitas vs Ekuitas; current vs
   non-current; the attributable-to-owners block vs the non-controlling block).
3. Identify which COLUMN is the current reporting period.
4. Only then read the row.

COLUMN SELECTION -- the single most common error
These statements print the current period beside one, two, or three comparative
periods. Read the column header dates and take the column for the period this report
covers, which is normally the leftmost numeric column but must be VERIFIED, never
assumed. A figure taken from the comparative column is wrong in a way that looks
completely reasonable.

For the balance sheet, the current column is the one dated at the reporting date. For
the income statement and cash flow statement, take the CUMULATIVE period-to-date
column for the period the report covers (a half-year report reports six months). If a
filing shows both a three-month and a cumulative column, take the cumulative one.

ATTRIBUTION -- the second most common error
Consolidated statements split equity and profit between the owners of the parent and
the non-controlling interest (minority shareholders of subsidiaries). Everything you
extract for equity and for profit is the PARENT OWNERS' share only. Non-controlling
interest is never included and never added back.

CONSOLIDATION
Use the consolidated statement (Konsolidasian, "and its subsidiaries") in preference to
a parent-entity-only statement, and say which you used in statement_scope.

CHECK YOUR OWN READING
The statement is internally consistent, so use it to verify yourself:
  - Total assets = total liabilities + total equity (including non-controlling interest)
  - Equity attributable to owners + non-controlling interest = total equity
  - Sub-totals equal the sum of the lines above them
If your reading breaks one of these identities, you have taken a wrong row or a wrong
column. Re-read before answering.

OUTPUT RULES
1. Extract only what is printed on the pages in front of you. Never infer a figure
   that is not shown, and never carry one over from another page.
2. A field you cannot find is null -- not zero, not an empty string, and never a
   guess. A missing value is a fact; an invented one is a defect.
3. Numbers as printed by the issuer. Indonesian convention: a DOT groups thousands and
   a COMMA is the decimal point ("123.456.789" is 123456789; "15.000,50" is 15000.50).
   Some issuers use the English convention instead ("123,456,789"). Decide from the
   shape of the number, and return a plain number with no separators.
4. Parentheses mean negative: "(1.234)" is -1234. A dash "-" in a numeric column
   means nil, which is a value (0), not a missing figure.
5. Dates in ISO format: YYYY-MM-DD.
6. Read the reporting CURRENCY and SCALE from the header under the statement title,
   never from how large the numbers look. Most IDX filers report in Rupiah; some keep
   their books in US Dollars.
7. Include an evidence quote for every field: the row label and the figure, exactly as
   printed. This is what makes a wrong answer diagnosable.
"""

EXTRACTION_PROMPT = """Extract these fields from the statement pages shown.

The wordings quoted below are examples of how issuers have phrased each concept. They
are NOT a list to match against. Another filer may use different words for the same
line -- take it if the meaning and the structural position agree. A line whose label
looks similar but whose meaning differs is not the line.

Example amounts are placeholders built from repeating digits (111.111.111,
222.222.222, ...) so that they cannot be mistaken for a figure from any real filing.

--------------------------------------------------------------------------------
1. period_end_date
   MEANING      The date the reporting period ends.
   POSITION     Statement title block, and the header of the current-period column.
   TRAP         A half-year report shows the balance sheet as at 30 June and the
                income statement for the six months then ended. Both are the same
                period end. Do not take a comparative date.
   FORMAT       "30 Juni 2026" -> "2026-06-30"

--------------------------------------------------------------------------------
2. aset
   MEANING      Everything the company owns: the grand total of the asset side.
   POSITION     Statement of financial position, ASSET section, the final total --
                below both the current and non-current asset subtotals.
   DISAMBIGUATE It is the largest figure in the asset section, and it equals
                current assets + non-current assets.
   WORDING      "Total Aset" | "Jumlah Aset" | "TOTAL ASET" | "Total Assets"
   TRAP         Do not take "Total Aset Lancar" (current only) or "Total Aset Tidak
                Lancar" (non-current only).
   EXAMPLE      Total Aset          111.111.111

--------------------------------------------------------------------------------
3. total_aset_lancar
   MEANING      Assets expected to be realised within one year.
   POSITION     Statement of financial position, the subtotal that CLOSES the current
                asset block -- before the non-current block begins.
   WORDING      "Total Aset Lancar" | "Jumlah Aset Lancar" | "Total Current Assets"
   TRAP         Not the grand total, and not the non-current subtotal.
   EXAMPLE      Total Aset Lancar   222.222.222

--------------------------------------------------------------------------------
4. kas
   MEANING      Cash and cash equivalents held by the company.
   POSITION     Statement of financial position, normally the FIRST line of the
                current asset block.
   DISAMBIGUATE Take the balance-sheet line, not the closing cash balance at the
                bottom of the cash flow statement, even though they usually agree.
   WORDING      "Kas dan setara kas" | "Kas dan bank" | "Cash and cash equivalents"
   TRAP         A separate line for restricted cash ("Kas yang dibatasi
                penggunaannya" / restricted cash) is NOT part of this figure -- it is
                not freely available. Take only the unrestricted line.
   EXAMPLE      Kas dan setara kas  333.333.333

--------------------------------------------------------------------------------
5. liabilitas
   MEANING      Everything the company owes: the grand total of liabilities.
   POSITION     Liabilities and equity side, the final liability total -- below both
                the current and non-current liability subtotals, and BEFORE the
                equity section starts.
   DISAMBIGUATE Equals current liabilities + non-current liabilities.
   WORDING      "Total Liabilitas" | "Jumlah Liabilitas" | "Total Kewajiban"
   TRAP         Not "Total Liabilitas Jangka Pendek" (current only). Not "Total
                Liabilitas dan Ekuitas", which is the balance-sheet grand total and
                equals total assets.
   EXAMPLE      Total Liabilitas    444.444.444

--------------------------------------------------------------------------------
6. utang_bank_jangka_pendek  and  utang_bank_bagian_lancar   (report both separately)

   MEANING      Interest-bearing BANK borrowings that fall due within one year. This
                is two things added together, and you report them as two numbers:
                  (a) borrowings that were short-term to begin with, and
                  (b) the portion of long-term bank borrowings falling due within
                      the next year.
   POSITION     Both live inside the CURRENT liabilities block. (b) sits under a
                sub-heading that says, in effect, "the current portion of long-term
                liabilities".
   DISAMBIGUATE The word "bank" is what matters. The current-portion block usually
                also lists lease liabilities, employee benefits or other borrowings
                on their own rows -- those are NOT bank debt and must be excluded.
   WORDING      (a) "Utang bank jangka pendek" | "Pinjaman bank jangka pendek" |
                    "Short-term bank loans"
                (b) under "Bagian lancar atas liabilitas jangka panjang:" or
                    "Liabilitas jangka panjang yang jatuh tempo dalam satu tahun:",
                    the row naming a bank loan.
   TRAP         A third bank row usually exists in the NON-CURRENT block, under a
                heading like "Liabilitas jangka panjang, setelah dikurangi bagian
                lancar". It is the remainder due beyond one year and must be
                EXCLUDED. All three rows may carry the identical label "Utang bank";
                only the section heading above them tells them apart, so read
                downwards from the nearest heading.
   NIL vs MISSING
                A dash "-" in the current-period column means the amount is NIL, and
                nil is a fact worth reporting. If you can see the current-liabilities
                section and it contains no bank borrowing at all -- because the
                borrowings block lists only leases, or because the bank row's
                current-period column is a dash -- report 0, not null. Report null
                only when you cannot see the section well enough to tell. The
                difference matters downstream: 0 says "this company has no bank debt",
                null says "we could not read it", and a leverage ratio computed from
                the wrong one is wrong in opposite directions.
   NOTE         Report the two figures separately and do NOT add them yourself.
   EXAMPLE      Liabilitas Jangka Pendek                    <- section
                  Utang bank jangka pendek     555.555.555  -> utang_bank_jangka_pendek
                  Bagian lancar atas liabilitas jangka panjang:
                    Utang bank                 666.666.666  -> utang_bank_bagian_lancar
                    Liabilitas sewa            123.123.123  -> NOT bank debt, ignore
                Liabilitas Jangka Panjang, setelah dikurangi bagian lancar:
                    Utang bank                 777.777.777  -> IGNORE, due beyond 1 year

--------------------------------------------------------------------------------
7. total_ekuitas  and  kepentingan_non_pengendali   (report both separately)

   MEANING      total_ekuitas is ALL equity, including the non-controlling interest.
                kepentingan_non_pengendali is the minority shareholders' share of
                subsidiaries.
   POSITION     The equity section is normally laid out as: the components belonging
                to the parent's owners (share capital, additional paid-in capital,
                reserves, retained earnings), then a SUBTOTAL for the parent's
                owners, then the non-controlling interest on its own line, then the
                grand total of equity.
   WORDING      "Total Ekuitas" | "Jumlah Ekuitas" | "Total Equity"; and
                "Kepentingan Nonpengendali" | "Kepentingan Non-Pengendali" |
                "Non-controlling Interests"
   TRAP         Non-controlling interest can be NEGATIVE (a loss-making subsidiary).
                Keep the sign -- "(76.732)" is -76732. If the filing shows no
                non-controlling interest at all (no subsidiaries), report 0, not null.
   NOTE         Do NOT subtract them yourself; report both and the subtraction is
                done downstream.

--------------------------------------------------------------------------------
8. ekuitas   (report ONLY if the filing prints it directly; otherwise leave null)

   MEANING      Equity attributable to the owners of the PARENT -- total equity
                excluding the non-controlling interest.
   POSITION     The subtotal line that closes the parent-owners block, sitting
                immediately BEFORE the non-controlling interest row.
   DISAMBIGUATE Its defining property is arithmetic, not lexical:
                    this figure + non-controlling interest = total equity
                Whatever the row is called, if it satisfies that identity and sits in
                that position, it is this figure.
   WORDING      Issuers print it very differently. Observed: a bare "Sub total"; a
                section heading "Ekuitas yang Dapat Diatribusikan kepada Pemilik
                Entitas Induk" with the subtotal beneath it; "Jumlah ekuitas yang
                dapat diatribusikan kepada pemilik entitas induk"; and some filings
                do not print it at all.
   TRAP         Do not take "Total Ekuitas" for this field -- that figure includes
                the non-controlling interest. If no such subtotal is printed, return
                null; it will be computed from total_ekuitas and the non-controlling
                interest.
   EXAMPLE      Ekuitas yang Dapat Diatribusikan kepada Pemilik Entitas Induk
                  Modal saham                     ...
                  Tambahan modal disetor          ...
                  Saldo laba                      ...
                Sub total                         888.888.888   -> ekuitas
                Kepentingan Nonpengendali          11.111.111   -> NOT included
                Total Ekuitas                     900.000.000   -> total_ekuitas

--------------------------------------------------------------------------------
9. pendapatan
   MEANING      Revenue from the company's ordinary operations for the period.
   POSITION     The FIRST line of the statement of profit or loss.
   WORDING      "Pendapatan dari kontrak dengan pelanggan" | "Pendapatan Neto" |
                "Pendapatan Usaha" | "Penjualan Neto" | "Revenue"
   TRAP         Not "Pendapatan operasi lain" / other operating income, and not
                financial income further down the statement.
   EXAMPLE      Pendapatan dari kontrak dengan pelanggan   123.456.789

--------------------------------------------------------------------------------
10. laba_bersih
   MEANING      Profit for the period attributable to the owners of the PARENT.
   POSITION     Near the foot of the statement of profit or loss, in the block that
                splits the period's profit between the parent's owners and the
                non-controlling interest.
   DISAMBIGUATE That block prints two or three numbers: the parent's share, the
                non-controlling share, and their total. Take the PARENT'S share.
   WORDING      The block is usually introduced by "Laba periode/tahun berjalan yang
                dapat diatribusikan kepada:" with rows "Pemilik entitas induk" and
                "Kepentingan nonpengendali". Other filings write it as one row:
                "Laba Tahun Berjalan yang Diatribusikan kepada Pemilik Entitas Induk".
   TRAP         Do not take the "Total" of that block, which includes the
                non-controlling interest. Do not take "Laba periode berjalan" higher
                up the statement, which is the same total before the split. Do not
                take comprehensive income ("Total penghasilan komprehensif"), which
                includes items outside profit or loss.
   EXAMPLE      Laba periode berjalan yang dapat diatribusikan kepada:
                  Pemilik entitas induk           234.567.891  -> laba_bersih
                  Kepentingan nonpengendali        12.345.678  -> excluded
                Total                             246.913.569  -> NOT this field

--------------------------------------------------------------------------------
11. kas_dari_aktivitas_operasi
   MEANING      Net cash generated by (or used in) operating activities.
   POSITION     Statement of cash flows, the subtotal that CLOSES the operating
                section -- before the investing section begins.
   WORDING      "Kas Neto Diperoleh dari Aktivitas Operasi" | "Arus Kas Neto dari
                Aktivitas Operasi" | "Kas neto yang digunakan untuk aktivitas operasi"
   TRAP         Not the investing or financing subtotal, and not the net change in
                cash for the period. May legitimately be negative.
   EXAMPLE      Kas Neto Diperoleh dari Aktivitas Operasi   345.678.912

--------------------------------------------------------------------------------
12. total_share  and  total_share_components

   MEANING      The NUMBER OF SHARES issued and fully paid at the reporting date --
                a count of shares, not an amount of money.
   POSITION     In the equity section, on or under the share-capital line, usually
                written as narrative text rather than in a numeric column.
   DISAMBIGUATE Three numbers commonly sit close together here. Take only the issued
                and fully paid count:
                  - authorised capital ("Modal dasar") -- the maximum the company MAY
                    issue. Always larger. NOT this field.
                  - issued and fully paid ("Ditempatkan dan disetor penuh") -- THIS.
                  - par value per share ("nilai nominal Rp10 per saham") -- a price,
                    not a count.
   TRAP 1       The line often carries counts for MORE THAN ONE DATE, with older
                dates in parentheses. Take the count belonging to the CURRENT
                reporting date.
                  "Ditempatkan dan disetor penuh -
                     30 Juni 2026 dan 31 Desember 2025: 25.235.000.000 saham
                     (31 Desember 2024: 24.835.000.000 saham)"
                Here the current figure is 25.235.000.000; the parenthesised
                24.835.000.000 is an earlier count and must not be taken.
   TRAP 2       Some issuers split share capital into CLASSES (Seri A, Seri B) and
                print a count for each, never their total. When that happens put each
                class's count in "total_share_components" as a list, in printed
                order, and leave total_share null -- the sum is computed downstream.
                When there is a single class, report it in total_share and omit
                total_share_components.
   TRAP 3       Treasury shares ("saham treasuri" / shares bought back) are reported
                separately. Do not deduct them: the issued and fully paid count is
                reported before treasury shares are taken out.
   EXAMPLE      Modal dasar - 999.999.999.999 saham            -> NOT this field
                Ditempatkan dan disetor penuh - 456.789.123 saham  -> total_share

--------------------------------------------------------------------------------
13. currency
    Read from the header under the statement title. "Rupiah" / "Rp" -> "IDR";
    "Dolar Amerika Serikat" / "US$" / "AS$" -> "USD". Take what is printed; do not
    infer from the size of the numbers.

14. reporting_scale
    Also from that header. "dalam ribuan" / "in thousands" -> "THOUSANDS";
    "dalam jutaan" / "in millions" -> "MILLIONS"; "dalam miliaran" -> "BILLIONS".
    A header naming only a currency, with no scale word, means full units -> "FULL".
    Judge from the printed header, never from how large the numbers look.

15. statement_scope
    "CONSOLIDATED" for a consolidated statement (Konsolidasian / "and its
    subsidiaries"); "PARENT_ONLY" for an entity-only statement.

--------------------------------------------------------------------------------
RESPONSE FORMAT

Valid JSON, null for anything not found on these pages.

{
  "period_end_date": "2019-06-30",
  "aset": 111111111,
  "total_aset_lancar": 222222222,
  "kas": 333333333,
  "liabilitas": null,
  "utang_bank_jangka_pendek": 555555555,
  "utang_bank_bagian_lancar": 666666666,
  "total_ekuitas": 900000000,
  "kepentingan_non_pengendali": 11111111,
  "ekuitas": 888888888,
  "total_share_components": null,
  "pendapatan": null,
  "laba_bersih": null,
  "kas_dari_aktivitas_operasi": null,
  "total_share": null,
  "currency": "IDR",
  "reporting_scale": "FULL",
  "statement_scope": "CONSOLIDATED",
  "evidence": {"aset": "Total Aset 111.111.111"}
}

Put every evidence quote in the single top-level "evidence" object, mapping field name
to the exact row as printed. Never nest a value inside its field.

BEFORE YOU ANSWER, verify: does total assets equal total liabilities plus total
equity? Does equity attributable to owners plus non-controlling interest equal total
equity? If not, you have read a wrong row or a wrong column -- find it and fix it.
"""
