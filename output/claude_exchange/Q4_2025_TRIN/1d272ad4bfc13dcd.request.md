# Permintaan ekstraksi 1d272ad4bfc13dcd

Filing: `/Users/muhammadnajmirahmani/FinancialReport/TRIN/Q4_2025_TRIN.pdf` · emiten: TRIN · field: kas_dari_aktivitas_operasi

Anda menggantikan model ekstraksi pipeline. Jawab HANYA dari halaman di bawah (dipilih
oleh kode). Jangan membuka PDF lain, CSV hasil, workbook, `data/ground_truth/`, atau
`output/evaluation/`. Tulis jawaban sebagai satu objek JSON persis seperti yang diminta
PROMPT ke `/Users/muhammadnajmirahmani/Belajar/ProjectDatasaur/output/claude_exchange/Q4_2025_TRIN/1d272ad4bfc13dcd.answer.json` (tanpa teks lain), lalu periksa dengan:

    python scripts/claude_extract.py check /Users/muhammadnajmirahmani/Belajar/ProjectDatasaur/output/claude_exchange/Q4_2025_TRIN/1d272ad4bfc13dcd.answer.json

Angka ditulis apa adanya seperti tercetak (skala dan mata uang diurus kode). Field yang
tidak didukung halaman ini = null; jangan menebak.

## Memori (catatan dari evaluasi sebelumnya; petunjuk, bukan jawaban -- halaman di bawah tetap yang menentukan)

<!-- memory/extraction/MEMORY.md -->
# Memori ekstraksi (dibaca setiap permintaan)

Untuk apa: hal-hal yang TIDAK terlihat dari halaman permintaan itu sendiri, yaitu
konvensi yang diputuskan user dan jebakan yang terbukti dari evaluasi. Bukan jawaban:
memori tidak pernah memuat angka label. Halaman yang diberikan tetap yang menentukan.
Kalau catatan bertentangan dengan halaman, ikuti halaman dan laporkan pertentangannya.

Format catatan: `- (verified|hipotesis YYYY-MM-DD; bukti: <PDF hal./laporan eval/CP>) aturan`.
Satu halaman per emiten (`issuers/<T>.md`) dan per field (`fields/<field>.md`); kode
hanya menyuntikkan halaman ini, halaman emiten filing itu, dan halaman field yang diminta.

## Konvensi umum

- (verified 2026-11-01; bukti: CHECKPOINT aturan tetap) Angka ditulis apa adanya seperti tercetak; skala ("dalam ribuan/jutaan") dan kurs USD diurus kode.
- (verified 2026-10-17; bukti: CP19, CP22) Selalu kolom periode berjalan (biasanya kolom angka pertama); jangan pakai kolom pembanding tahun/kuartal lalu.
- (verified 2026-10-17; bukti: CP21) Laporan konsolidasian, bukan entitas induk saja (halaman entitas induk biasanya di lampiran belakang).

<!-- memory/extraction/issuers/TRIN.md -->
# TRIN

- (verified 2026-10-17; bukti: CP21, Q4_2024_TRIN.pdf hal. 11-17 vs 127-132) Filing tahunan memuat laporan entitas induk di lampiran; angka konsolidasian ada di halaman awal.
- (verified 2026-10-17; bukti: CP17) Catatan utang memisahkan lender bank dan non-bank dalam baris berbeda; keduanya masuk utang_bank (lihat fields/utang_bank.md).

---

## SYSTEM

You are a financial analyst reading an Indonesian listed company's
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


## PROMPT

Extract these fields from the statement pages shown.

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
   TRAP 2       The cash flow statement prints "Kas dan setara kas" several times, and
                its labels often wrap so those words stand alone on a line. Only the
                CLOSING balance ("... akhir periode/tahun" / "at end of period") equals
                kas. The others are movements during the period: "Kenaikan (penurunan)
                neto kas dan setara kas" (net increase) and "Dampak perubahan kurs atas
                kas dan setara kas" (exchange-rate effect). Never report a movement as
                kas, and never add movements together to build it.
   TRAP 3       Some balance sheets print NO total on the cash line. "Kas dan setara
                kas" stands alone as a heading, and the amounts sit on the lines
                directly under it, split by counterparty -- "Pihak berelasi" (related
                parties) and "Pihak ketiga" (third parties). Then report each of those
                sub-line amounts in "kas_components", in printed order, and leave kas
                null: the total is computed downstream. Do not add them up yourself --
                a total you compute is printed nowhere and cannot be checked. Stop at
                the next heading: the "Pihak berelasi" / "Pihak ketiga" lines under
                "Piutang usaha" (receivables) are NOT cash. When the cash line carries
                its own figure, report it in kas and omit kas_components.
                  Kas dan setara kas
                    Pihak berelasi      111.111      -> kas_components [111111, 222222]
                    Pihak ketiga        222.222
                  Piutang usaha                          -> stop here
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

   MEANING      Interest-bearing borrowings from BANKS and NON-BANK FINANCIAL
                INSTITUTIONS that fall due within one year. Report these two amounts:
                  (a) borrowings that were short-term to begin with, and
                  (b) the portion of long-term bank or financial-institution borrowings
                      falling due within the next year.
   POSITION     Both live inside the CURRENT liabilities block. (b) sits under a
                sub-heading that says, in effect, "the current portion of long-term
                liabilities".
   DISAMBIGUATE Include loans from both banks and non-bank financial institutions
                (including finance companies). A combined row such as "Utang Bank dan
                Lembaga Keuangan Non-Bank" is valid for its maturity section. Exclude
                leases, employee benefits, trade payables, other non-financial
                liabilities, and long-term remainder.
   WORDING      (a) "Utang bank jangka pendek" | "Pinjaman bank jangka pendek" |
                    "Short-term bank or finance-company loans"
                (b) under "Bagian lancar atas liabilitas jangka panjang:" or
                    "Liabilitas jangka panjang yang jatuh tempo dalam satu tahun:",
                    the row naming a bank or financial-institution loan.
   TRAP         A long-term remainder may exist in the NON-CURRENT block, under a
                heading like "Liabilitas jangka panjang, setelah dikurangi bagian
                lancar". It is the remainder due beyond one year and must be
                EXCLUDED. Similar loan labels can recur across maturity sections;
                only the section heading above them tells them apart, so read
                downwards from the nearest heading.
   NIL vs MISSING
                A dash "-" in the current-period column means the amount is NIL, and
                nil is a fact worth reporting. If you can see the current-liabilities
                section and it contains no qualifying financial-institution borrowing
                -- because the borrowings block lists only leases, or because the loan row's
                current-period column is a dash -- report 0, not null. Report null
                only when you cannot see the section well enough to tell. The
                difference matters downstream: 0 says "this company has no qualifying
                financial-institution debt"; null says "we could not read it".
   NOTE         Report the two figures separately and do NOT add them yourself.
   EXAMPLE      Liabilitas Jangka Pendek                    <- section
                  Utang bank jangka pendek     555.555.555  -> utang_bank_jangka_pendek
                  Bagian lancar atas liabilitas jangka panjang:
                    Utang Bank / Lembaga Keuangan Non-Bank 666.666.666 -> utang_bank_bagian_lancar
                    Liabilitas sewa            123.123.123  -> NOT financial-institution debt, ignore
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
   BLOCK        Some statements open with a revenue BLOCK: several revenue lines that
                close with a printed total ("Jumlah Pendapatan" / "Total Pendapatan" /
                "Total Revenues") before the cost of revenues. Then take that printed
                total, even when one line in the block is finance income or rental
                income -- the issuer itself presents the block as its revenue.
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
   NO SPLIT     A company with no subsidiaries has no non-controlling interest, so its
                statement prints NO attribution block at all. Then the profit for the
                period IS the parent's share: take "Laba periode/tahun berjalan" (or
                "Laba neto periode berjalan" / "Profit for the period") -- the line
                after income tax, before other comprehensive income. Do not return
                null just because the block is missing; the rule above against the
                higher line applies only when the block exists.
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

   MEANING      Everything about the number of shares OUTSTANDING at the reporting
                date -- the shares held by shareholders other than the company itself.
                Counts of shares, never amounts of money.
   POSITION     The SHAREHOLDER TABLE in the notes ("Susunan pemegang saham", "Komposisi
                pemegang saham", "The composition of the Company's shareholders"): one
                row per shareholder, a percentage column, and a total row beside 100%.
                Read these fields from that table ONLY. Never from the balance sheet or
                the statement of changes in equity: their share-capital line ("Modal
                saham - Modal dasar ... Ditempatkan dan disetor penuh ... saham") is not
                a source for these fields, even when it prints a count.
   REPORT       From the table for the CURRENT reporting date:
                  "total_share" -- the count on the total row, beside 100%.
                  "saham_beredar" -- the outstanding count when the table prints it as
                     a row of its own: "Jumlah saham beredar", "Total saham beredar",
                     "Total shares outstanding", with a percentage just below 100, above
                     a treasury row. Some tables print it as an unlabelled subtotal of
                     the shareholder rows directly above the treasury row; that subtotal
                     is saham_beredar too. null when it is not printed. Never compute it.
                  "saham_treasuri" -- the count on a treasury row ("Saham treasuri",
                     "Modal saham diperoleh kembali", "Treasury stock/shares"). A count,
                     never its cost. null when the current table has no such row.
                A table with no treasury row means every share is outstanding: report
                the total row in total_share and leave the other two null. Any
                subtraction is done downstream.
   TRAP 1       The note usually prints the table TWICE, once per date -- the current
                date first, the comparative date below it or on the next page. Use only
                the table headed by the CURRENT reporting date. A treasury row that
                appears only in the comparative table does not exist at the current date.
   TRAP 2       Not the weighted average number of shares ("rata-rata tertimbang saham
                beredar", "weighted average number of shares outstanding") in the
                earnings-per-share note. That is an average over the period, not the
                count at the reporting date.
   TRAP 3       Not authorised capital ("Modal dasar"), not a par value ("nilai nominal
                Rp100 per saham"), and not a count quoted in narrative text about the
                listing or a past stock split.
   TRAP 4       Some tables split the rows into CLASSES (Seri A, Seri B) with a total per
                class and no grand total. Then put each class's total in
                "total_share_components", in printed order, and leave total_share null.
                When there is a grand total row, report it in total_share and omit
                total_share_components.
   TRAP 5       Never compute a count from share capital divided by par value, or by any
                other arithmetic. If no shareholder table is on the pages you were
                given, return null for all of these fields.
   EXAMPLE      31 Desember 2025
                  PT Induk                    6.000.000.000   51,72
                  Masyarakat                  5.500.000.000   47,41
                  Total saham beredar        11.500.000.000   99,14  -> saham_beredar
                  Saham treasuri                100.000.000    0,86  -> saham_treasuri
                  Total                      11.600.000.000  100,00  -> total_share
                31 Desember 2024                                     -> ignore this table

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
  "kas_components": null,
  "liabilitas": null,
  "utang_bank_jangka_pendek": 555555555,
  "utang_bank_bagian_lancar": 666666666,
  "utang_bank_bagian_lancar_components": null,
  "total_ekuitas": 900000000,
  "kepentingan_non_pengendali": 11111111,
  "ekuitas": 888888888,
  "total_share_components": null,
  "pendapatan": null,
  "laba_bersih": null,
  "kas_dari_aktivitas_operasi": null,
  "total_share": null,
  "saham_beredar": null,
  "saham_treasuri": null,
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


=== THIS REQUEST ONLY ===
These pages contain ONLY part of the statements. Extract EXACTLY these fields and nothing else: kas_dari_aktivitas_operasi, period_end_date, currency, reporting_scale, statement_scope. Include every requested key in the JSON. Return null when a requested field is not supported by these pages; never fill it from another period or an unrelated row. Omit all other fields from your JSON.

DOCUMENT:
--- PAGE 16 ---
| Keterangan | kolom 1 | kolom 2 | English |
|---|---|---|---|
| · · · · · · The original consolidated |  |  | financial statements herein are in |
|  |  |  | Indonesian language |
| · · · · PT PERINTIS TRINITI PROPERTI Tbk PT PERINTIS |  |  | TRINITI PROPERTI Tbk |
| · · · · · · DAN ENTITAS ANAKNYA AND ITS |  |  | SUBSIDIARIES |
| · · · LAPORAN ARUS KAS KONSOLIDASIAN CONSOLIDATED STATEMENT |  |  | OF CASH FLOWS |
| · · · Untuk Tahun yang Berakhir pada Tanggal For the |  |  | Year Ended |
| · · · · · · 31 Desember 2025 December |  |  | 31, 2025 |
| · · · · · (Disajikan dalam Ribuan Rupiah, (Expressed in |  |  | Thousands of Rupiah, |
| · · · · · · kecuali dinyatakan lain) unless |  |  | otherwise stated) |
| · · · · · · Catatan / |  |  |  |
| · · · · · · Notes 2025 2024 |  |  |  |
| ARUS KAS DARI AKTIVITAS |  |  | CASH FLOWS FROM |
| · OPERASI |  |  | OPERATING ACTIVITIES |
| Penerimaan kas dari pelanggan | 142.031.740 | 327.227.512 | Cash receipt from customers |
| Pembayaran beban pajak final 8,27c | (4.540.623) | (5.333.717) | Final tax expenses paid |
| Penerimaan dari pelanggan-bersih | 137.491.117 | 321.893.795 | Cash receipts from customers - net |
| Pembayaran kas kepada karyawan | (34.323.173) | (46.196.470) | Cash paid to employees |
| Pembayaran kas kepada pemasok |  |  | Cash paid to suppliers and other |
| · dan beban opersional lainnya | (179.452.577) | (245.115.749) | operating expenses |
| Penempatan pada rekening bank |  |  | Placement on |
| · yang dibatasi penggunaanya | (5.489.679) | (30.634.803) | restricted cash in banks |
| Kas digunakan untuk operasi | (81.774.312) | (53.227) | Cash used in operation |
| Pembayaran beban bunga dan |  |  | Interest and |
| · keuangan | (8.040.759) | (9.566.966) | financial charges |
| Kas Neto |  |  | Net Cash |
| · Digunakan untuk |  |  | Used in |
| · Aktivitas Operasi | (89.815.071) | (9.620.193) | Operating Activities |
| ARUS KAS DARI AKTIVITAS |  |  | CASH FLOWS FROM |
| · INVESTASI |  |  | INVESTING ACTIVITIES |
| Penerimaan bunga | 976.413 | 934.418 | Interest received |
| Penerimaan dari pelepasan |  |  | Proceed from disposal |
| entitas anak 1c - | 325.000 |  | of subsidiary |
| Perolehan aset takberwujud 13 - | (293.834) |  | Acquisitions of intangible assets |
| Penerimaan penjualan aset tetap 14 | 32.520.000 | 134.234 | Proceed from sale of fixed asset |
| Perolehan aset tetap 14 | (80.358) | (1.193.342) | Acquisitions of fixed assets |
| Kas Neto Diperoleh dari |  |  | Net Cash |
| (Digunakan untuk) |  |  | Provided by (Used in) |
| Aktivitas Investasi | 33.447.221 | (124.690) | Investing Activities |
| ARUS KAS DARI AKTIVITAS |  |  | CASH FLOWS |
| PENDANAAN |  |  | FROM FINANCING ACTIVITIES |
| Utang bank dan lembaga |  |  | Bank loans and non-bank |
| keuangan non-bank dan lainnya |  |  | financial institutions and others |
| Penerimaan - | 25.014.682 |  | Proceeds |
| Pembayaran | (21.737.236) | (5.190.568) | Payments |
| Penerimaan hasil pengalihan |  |  | Proceeds from transfer of treasury |
| saham treasuri 28 - | 39.989.426 |  | shares |
| Penerimaan dari pelaksanaan |  |  | Receipts from exercise |
| waran 29 46 | 487 |  | of warrant |
| Penerimaan (pembayaran) utang |  |  | Proceeds from (repayment of) |
| lain-lain kepada pihak berelasi | 4.455.347 | 16.931.062 | other payables to related parties |
| Setoran modal kepentingan |  |  | Capital contribution of non- |
| non pengendali entitasi anak - |  | 5.420.000 | controlling interest in subsidiary |
| Kas Neto Diperoleh dari |  |  | Net Cash Provided by |
| Aktivitas Pendanaan | 47.722.706 | 17.160.540 | Financing Activities |
| KENAIKAN (PENURUNAN) |  |  | NET INCREASE (DECREASE) IN |
| NETO KAS DAN |  |  | CASH AND CASH |
| SETARA KAS | (8.645.144) | 7.415.657 | EQUIVALENTS |
| KAS DAN SETARA KAS |  |  | CASH AND CASH EQUIVALENTS |
| AWAL TAHUN 3 8 9 | 30.318.046 | 22.902. | AT THE BEGINNING OF YEAR |
| KAS DAN SETARA KAS |  |  | CASH AND CASH EQUIVALENTS |
| AKHIR TAHUN 4 | 21.672.902 | 30.318.046 | AT THE END OF YEAR |
| Lihat Catatan 46 atas laporan keuangan konsolidasian untuk See Note 46 to the consolidated |  |  | financial statements for the |
| informasi tambahan arus kas. supplementary cash flows information. |  |  |  |
| · · Lihat Catatan atas Laporan Keuangan Konsolidasian terlampir See accompanying Notes |  |  | to the Consolidated Financial Statements |
| · yang merupakan bagian yang tidak terpisahkan dari laporan keuangan which are an integral |  |  | part of the consolidated |
| · · · · · · konsolidasian secara keseluruhan. financial statements |  |  | taken as a whole. |
| · · · · · · 7 |  |  |  |

--- PAGE 17 ---
| The original consolidated financial statements herein are in |
| Indonesian language |
| PT PERINTIS TRINITI PROPERTI Tbk PT PERINTIS TRINITI PROPERTI Tbk |
| DAN ENTITAS ANAKNYA AND ITS SUBSIDIARIES |
| CATATAN ATAS NOTES TO THE |
| LAPORAN KEUANGAN KONSOLIDASIAN CONSOLIDATED FINANCIAL STATEMENTS |
| 31 Desember 2025 December 31, 2025 |
| Dan untuk Tahun yang Berakhir pada Tanggal tersebut For the Year Ended |
| (Disajikan dalam Ribuan Rupiah, (Expressed in Thousands of Rupiah, |
| kecuali dinyatakan lain) unless otherwise stated) |
| 1. UMUM 1. GENERAL |
| a. Pendirian Perusahaan a. The Company’s Establishment |
| PT Perintis Triniti Properti Tbk (“Perusahaan”) PT Perintis Triniti Properti Tbk (the “Company”) |
| didirikan pada tanggal 13 Maret 2009 berdasarkan was established on March 13, 2009 based on |
| Akta Notaris No. 06 dari Drs. Arif Djohan Tunggal, Notarial Deed No. 06 of Drs. Arif Djohan Tunggal, |
| S.H., M.H., M.Kn., notaris d Jakarta. Akta S.H., M.H., M.Kn., notary in Jakarta. The Deed of |
| Pendirian ini telah disahkan oleh Menteri Hukum Establishment was approved by the Minister of |
| dan Hak Asasi Manusia Republik Indonesia sesuai Law and Human Rights of the Republic of |
| melalui Surat Keputusannya No. AHU- Indonesia through its Decision Letter No. AHU- |
| 21089.AH.01.01. Tahun 2009 tanggal 21089.AH.01.01. Year 2009 dated May 15, 2009. |
| 15 Mei 2009. |
| Anggaran Dasar Perusahaan telah mengalami The Company’s Article of Association have been |
| beberapa kali perubahan, terakhir berdasarkan amended several times, the most recent being |
| Akta Notaris No. 03 tanggal 2 Desember 2025 dari based on the Notarial Deed No. 03 dated |
| Lisa Sujanto, S.H., M.Kn. notaris di Tangerang December 2, 2025 from Lisa Sujanto, S.H., M.Kn. |
| Selatan, tentang perubahan Komisaris dan notary in South Tangerang, concerning the |
| Direktur. Perubahan tersebut telah diterima dan change of composition Board of Commissioners |
| dicatat pada Sistem Administrasi Badan Hukum and Directors. This amendment was accepted |
| Kementerian Hukum dan Hak Asasi Manusia and recorded in the Legal Entity Administration |
| Republik Indonesia melalui Surat No. AHU- System of the Ministry of Law and Human Rights |
| AH.01.09-0365536 tanggal 12 Desember 2025. of the Republic of Indonesia in its Letter No. AHU- |
| AH.01.09-0365536 dated December 12, 2025. |
| Sesuai dengan Pasal 3 Anggaran Dasar In accordance with Article 3 of Company’s Articles |
| Perusahaan, maksud dan tujuan serta kegiatan of Association, the Company’s business purpose |
| usaha Perusahaan berusaha dalam bidang real and activities is to engage in real estate field, |
| estat, kegiatan yang meliputi: which includes: |
| • Menjalankan usaha-usaha dibidang real estat • Perform real estate business covering |
| yang mencakup usaha pembelian, penjualan, purchase, selling, renting and operational of |
| persewaan dan pengoperasian real estat baik real estate self-owned or rented. |
| yang dimiliki sendiri maupun disewa. |
| • Kegiatan penjualan tanah, pengembangan • Activities in land selling, building development |
| gedung untuk dioperasikan sendiri, for own operated, divide real estate become |
| pembagian real estat menjadi tanah kapling kavling land without land development and |
| tanpa pengembangan lahan dan living area operation. |
| pengoperasian kawasan tempat tinggal. |
| Entitas induk Perusahaan yaitu PT Kunci Daud The Company's parent entity is PT Kunci Daud |
| Indonesia dan entitas induk terakhir yaitu Indonesia and the ultimate parent entity is |
| PT Mahkota Daud Indonesia. PT Mahkota Daud Indonesia. |
| Kantor pusat Perusahaan berlokasi di Premium The Company’s head office is in Premium Office |
| Office No.1-3, Jl. Sutera Boulevard kav. 22-26, No.1-3, Jl. Sutera Boulevard kav. 22-26, South |
| Tangerang Selatan, Banten. Perusahaan mulai Tangerang, Banten. The Company started its |
| beroperasi secara komersial pada tahun 2009. commercial operations in 2009. |
| 8 |

--- PAGE 18 ---
| The original consolidated financial statements herein are in |
| Indonesian language |
| PT PERINTIS TRINITI PROPERTI Tbk PT PERINTIS TRINITI PROPERTI Tbk |
| DAN ENTITAS ANAKNYA AND ITS SUBSIDIARIES |
| CATATAN ATAS NOTES TO THE |
| LAPORAN KEUANGAN KONSOLIDASIAN CONSOLIDATED FINANCIAL STATEMENTS |
| 31 Desember 2025 December 31, 2025 |
| Dan untuk Tahun yang Berakhir pada Tanggal tersebut For the Year Ended |
| (Disajikan dalam Ribuan Rupiah, (Expressed in Thousands of Rupiah, |
| kecuali dinyatakan lain) unless otherwise stated) |
| 1. UMUM (Lanjutan) 1. GENERAL (continued) |
| b. Dewan Komisaris dan Direksi, Komite Audit b. Board of Commissioners and Directors, |
| Sekretaris Perusahaan, Audit Internal, serta Audit Committee, Corporate Secretary, |
| Karyawan Internal Audit, and Employees |
| Pada tanggal 31 Desember 2025 dan As of December 31, 2025 and 2024, the |
| 2024 susunan Dewan Komisaris dan Direksi composition of the Board of Commissioners |
| Perusahaan adalah sebagai berikut: and Directors, are as follows: |
| 2025 2024 |
| Dewan Komisaris Board of Commissioners |
| Komisaris Utama : Rahayu Septian Starlin : President Commissioner |
| Saraswati |
| Djojohadikusumo |
| Komisaris : Septian Starlin Matius Jusuf : Commissioner |
| Matius Jusuf - |
| Komisaris Independen : Hery Susanto Erman Suparno : Independent Commissioner |
| Rachmad |
| Dewan Direksi Directors |
| Direktur Utama : Ishak Chandra Ishak Chandra : President Director |
| Direktur : Chandra Chandra : Director |
| Johanes L.A Johanes L.A |
| Gregorius Danny |
| Seloko Uyanto Sutradewa |
| Susunan Komite Audit Perusahaan pada tanggal The composition of the Company’s Audit |
| 31 Desember 2025 dan 2024 adalah sebagai Committee as of December 31, 2025 and 2024 |
| berikut: was as follows: |
| 2025 2024 |
| Komite Audit Audit Committee |
| Ketua : Henry Susanto Erman Suparno : Chairman |
| Anggota : Yohanes Eddy : |
| Gregorius S.U Member |
| Christianto |
| Anggota : Richard Yovann Richard Yovann Member |
| : |
| Sekertaris Perusahaan Fiolita |
| Riska Afriani Corporate Secretary |
| : Nurfitriyana |
| Audit Internal : Kian Yui Kian Yui Internal Audit |
| Jumlah karyawan tetap Perusahaan dan entitas The Group had total number of permanent |
| anaknya masing-masing sebanyak 88 dan employees of 88 and 144 as of December 31, |
| 144 orang per 31 Desember 2025 dan 2024 (tidak 2025 and 2024, respectively (unaudited). |
| diaudit). |
| 9 |

--- PAGE 19 ---
| Keterangan | kolom 1 | kolom 2 | English |
|---|---|---|---|
| · · · · · · The original consolidated financial statements herein are in |  |  |  |
| · · · · · · Indonesian language |  |  |  |
| · · · · PT PERINTIS TRINITI PROPERTI Tbk PT PERINTIS TRINITI PROPERTI Tbk |  |  |  |
| · · · · · · DAN ENTITAS ANAKNYA AND ITS SUBSIDIARIES |  |  |  |
| · · · · · · CATATAN ATAS NOTES TO THE |  |  |  |
| · · · LAPORAN KEUANGAN KONSOLIDASIAN CONSOLIDATED FINANCIAL STATEMENTS |  |  |  |
| · · · · · · 31 Desember 2025 December 31, 2025 |  |  |  |
| Dan untuk Tahun yang Berakhir pada Tanggal tersebut For the Year Ended |  |  |  |
| · · · · · (Disajikan dalam Ribuan Rupiah, (Expressed in Thousands of Rupiah, |  |  |  |
| · · · · · · kecuali dinyatakan lain) unless otherwise stated) |  |  |  |
| 1. UMUM (lanjutan) 1. GENERAL (continued) |  |  |  |
| · · c. Entitas Anak c. Subsidiaries |  |  |  |
| · · · · Pada tanggal 31 Desember 2025 dan 2024, rincian As of December 31, 2025 and the details | 2024, |  |  |
| · · · · Entitas Anak yang dikonsolidasikan adalah of the consolidated subsidiaries are as follows: |  |  |  |
| · · · · sebagai berikut: |  |  |  |
| · · · · · · Persentase Total Aset |  |  |  |
| · · · · · · Tahun Beroperasi Kepemilikan Efektif / Sebelum Eliminasi / |  |  |  |
| · · · · · · Percentage of Total Assets |  |  |  |
| · · · · · · Tempat Komersial / |  |  |  |
| · · · · · Entitas Anak / Kedudukan / Bidang Usaha / Commercial Effective Ownership Before Elimination |  |  |  |
| · · · · · Subsidiaries Location Business Activities Operating Year 2025 2024 | 2025 | 2024 |  |
| · · · · Kepemilikan Langsung / Direct Ownership |  |  |  |
| · · · · · · Real estat yang dimiliki |  |  |  |
| · · · · · · sendiri atau disewa / |  |  |  |
| · · · · PT Sirius Terang Owned or leased real |  |  |  |
| · · · · · Cemerlang (“STC”) Tangerang estate 2015 99,20% 99,20% | 136.399.960 | 121.765.859 |  |
| · · · · · · Pembangunan, |  |  |  |
| · · · · · · Perdagangan dan Jasa/ |  |  |  |
| · · · · PT Triniti Pilar Gemilang Development, Trade and |  |  |  |
| · · · · (“TPG”) Tangerang Service 2013 99,99% 99,92% | 32.805.509 | 70.636.141 |  |
| · · · · · · Real estat yang dimiliki |  |  |  |
| · · · · · · sendiri atau disewa / |  |  |  |
| · · · · PT Triniti Menara Serpong Owned or leased real |  |  |  |
| · · · · (“TMS) Tangerang estate 2017 50,00% 50,00% | 1.095.849.016 | 984.656.386 |  |
| · · · · · · Real estat yang dimiliki |  |  |  |
| · · · · · · sendiri atau disewa / |  |  |  |
| · · · · PT Triniti Menara Gading Owned or leased real Pra-Operasi/ |  |  |  |
| · · · · (“TMG”) Tangerang estate Pre-Operating 99,99% 99,99% | 103.303.577 | 98.724.781 |  |
| · · · · · · Real estat yang dimiliki |  |  |  |
| · · · · · · sendiri atau disewa / |  |  |  |
| · · · · PT Puri Triniti Batam Owned or leased real |  |  |  |
| · · · · · · estate |  |  |  |
| · · · · (“PTB”) Batam 2018 70,00% 70,00% | 169.124.642 | 168.420.493 |  |
| · · · · · · Real estat yang dimiliki |  |  |  |
| · · · · · · sendiri atau disewa / |  |  |  |
| · · · · PT Triniti Garam Properti Owned or leased real |  |  |  |
| · · · · (“TGP”)* Jakarta estate 2021 - 65,00% - |  | 216.837.850 |  |
| · · · · · · Real estat yang dimiliki |  |  |  |
| · · · · PT Tanamori Makmur sendiri atau disewa / |  |  |  |
| · · · · Indonesia Owned or leased real |  |  |  |
| · · · · (“TMI”) Labuan Bajo estate 2019 51,00% 51,00% | 17.806.743 | 18.520.697 |  |
| · · · · *) Perusahaan telah kehilangan pengendalian atas entitas anak *) The Company has lost its control of a subsidiary PT Triniti |  |  |  |
| · · · · · PT Triniti Garam Properti (“TGP”) pada September 2025. Garam Properti (“TGP”) in September | 2025. |  |  |
| · · · · Pelepasan Entitas Anak Divestment of Subsidiaries |  |  |  |
| · · · · PT Triniti Garam Properti (“TGP”) PT Triniti Garam Properti (“TGP”) |  |  |  |
| · · · · Kepemilikan Perusahaan di TGP sebesar 65%, The Company’s ownership interest in TGP |  |  |  |
| · · · · setara 6.500 lembar saham dengan nilai represents 65%, equivalent to shares of | 6,500 |  |  |
| · · · · Rp 325.000. per lembar saham. stock with Rp 325,000 par value per share. |  |  |  |
| · · · · Berdasarkan Rapat Umum Pemegang Saham Based on Extraordinary General Meeting dated |  |  |  |
| · · · · Luar Biasa pada tanggal 25 September 2025, September 25, 2025, the Company’s |  |  |  |
| · · · · pemegang saham Perusahaan menyetujui shareholders approved transfer of |  | 6,500 |  |
| · · · · pengalihan saham sebanyak 6.500 saham milik shares owned by the Company to PT Sequoia |  |  |  |
| · · · · Perusahaan kepada PT Sequoia Tumbuh Tumbuh Sejahtera with nominal values of each |  |  |  |
| · · · · Sejahtera dengan nilai nominal setiap saham share of Rp 325,000. |  |  |  |
| · · · · sebesar Rp 325.000. |  |  |  |
| · · · · · · 10 |  |  |  |

--- PAGE 20 ---
| Keterangan | 31 Desember 2025 December 31, 2025 | English |
|---|---|---|
|  |  | The original consolidated financial statements herein are in |
|  |  | Indonesian language |
| · · · · PT PERINTIS TRINITI PROPERTI Tbk |  | PT PERINTIS TRINITI PROPERTI Tbk |
| · · · · · · DAN ENTITAS ANAKNYA |  | AND ITS SUBSIDIARIES |
| · · · · · · CATATAN ATAS |  | NOTES TO THE |
| · · · LAPORAN KEUANGAN KONSOLIDASIAN CONSOLIDATED |  | FINANCIAL STATEMENTS |
| · · · · · · 31 Desember 2025 |  | December 31, 2025 |
| Dan untuk Tahun yang Berakhir pada Tanggal tersebut |  | For the Year Ended |
| · · · · · (Disajikan dalam Ribuan Rupiah, |  | (Expressed in Thousands of Rupiah, |
| · · · · · · kecuali dinyatakan lain) |  | unless otherwise stated) |
| 1. UMUM (lanjutan) 1. GENERAL |  | (continued) |
| · · c. Entitas Anak (lanjutan) c. |  | Subsidiaries (continued) |
| · · · · Pelepasan Entitas Anak (lanjutan) |  | Divestment of Subsidiaries (continued) |
| · · · · PT Triniti Garam Properti (“TGP”) (lanjutan) |  | PT Triniti Garam Properti (“TGP”) |
|  |  | (continued) |
| · · · · Berikut perhitungan keuntungan penjualan entitas |  | The following calculation in gain on disposal of |
| · · · · anak: |  | subsidiary: |
| · · · · Harga Jual | 325.000 | Selling price |
| · · · · Dikurangi: |  | Less: |
| · · · · · Nilai tercatat aset neto | 65.148.530 | Carrying value of net assets |
| · · · · · Kepentingan nonpengendali |  | Non-controlling interest |
| · · · · · (Catatan 31) | (22.781.467) | (Note 31) |
| · · · · Keuntungan penjualan entitas anak |  | Gain on disposal of a subsidiary |
| · · · · · (Catatan 37) | 42.692.063 | (Note 37) |
| · · · · Dampak Akuisisi Entitas Anak |  | Impact of the Acquisition of a Subsidiary |
| · · · · PT Tanamori Makmur Indonesia |  | PT Tanamori Makmur Indonesia |
| · · · · Pada tanggal 3 Januari 2024, Perusahaan telah |  | On January 3, 2024, the Company has |
| · · · · efektif meningkatkan tambahan 2% kepemilikan di |  | effectively increased additional 2% ownership |
| · · · · PT Tanamori Makmur Indonesia atau setara |  | in PT Tanamori Makmur Indonesia or |
| · · · · dengan 100.775.000 lembar saham, dan |  | equivalent to 100,775,000 shares, and |
| · · · · memperoleh pengendalian atas PT Tanamori |  | obtained control over PT Tanamori Makmur |
| · · · · Makmur Indonesia. Sebelumnya Perusahaan |  | Indonesia. Previously, the Company owned |
| · · · · memiliki 49% saham dan mencatatnya sebagai |  | 49% shares and recorded it as investment in |
| · · · · investasi pada entitas asosiasi. |  | associate entity. |
| · · d. Penawaran Umum Efek Perusahaan d. |  | Public Offering of Share and Bonds of the |
|  |  | Company |
| · · · · Saham |  | Share |
| · · · · Pada tanggal 30 Desember 2019, Perusahaan |  | On December 30, 2019, the Company |
| · · · · memperoleh pernyataan efektif dari Otoritas Jasa |  | obtained the notice of effectivity from the |
| · · · · Keuangan (“OJK”) dengan suratnya |  | Financial Services Authority of Indonesia |
| · · · · No. S-207/D.04/2019 untuk melakukan |  | (“OJK”) in its letter No. S-207/D.04/2019 for its |
| · · · · penawaran umum perdana 648.833.400 lembar |  | public offering of 648,833,400 shares. On |
| · · · · saham kepada masyarakat. Pada tanggal 15 |  | January 15, 2020, the shares were listed on the |
| · · · · Januari 2020, saham tersebut telah dicatatkan |  | Indonesia Stock Exchange (“BEI”). |
| · · · · pada Bursa Efek Indonesia (“BEI”). |  |  |
| · · · · Pada tanggal 15 Januari 2020, 3.280.000.000 |  | On January 15, 2020, 3,280,000,000 shares |
| · · · · lembar saham Perusahaan milik pemegang |  | owned by the founding stockholders were listed |
| · · · · saham pendiri telah tercatat pada Bursa Efek |  | in the Indonesia Stock Exchange. |
| · · · · Indonesia. |  |  |
| · · · · Pada tanggal 19 Desember 2022, Perusahaan |  | On December 19, 2022, the Company obtained |
| · · · · memperoleh Pernyataan Efektif dari Otoritas Jasa |  | an Effective Statement from the Financial |
| · · · · Keuangan (OJK) dengan Surat No. S- |  | Services Authority (OJK) with Letter No. S- |
| · · · · 270/D.04/2022 untuk melakukan Penawaran |  | 270/D.04/2022 to conduct Limited Public |
|  |  | Offering I for additional Capital with Pre- |
| · · · · Umum Terbatas I untuk Penambahan Modal |  |  |
| · · · · Dengan Hak Memesan Efek Terlebih Dahulu. |  | emptive Rights. |
| · · · · · · 11 |  |  |

--- PAGE 21 ---
| The original consolidated financial statements herein are in |
| Indonesian language |
| PT PERINTIS TRINITI PROPERTI Tbk PT PERINTIS TRINITI PROPERTI Tbk |
| DAN ENTITAS ANAKNYA AND ITS SUBSIDIARIES |
| CATATAN ATAS NOTES TO THE |
| LAPORAN KEUANGAN KONSOLIDASIAN CONSOLIDATED FINANCIAL STATEMENTS |
| 31 Desember 2025 December 31, 2025 |
| Dan untuk Tahun yang Berakhir pada Tanggal tersebut For the Year Ended |
| (Disajikan dalam Ribuan Rupiah, (Expressed in Thousands of Rupiah, |
| kecuali dinyatakan lain) unless otherwise stated) |
| 1. UMUM (lanjutan) 1. GENERAL (continued) |
| d. Penawaran Umum Efek Perusahaan d. Public Offering of Share and Bonds of the |
| (lanjutan) Company (continued) |
| Obligasi Konversi Convertible Bonds |
| Pada 25 Maret 2019 dan 28 Oktober 2019, On March 25, 2019 and October 28, 2019, the |
| Perusahaan menerbitkan Mandatory Convertible Company issued Mandatory Convertible Bonds |
| Bonds (“MCB”) masing-masing sebesar (“MCB”) in the amount of Rp 13,200,000 and |
| Rp 13.200.000 dan Rp 36.000.000. Rp 36,000,000, respectively. |
| Pada 17 Desember 2018, Perusahaan On December 17, 2018, the Company issued |
| menerbitkan Mandatory Convertible Bonds Mandatory Convertible Bonds (“MCB”) |
| (“MCB”) sebesar Rp 39.700.000. Penerbitan MCB amounting to Rp 39,700,000. Issuance of MCB |
| dilakukan sesuai dengan Perjanjian Perusahaan is carried out in accordance with the Company |
| (Penerbit) dan Masyarakat (Pembeli). (Publisher) and Community (Buyer) |
| Agreement. |
| Pada tanggal 15 Januari 2020, seluruh MCB telah On January 15, 2020, all MCB have been |
| dikonversikan menjadi 444.500.000 lembar saham converted into 444,500,000 public shares with |
| publik dengan nilai konversi sebesar the conversion value of Rp 44,450,000. |
| Rp 44.450.000. |
| e. Penerbitan Laporan Keuangan Konsolidasian e. Issuance of the Consolidated Financial |
| Statements |
| Manajemen Perusahaan bertanggung jawab atas The management of the Company is |
| penyusunan laporan keuangan konsolidasian ini responsible of the preparation of these |
| yang telah disetujui oleh Direksi untuk diterbitkan consolidated financial statements that have |
| pada tanggal 31 Maret 2026. been authorized for issue by the Directors on |
| March 31, 2026. |
| 2. INFORMASI KEBIJAKAN AKUNTANSI MATERIAL 2. MATERIAL ACCOUNTING POLICY |
| INFORMATION |
| a. Kepatuhan terhadap Standar Akuntansi a. Compliance with Financial Accounting |
| Keuangan (“SAK”) Standards (“SAK”) |
| Laporan keuangan konsolidasian Perusahaan dan The consolidated financial statements of the |
| entitas anaknya (bersama-sama disebut sebagai Company and its subsidiaries (together referred |
| “Grup”) telah disusun dan disajikan sesuai dengan as "the Group") have been prepared and |
| SAK di Indonesia yang meliputi Pernyataan presented in accordance with Indonesian SAK |
| Standar Akuntansi Keuangan (“PSAK”) dan which comprise of the Statements of Financial |
| Interpretasi Standar Akuntansi Keuangan (“ISAK”) Accounting Standards (“PSAK”) and the |
| yang diterbitkan oleh Dewan Standar Akuntansi Interpretation of Financial Accounting |
| Keuangan - Ikatan Akuntan Indonesia (“DSAK- Standards (“ISAK”) issued by Financial |
| IAI”), serta Peraturan No. VIII.G.7 yang diterbitkan Accounting Standards Board of the Institute of |
| oleh BAPEPAM-LK, tentang Penyajian dan Indonesia Chartered Accountants (“DSAK-IAI”), |
| Pengungkapan Laporan Keuangan Emiten atau and BAPEPAMLK Regulation No. VIII.G.7 |
| Perusahaan Publik, yang terlampir dalam surat regarding the Presentations and Disclosures of |
| keputusan No. KEP-347/BL/2012 dari Ketua Financial Statements of listed entity, enclosed in |
| BAPEPAM-LK tanggal 25 Juni 2012. the decision letter No. KEP-347/BL/2012 of |
| Chairman of BAPEPAM-LK dated June 25, |
| 2012. |
| 12 |

--- PAGE 22 ---
| The original consolidated financial statements herein are in |
| Indonesian language |
| PT PERINTIS TRINITI PROPERTI Tbk PT PERINTIS TRINITI PROPERTI Tbk |
| DAN ENTITAS ANAKNYA AND ITS SUBSIDIARIES |
| CATATAN ATAS NOTES TO THE |
| LAPORAN KEUANGAN KONSOLIDASIAN CONSOLIDATED FINANCIAL STATEMENTS |
| 31 Desember 2025 December 31, 2025 |
| Dan untuk Tahun yang Berakhir pada Tanggal tersebut For the Year Ended |
| (Disajikan dalam Ribuan Rupiah, (Expressed in Thousands of Rupiah, |
| kecuali dinyatakan lain) unless otherwise stated) |
| 2. INFORMASI KEBIJAKAN AKUNTANSI MATERIAL 2. MATERIAL ACCOUNTING POLICY |
| (lanjutan) INFORMATION (continued) |
| b. Dasar Pengukuran dalam Penyusunan b. Basis Measurement in Preparation of the |
| Laporan Keuangan Konsolidasian Consolidated Financial Statements |
| Laporan keuangan konsolidasian disusun The consolidated financial statements have |
| berdasarkan asumsi kelangsungan usaha serta been prepared on the assumption of going |
| atas dasar akrual, kecuali laporan arus kas concern and accrual basis except for |
| konsolidasian yang menggunakan dasar kas. consolidated statement of cash flows using |
| cash basis. |
| Laporan keuangan konsolidasian, kecuali laporan The consolidated financial statements, except |
| arus kas konsolidasian, telah disusun secara for the consolidated statement of cash flows, |
| akrual dengan menggunakan konsep biaya have been prepared based on the accrual basis |
| perolehan (historical cost), kecuali untuk akun- using the historical cost concept of accounting, |
| akun tertentu yang diukur berdasarkan basis lain except for certain accounts which are measured |
| seperti yang dijelaskan dalam kebijakan akuntansi on the basis described in the related accounting |
| terkait. policies. |
| Laporan arus kas konsolidasian disusun dengan The consolidated statement of cash flows are |
| menggunakan metode langsung, dan prepared using the direct method, and classified |
| dikelompokkan ke dalam aktivitas operasi, into operating, investing and financing activities. |
| investasi dan pendanaan. |
| Kebijakan akuntansi yang digunakan dalam The accounting policies adopted in the |
| penyusunan laporan keuangan konsolidasian preparation of the consolidated financial |
| konsisten dengan yang digunakan dalam statements are consistent with those adopted in |
| penyusunan laporan keuangan konsolidasian the preparation of the consolidated financial |
| untuk tahun yang berakhir pada tanggal statements for the year ended December 31, |
| 31 Desember 2024, kecuali untuk penerapan 2024, except for the adoption of revised PSAK |
| PSAK yang direvisi yang berlaku efektif pada effective January 1, 2025 as disclosed in this |
| tanggal 1 Januari 2025 seperti yang diungkapkan Note. |
| dalam Catatan ini. |
| Penyusunan laporan keuangan konsolidasian The preparation of consolidated financial |
| sesuai dengan SAK di Indonesia mengharuskan statements in conformity with Indonesian SAK |
| manajemen untuk membuat pertimbangan, requires management to make judgment, |
| estimasi dan asumsi yang memengaruhi estimates and assumptions that affect the |
| penerapan kebijakan akuntansi dan jumlah aset, application of accounting policies and the |
| liabilitas, pendapatan dan beban yang dilaporkan. reported amounts of assets, liabilities, income |
| Walaupun estimasi ini dibuat berdasarkan and expenses. Although these estimates are |
| pengetahuan terbaik manajemen dan based on management’s best knowledge and |
| pertimbangan atas kejadian dan tindakan saat ini, judgment of current events and actions, actual |
| hasil yang sebenarnya mungkin berbeda dari results may ultimately differ from those |
| jumlah yang diestimasi. Hal-hal yang melibatkan estimates. The areas involving a higher degree |
| pertimbangan atau kompleksitas yang lebih tinggi of judgment or complexity, or areas where |
| atau hal-hal dimana asumsi dan estimasi adalah assumptions and estimates are significant to |
| signifikan terhadap laporan keuangan the consolidated financial statements are |
| konsolidasian diungkapkan dalam Catatan 3 atas disclosed in Note 3 to the consolidated financial |
| laporan keuangan konsolidasian. statements. |
| 13 |

--- PAGE 23 ---
| The original consolidated financial statements herein are in |
| Indonesian language |
| PT PERINTIS TRINITI PROPERTI Tbk PT PERINTIS TRINITI PROPERTI Tbk |
| DAN ENTITAS ANAKNYA AND ITS SUBSIDIARIES |
| CATATAN ATAS NOTES TO THE |
| LAPORAN KEUANGAN KONSOLIDASIAN CONSOLIDATED FINANCIAL STATEMENTS |
| 31 Desember 2025 December 31, 2025 |
| Dan untuk Tahun yang Berakhir pada Tanggal tersebut For the Year Ended |
| (Disajikan dalam Ribuan Rupiah, (Expressed in Thousands of Rupiah, |
| kecuali dinyatakan lain) unless otherwise stated) |
| 2. INFORMASI KEBIJAKAN AKUNTANSI MATERIAL 2. MATERIAL ACCOUNTING POLICY |
| (lanjutan) INFORMATION (continued) |
| b. Dasar Pengukuran dalam Penyusunan b. Basis Measurement in Preparation of the |
| Laporan Keuangan Konsolidasian (lanjutan) Consolidated Financial Statements |
| (continued) |
| Mata uang pelaporan yang digunakan dalam The reporting currency used in the preparation |
| laporan keuangan konsolidasian adalah Rupiah of the consolidated financial statements is |
| atau Rp yang juga merupakan mata uang Rupiah or Rp which also represents functional |
| fungsional Grup. currency of the Group. |
| Penerapan PSAK yang Direvisi Adoption of Revised PSAK |
| Grup telah menerapkan PSAK yang direvisi, yang The Group adopted the following revised PSAK |
| berlaku efektif 1 Januari 2025: that are mandatory for application effective |
| January 1, 2025: |
| • Amendemen PSAK 221: Pengaruh • Amendments to PSAK 221: The Effects of |
| Perubahan Kurs Valuta Asing - Kekurangan Changes in Foreign Exchanges Rates - |
| Ketertukaran Lack of Exchangeability |
| Penerapan standar yang direvisi tidak The adoption of the revised standards did not |
| mengakibatkan perubahan substansial terhadap result in substantial changes to the Group’s |
| kebijakan akuntansi Grup dan tidak memiliki accounting policies and had no material effect |
| dampak material terhadap jumlah yang dilaporkan |
| untuk tahun berjalan. |
| c. Dasar Konsolidasian c. Basis of Consolidation |
| Entitas anak adalah seluruh entitas dimana Grup Subsidiaries are all entities over which the |
| memiliki pengendalian. Grup mengendalikan Group has control. The Group controls an |
| investee ketika (a) memiliki kekuasaan atas investee when the Group (a) has power over the |
| investee, (b) eksposur atau hak atas imbal hasil investee, (b) is exposed, or has rights, to |
| variabel dari keterlibatannya dengan investee, variable returns from its involvement with the |
| dan (c) memiliki kemampuan untuk investee, and (c) has the ability to use its power |
| menggunakan kekuasaannya atas investee over the investee to affect its returns. The Group |
| untuk memengaruhi jumlah imbal hasil. Grup re-assesses whether or not it controls an |
| menilai kembali apakah Grup mengendalikan investee if facts and circumstances indicate that |
| investee jika fakta dan keadaan mengindikasikan there are changes to one or more of the three |
| adanya perubahan terhadap satu atau lebih dari elements of control. |
| tiga elemen pengendalian. |
| Konsolidasi atas entitas anak dimulai sejak Consolidation of a subsidiary begins when the |
| tanggal Grup memperoleh pengendalian atas Group obtains control over the subsidiary and |
| ceases when the Group loses control of the |
| entitas anak dan berakhir ketika Grup kehilangan |
| pengendalian atas entitas anak. Penghasilan dan subsidiary. Income and expenses of a |
| beban entitas anak dimasukkan atau dilepaskan subsidiary acquired or disposed of during the |
| selama tahun berjalan dalam laba rugi dari year are included in the profit or loss from the |
| tanggal diperolehnya pengendalian sampai date the Group gains control until the date the |
| dengan tanggal ketika Grup kehilangan Group ceases to control the subsidiary. |
| pengendalian atas entitas anak. |
| 14 |

--- PAGE 24 ---
| The original consolidated financial statements herein are in |
| Indonesian language |
| PT PERINTIS TRINITI PROPERTI Tbk PT PERINTIS TRINITI PROPERTI Tbk |
| DAN ENTITAS ANAKNYA AND ITS SUBSIDIARIES |
| CATATAN ATAS NOTES TO THE |
| LAPORAN KEUANGAN KONSOLIDASIAN CONSOLIDATED FINANCIAL STATEMENTS |
| 31 Desember 2025 December 31, 2025 |
| Dan untuk Tahun yang Berakhir pada Tanggal tersebut For the Year Ended |
| (Disajikan dalam Ribuan Rupiah, (Expressed in Thousands of Rupiah, |
| kecuali dinyatakan lain) unless otherwise stated) |
| 2. INFORMASI KEBIJAKAN AKUNTANSI MATERIAL 2. MATERIAL ACCOUNTING POLICY |
| (lanjutan) INFORMATION (continued) |
| c. Dasar Konsolidasian (lanjutan) c. Basis of Consolidation (continued) |
| Laba rugi dan setiap komponen dari penghasilan Profit or loss and each component of other |
| komprehensif lain diatribusikan kepada pemilik comprehensive income are attributed to owners |
| entitas induk dan kepentingan nonpengendali, of the parent entity and to the non-controlling |
| meskipun hal tersebut mengakibatkan interests, even if this results in the non- |
| kepentingan nonpengendali memiliki saldo defisit. controlling interests having a deficit balance. |
| Jika diperlukan, dilakukan penyesuaian atas When necessary, adjustments are made to the |
| laporan keuangan entitas anak guna memastikan financial statements of subsidiaries to bring their |
| keseragaman dengan kebijakan akuntansi Grup. accounting policies into line with the Group’s |
| Mengeliminasi secara penuh aset dan liabilitas, accounting policies. All intra-group assets and |
| penghasilan, beban, dan arus kas dalam intra liabilities, equity, income, expenses and cash |
| kelompok usaha terkait dengan transaksi antar flows relating to transactions between members |
| entitas dalam Grup. of the Group are eliminated in full on |
| consolidation. |
| Perubahan dalam bagian kepemilikan atas entitas A change in the ownership interest of a |
| anak yang tidak mengakibatkan hilangnya subsidiary, without a loss of control, is |
| pengendalian pada entitas anak dicatat sebagai accounted for as an equity transaction. Any |
| transaksi ekuitas. Setiap perbedaan antara jumlah difference between the amount by which the |
| tercatat kepentingan nonpengendali yang non-controlling interests are adjusted and the |
| disesuaikan dan nilai wajar imbalan yang dibayar fair value of the consideration paid or received |
| atau diterima diakui secara langsung di ekuitas is recognized directly in equity and attributed to |
| dan mengatribusikannya kepada pemilik entitas owners of the parent. |
| induk. |
| Ketika Grup kehilangan pengendalian pada If the Group losses control over a subsidiary, it |
| entitas anak, maka Grup menghentikan derecognises the related assets (including |
| pengakuan atas aset (termasuk goodwill), goodwill), liabilities, non-controlling interest and |
| liabilitas dan komponen lain dari ekuitas terkait, other components of equity while any resulting |
| sementara keuntungan atau kerugian yang gain or loss is recognized in profit or loss. Any |
| dihasilkan diakui pada laba rugi. Bagian dari investment retained is recognized at fair value. |
| investasi yang tersisa diakui pada nilai wajar. |
| d. Kombinasi Bisnis d. Business Combination |
| Grup menerapkan metode akuisisi untuk The Group uses the acquisition method of |
| mencatat kombinasi bisnis. Imbalan yang accounting to account for business |
| dialihkan untuk akuisisi suatu entitas anak adalah combinations. The consideration transferred for |
| sebesar nilai wajar aset yang dialihkan, liabilitas the acquisition of a subsidiary is the fair value of |
| yang diambil alih dan kepentingan ekuitas yang the assets transferred, the liabilities incurred and |
| diterbitkan oleh Grup. Beban akuisisi terkait the equity interest issued by the Group. |
| dibebankan pada saat terjadinya. Aset Acquisition-related costs are expensed as |
| teridentifikasi yang diperoleh dan liabilitas serta incurred. Identifiable assets acquired and |
| liabilitas kontinjensi yang diambil alih dalam suatu liabilities and contingent liabilities assumed in a |
| kombinasi bisnis diukur pada awalnya sebesar business combination are measured initially at |
| nilai wajar pada tanggal akuisisi. their fair value at the acquisition date. |
| 15 |

--- PAGE 25 ---
| The original consolidated financial statements herein are in |
| Indonesian language |
| PT PERINTIS TRINITI PROPERTI Tbk PT PERINTIS TRINITI PROPERTI Tbk |
| DAN ENTITAS ANAKNYA AND ITS SUBSIDIARIES |
| CATATAN ATAS NOTES TO THE |
| LAPORAN KEUANGAN KONSOLIDASIAN CONSOLIDATED FINANCIAL STATEMENTS |
| 31 Desember 2025 December 31, 2025 |
| Dan untuk Tahun yang Berakhir pada Tanggal tersebut For the Year Ended |
| (Disajikan dalam Ribuan Rupiah, (Expressed in Thousands of Rupiah, |
| kecuali dinyatakan lain) unless otherwise stated) |
| 2. INFORMASI KEBIJAKAN AKUNTANSI MATERIAL 2. MATERIAL ACCOUNTING POLICY |
| (lanjutan) INFORMATION (continued) |
| d. Kombinasi Bisnis (lanjutan) d. Business Combination (continued) |
| Setiap imbalan kontinjensi yang dialihkan oleh Any contingent consideration to be transferred |
| pihak pengakuisisi diakui pada nilai wajar pada by the acquirer will be recognized at fair value at |
| tanggal akuisisi. Imbalan kontinjensi yang the acquisition date. Contingent consideration |
| diklasifikasikan sebagai aset atau liabilitas yang classified as an asset or liability that is a financial |
| merupakan instrumen keuangan dan termasuk instrument and within the scope of PSAK 109: |
| dalam ruang lingkup PSAK 109: Instrumen Financial Instruments, is measured at fair value |
| Keuangan diukur pada nilai wajar dengan with the changes in fair value recognized either |
| perubahan pada nilai wajar diakui baik dalam laba in profit or loss or other comprehensive income. |
| rugi atau penghasilan komprehensif lain. Jika If the contingent consideration is not within the |
| imbalan kontinjensi tidak termasuk dalam ruang scope of PSAK 109, it is measured in |
| lingkup PSAK 109 diukur dengan PSAK yang accordance with the appropriate PSAK. |
| sesuai. Imbalan kontinjensi yang diklasifikasikan Contingent consideration classified as equity is |
| sebagai ekuitas tidak diukur kembali dan not remeasured and subsequent settlement is |
| penyelesaian selanjutnya dicatat dalam ekuitas. accounted for within equity. |
| Pada akuisisi bertahap, Grup mengakui On an acquisition-by-acquisition basis, the |
| kepentingan nonpengendali sebesar nilai wajar Group recognizes any non-controlling interest |
| atau sebesar bagian proporsional kepentingan in the acquiree either at fair value or at the non- |
| nonpengendali atas aset neto pihak yang controlling interest’s proportionate share of the |
| diakuisisi. acquiree’s net assets. |
| Selisih lebih nilai agregat dari imbalan yang The excess of the aggregate of the |
| dialihkan, jumlah kepentingan nonpengendali consideration transferred, the amount of any |
| pada pihak yang diakuisisi dan nilai wajar pada non-controlling interest in the acquiree and the |
| tanggal akuisisi dari kepentingan ekuitas acquisition-date fair value of any previous |
| sebelumnya pada pihak yang diakuisisi yang equity interest in the acquiree over the fair |
| melebihi nilai wajar bagian Grup atas aset bersih value of the Group’s share of the identifiable |
| yang dapat diidentifikasi yang diakuisisi dicatat net assets acquired is recorded as goodwill. If |
| sebagai goodwill. Jika nilai wajar atas aset neto the fair value of the net assets acquired is in |
| yang diakuisisi melebihi nilai gabungan imbalan excess of the aggregate consideration |
| yang dialihkan dalam kasus pembelian dengan transferred in the case of a bargain purchase, |
| diskon, maka selisih tersebut diakui langsung the difference is recognized directly in profit or |
| dalam laba rugi. loss. |
| Setelah pengakuan awal, goodwill diukur pada After initial recognition, goodwill is measured at |
| biaya perolehan dikurangi akumulasi rugi cost less any accumulated impairment losses. |
| penurunan nilai. Untuk tujuan pengujian For the purpose of impairment testing, goodwill |
| penurunan nilai, goodwill yang diperoleh dari suatu acquired in a business combination, from the |
| kombinasi bisnis, sejak tanggal akuisisi, acquisition date, allocated to each of the |
| dialokasikan ke setiap unit penghasil kas dari Grup Group’s cash-generating units that are |
| yang diharapkan bermanfaat untuk kombinasi expected to benefit from the combination, |
| tersebut, terlepas dari apakah aset atau liabilitas irrespective of whether other assets or |
| lain dari pihak yang diakuisisi ditetapkan ke unit- liabilities of the acquiree are assigned to those |
| unit tersebut. units. |
| 16 |

--- PAGE 26 ---
| The original consolidated financial statements herein are in |
| Indonesian language |
| PT PERINTIS TRINITI PROPERTI Tbk PT PERINTIS TRINITI PROPERTI Tbk |
| DAN ENTITAS ANAKNYA AND ITS SUBSIDIARIES |
| CATATAN ATAS NOTES TO THE |
| LAPORAN KEUANGAN KONSOLIDASIAN CONSOLIDATED FINANCIAL STATEMENTS |
| 31 Desember 2025 December 31, 2025 |
| Dan untuk Tahun yang Berakhir pada Tanggal tersebut For the Year Ended |
| (Disajikan dalam Ribuan Rupiah, (Expressed in Thousands of Rupiah, |
| kecuali dinyatakan lain) unless otherwise stated) |
| 2. INFORMASI KEBIJAKAN AKUNTANSI MATERIAL 2. MATERIAL ACCOUNTING POLICY |
| (lanjutan) INFORMATION (continued) |
| d. Kombinasi Bisnis (lanjutan) d. Business Combination (continued) |
| Jika goodwill yang telah dialokasikan pada suatu If goodwill has been allocated to a cash- |
| unit penghasil kas dan bagian operasi atas unit generating unit and part of the operation within |
| tersebut dilepas, maka goodwill yang terkait that unit is disposed, the goodwill associated |
| dengan operasi yang dilepas tersebut dimasukkan with the disposed operation is included in the |
| ke dalam jumlah tercatat operasi ketika carrying amount of the operation when |
| menentukan keuntungan atau kerugian dari determining the gain or loss on disposal. |
| pelepasan. Goodwill yang dilepas dalam keadaan Goodwill disposed in these circumstances is |
| tersebut diukur berdasarkan nilai relatif operasi measured based on the relative values of the |
| yang dilepas dan porsi unit penghasil kas yang disposed operation and the portion of the |
| ditahan. cash-generating unit retained. |
| e. Transaksi dan Saldo dalam Mata Uang Asing e. Foreign Currency Transactions and |
| Balances |
| (i) Mata Uang Fungsional dan Penyajian (i) Functional and Presentation Currency |
| Laporan keuangan konsolidasian disajikan The consolidated financial statements are |
| dalam Rupiah (“Rp”), yang merupakan mata presented in Indonesian Rupiah (“Rp”), |
| uang fungsional Perusahaan dan entitas which is the functional currency of the |
| anaknya. Company and its subsidiaries. |
| (ii) Transaksi dan Saldo (ii) Transactions and balances |
| Transaksi dalam mata uang asing dicatat ke Transactions in foreign currencies are |
| mata uang Rupiah dengan menggunakan translated in to Rupiah using the |
| kurs yang berlaku pada tanggal transaksi. exchange rates prevailing at the dates of |
| Pada tanggal laporan posisi keuangan the transactions. Monetary assets and |
| konsolidasian, aset dan liabilitas moneter liabilities denominated in foreign |
| dalam mata uang asing dijabarkan dengan currencies are translated at the rate of |
| kurs yang berlaku saat itu. Pos non-moneter exchange prevailing at the consolidated |
| dalam mata uang asing yang diukur statement of financial position date. Non- |
| berdasarkan nilai historis tidak dijabarkan monetary items that are measured in |
| kembali. Selisih kurs yang timbul atas terms of historical cost in a foreign |
| penyelesaian pos-pos moneter dan currency are not retranslated. Exchange |
| penjabaran kembali pos-pos moneter diakui differences arising on the settlement of |
| pada laba rugi monetary items and on retranslation of |
| monetary items are included in profit or |
| loss. |
| Kurs penutup yang digunakan pada tanggal The closing exchange rates used as of |
| 31 Desember 2025 dan 2024 adalah sebagai December 31, 2025 and 2024 were as |
| berikut: follows: |
| 2025 2024 |
| (Angka Penuh / (Angka Penuh / |
| Full Amount) Full Amount) |
| 1 Dolar Amerika Serikat/Rp 16.782 16.162 1 United States Dollar/Rp |
| 17 |

--- PAGE 27 ---
| The original consolidated financial statements herein are in |
| Indonesian language |
| PT PERINTIS TRINITI PROPERTI Tbk PT PERINTIS TRINITI PROPERTI Tbk |
| DAN ENTITAS ANAKNYA AND ITS SUBSIDIARIES |
| CATATAN ATAS NOTES TO THE |
| LAPORAN KEUANGAN KONSOLIDASIAN CONSOLIDATED FINANCIAL STATEMENTS |
| 31 Desember 2025 December 31, 2025 |
| Dan untuk Tahun yang Berakhir pada Tanggal tersebut For the Year Ended |
| (Disajikan dalam Ribuan Rupiah, (Expressed in Thousands of Rupiah, |
| kecuali dinyatakan lain) unless otherwise stated) |
| 2. INFORMASI KEBIJAKAN AKUNTANSI MATERIAL 2. MATERIAL ACCOUNTING POLICY |
| (lanjutan) INFORMATION (continued) |
| f. Transaksi dengan Pihak-pihak Berelasi f. Transactions with Related Parties |
| Sesuai dengan PSAK 224, “Pengungkapan Pihak- In accordance with PSAK 224, “Related Party |
| pihak Berelasi”, pihak dianggap berelasi jika salah Disclosures”, parties are considered to be |
| satu pihak memiliki kemampuan untuk related if one party has the ability to control (by |
| mengendalikan (dengan cara kepemilikan, secara way of ownership, directly or indirectly) or |
| langsung atau tidak langsung) atau mempunyai exercise significant influence (by way of |
| pengaruh signifikan (dengan cara partisipasi participation in the financial and operating |
| dalam kebijakan keuangan dan operasional) atas policies) over the other party in making |
| pihak lain dalam mengambil keputusan keuangan financial and operating decisions. |
| dan operasional. |
| Seluruh transaksi yang signifikan dengan pihak- All significant transactions with related parties |
| pihak berelasi telah diungkapkan dalam Catatan are disclosed in Note 40 to the consolidated |
| 40 atas laporan keuangan konsolidasian. financial statements. |
| g. Instrumen Keuangan g. Financial Instruments |
| Aset Keuangan Financial Assets |
| Grup menentukan klasifikasi aset keuangan The Group determines the classification of its |
| tersebut pada pengakuan awal. Klasifikasi dan financial assets at initial recognition. |
| pengukuran aset keuangan harus didasarkan Classification and measurement of financial |
| pada bisnis model dan arus kas kontraktual - assets are based on business model and |
| apakah semata dari pembayaran pokok dan contractual cash flows - whether from solely |
| bunga. payment of principal and interest. |
| Aset keuangan diklasifikasikan dalam kategori Financial assets are classified in the following |
| berikut: categories: |
| • Aset keuangan yang diukur dengan biaya • Financial assets at amortized cost; and |
| diamortisasi; dan |
| • Aset keuangan yang diukur dengan nilai wajar • Financial assets at fair value through |
| melalui laba rugi atau melalui penghasilan profit or loss (“FVTPL”) or other |
| komprehensif lain. comprehensive income (“FVOCI”). |
| Semua aset keuangan pada awalnya diakui All financial assets are recognized initially at |
| sebesar nilai wajarnya ditambah dengan biaya- fair value plus transaction costs, except in the |
| biaya transaksi, kecuali aset keuangan dicatat case of financial assets which are recorded at |
| fair value through consolidated profit or loss. |
| pada nilai wajar melalui laba rugi konsolidasian. |
| Pembelian atau penjualan aset keuangan yang Purchases or sales of financial assets that |
| memerlukan penyerahan aset dalam kurun waktu require delivery of assets within a time frame |
| yang ditetapkan oleh peraturan atau kebiasaan established by regulation or convention in the |
| yang berlaku di pasar (perdagangan yang lazim) market place (regular way trades) are |
| diakui pada tanggal perdagangan, yaitu pada recognized on the trade date, i.e., the date that |
| tanggal Grup berkomitmen untuk membeli atau the Group commits to purchase or sell the |
| menjual aset tersebut. assets. |
| 18 |

--- PAGE 28 ---
| The original consolidated financial statements herein are in |
| Indonesian language |
| PT PERINTIS TRINITI PROPERTI Tbk PT PERINTIS TRINITI PROPERTI Tbk |
| DAN ENTITAS ANAKNYA AND ITS SUBSIDIARIES |
| CATATAN ATAS NOTES TO THE |
| LAPORAN KEUANGAN KONSOLIDASIAN CONSOLIDATED FINANCIAL STATEMENTS |
| 31 Desember 2025 December 31, 2025 |
| Dan untuk Tahun yang Berakhir pada Tanggal tersebut For the Year Ended |
| (Disajikan dalam Ribuan Rupiah, (Expressed in Thousands of Rupiah, |
| kecuali dinyatakan lain) unless otherwise stated) |
| 2. INFORMASI KEBIJAKAN AKUNTANSI MATERIAL 2. MATERIAL ACCOUNTING POLICY |
| (lanjutan) INFORMATION (continued) |
| g. Instrumen Keuangan (lanjutan) g. Financial Instruments (continued) |
| Aset Keuangan (lanjutan) Financial Assets (continued) |
| Grup hanya memiliki aset keuangan The Group had only financial assets classified |
| diklasifikasikan sebagai aset keuangan yang as financial assets at amortized cost. The |
| diukur dengan biaya diamortisasi. Aset keuangan Group’s financial assets include cash and |
| Grup meliputi kas dan setara kas, piutang lain-lain, cash equivalents, other receivables, security |
| uang jaminan, dan rekening bank yang dibatasi deposits, and restricted cash in banks. |
| penggunaannya. Aset keuangan diklasifikasikan Financial assets in this category are classified |
| sebagai aset lancar, jika jatuh tempo dalam waktu as current assets if expected to be settled |
| 12 bulan, jika tidak maka aset keuangan ini within 12 months, otherwise they are classified |
| diklasifikasikan sebagai aset tidak lancar. as non-current. |
| Aset keuangan yang diukur dengan biaya Financial assets at amortized cost are |
| diamortisasi selanjutnya diukur dengan subsequently measured using the Effective |
| menggunakan metode suku bunga efektif Interest Rate (“EIR”) method, less impairment. |
| (Effective Interest Rate) (“EIR”), setelah dikurangi Amortized cost is calculated by taking into |
| dengan penurunan nilai. Biaya perolehan yang account any discount or premium on |
| diamortisasi dihitung dengan memperhitungkan acquisition fees or costs that are an integral |
| diskonto atau premi atas biaya akuisisi atau biaya part of the EIR. The EIR amortization is |
| yang merupakan bagian integral dari EIR tersebut. included in the profit or loss. The losses arising |
| Amortisasi EIR dicatat dalam laba rugi. Kerugian from impairment are also recognized in the |
| yang timbul dari penurunan nilai juga diakui pada profit or loss. |
| laba rugi. |
| Aset keuangan dihentikan pengakuannya ketika Financial assets are derecognized when the |
| hak untuk menerima arus kas dari aset tersebut rights to receive cash flows from the assets |
| telah berakhir atau telah ditransfer dan Grup telah have ceased to exist or have been transferred |
| secara substansial mentransfer seluruh risiko dan and the Group has transferred substantially all |
| manfaat kepemilikannya. risks and rewards of ownership. |
| Liabilitas Keuangan Financial Liabilities |
| Liabilitas keuangan dalam lingkup PSAK 109 Financial liabilities within the scope of PSAK |
| diklasifikasikan sebagai berikut: 109 are classified as follows: |
| • Liabilitas keuangan yang diukur dengan biaya • Financial liabilities at amortized cost; and |
| diamortisasi; dan |
| • Liabilitas keuangan yang diukur dengan nilai • Financial liabilities at fair value through |
| wajar melalui laba rugi. profit or loss (“FVTPL”). |
| Grup menentukan klasifikasi liabilitas keuangan The Group determines the classification of its |
| mereka pada saat pengakuan awal. financial liabilities at initial recognition. |
| Seluruh liabilitas keuangan diakui pada awalnya All financial liabilities are recognized initially at |
| sebesar nilai wajar dan, dalam hal pinjaman dan fair value and, in the case of loans and |
| utang, termasuk biaya transaksi yang dapat borrowings, inclusive of directly attributable |
| diatribusikan secara langsung. transaction costs. |
| 19 |

--- PAGE 29 ---
| The original consolidated financial statements herein are in |
| Indonesian language |
| PT PERINTIS TRINITI PROPERTI Tbk PT PERINTIS TRINITI PROPERTI Tbk |
| DAN ENTITAS ANAKNYA AND ITS SUBSIDIARIES |
| CATATAN ATAS NOTES TO THE |
| LAPORAN KEUANGAN KONSOLIDASIAN CONSOLIDATED FINANCIAL STATEMENTS |
| 31 Desember 2025 December 31, 2025 |
| Dan untuk Tahun yang Berakhir pada Tanggal tersebut For the Year Ended |
| (Disajikan dalam Ribuan Rupiah, (Expressed in Thousands of Rupiah, |
| kecuali dinyatakan lain) unless otherwise stated) |
| 2. INFORMASI KEBIJAKAN AKUNTANSI MATERIAL 2. MATERIAL ACCOUNTING POLICY |
| (lanjutan) INFORMATION (continued) |
| g. Instrumen Keuangan (lanjutan) g. Financial Instruments (continued) |
| Liabilitas Keuangan (lanjutan) Financial Liabilities (continued) |
| Grup hanya memiliki liabilitas keuangan The Group’s had only financial liabilities |
| diklasifikasikan sebagai liabilitas keuangan yang classified as financial liabilities at amortized |
| diukur dengan biaya diamortisasi. Liabilitas cost. The Group’s financial liabilities include |
| keuangan Grup meliputi utang usaha, utang lain- accounts payables, other payables, accrued |
| lain, beban akrual, utang pembelian aset tetap, expenses, purchase of fixed assets payables, |
| utang ventura bersama, utang bank dan lembaga joint ventures loans, bank loans and non-bank |
| keuangan non-bank. Liabilitas keuangan financial institutions loans. Financial liabilities |
| diklasifikasikan sebagai liabilitas jangka panjang are classified as non-current liabilities when |
| jika jatuh tempo melebihi 12 bulan dan sebagai the remaining maturity is more than |
| liabilitas jangka pendek jika jatuh tempo yang 12 months, and as current liabilities when the |
| tersisa kurang dari 12 bulan. remaining maturity is less than 12 months |
| Liabilitas keuangan yang diukur pada biaya Financial liabilities at amortized cost (e.g |
| amortisasi (misalnya pinjaman dan utang yang interest-bearing loans and borrowings) are |
| dikenakan bunga) selanjutnya diukur dengan subsequently measured using the EIR |
| menggunakan metode EIR. Amortisasi EIR method. The EIR amortization is included in |
| termasuk di dalam biaya keuangan dalam laba rugi. finance costs in the profit or loss. |
| Liabilitas keuangan dihentikan pengakuannya pada A financial liability is derecognized when the |
| saat liabilitas tersebut berakhir atau dibatalkan atau obligation under the liability is discharged or |
| kedaluwarsa. canceled or has expired. |
| Dalam hal suatu liabilitas keuangan yang ada When an existing financial liability is replaced |
| digantikan oleh liabilitas keuangan lain dari pemberi by another from the same lender on |
| pinjaman yang sama dengan persyaratan yang substantially different terms, or the terms of an |
| berbeda secara substansial, atau modifikasi secara existing liability are substantially modified, |
| substansial atas persyaratan dari suatu liabilitas such an exchange or modification is treated as |
| yang ada, pertukaran atau modifikasi tersebut a derecognition of the original liability and the |
| diperlakukan sebagai penghentian pengakuan recognition of a new liability, and the |
| liabilitas awal dan pengakuan liabilitas baru, dan difference in the respective carrying amounts |
| selisih antara nilai tercatat masing-masing liabilitas is recognized in the consolidated profit or loss. |
| diakui dalam laba rugi konsolidasian. |
| Saling Hapus antar Aset dan Liabilitas Offsetting Financial Assets and Financial |
| Keuangan Liabilities |
| Aset dan liabilitas keuangan dapat saling hapus Financial assets and liabilities are offset and |
| dan nilai bersihnya disajikan dalam laporan posisi the net amount is presented in the |
| keuangan konsolidasian jika, dan hanya jika, consolidated statement of financial position if, |
| Grup saat ini memiliki hak yang berkekuatan hukum and only if, the Group currently has a legally |
| untuk melakukan saling hapus atas jumlah yang enforceable right to offset the recognized |
| telah diakui tersebut dan berniat untuk amounts and intends either to settle on a net |
| menyelesaikan secara neto atau untuk basis, or to realize the asset and settle the |
| merealisasikan aset dan menyelesaikan liability simultaneously. |
| liabilitasnya secara simultan. |
| 20 |
