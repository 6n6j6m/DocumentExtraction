# Evaluation — CORPUS on `gemini_gemini-3.1-flash-lite_image`

- **run** 2026-09-23T08:24:58+00:00, commit `e02530d` (dirty tree), prompt `db09b37780b3`
- **target** in-process, tolerance 0.0001
- **corpus** 223 of 223 filings scored, 14 issuers, 2229 labelled cells

## Headline

| | |
|---|---:|
| accuracy (labelled cells) | **98.9%** (2205/2229) |
| accuracy when it answered | 99.5% |
| answer rate | 99.4% |
| wrong | 10 |
| withheld on a labelled cell | 11 |
| LLM calls per filing | 3.98 |
| tokens per filing | 31,184 in / 1,143 out |
| seconds per filing (p50 / p95) | 32.8 / 109.5 |
| cost | — (no price configured for gemini-3.1-flash-lite - add it to /Users/muhammadnajmirahmani/Belajar/ProjectDatasaur/config/pricing.json) |

## Coverage

Every labelled cell lands in exactly one row. The last three rows are cells
nobody has labelled yet: an abstention there used to vanish into
`both_absent`, counted in neither the numerator nor the denominator.

| bucket | n |
|---|---:|
| labelled cells | 2229 |
| … answered correctly | 2205 |
| … answered wrongly | 10 |
| … withheld deliberately | 11 |
| … missing for another reason | 3 |
| unlabelled, answered | 1 |
| unlabelled, withheld | 0 |
| unlabelled, silent | 0 |

## Was withholding the right call?

- **withdrawn** 11 labelled cells
- **caught** 2 — the withheld figure would have been wrong
- **thrown away** 6 — it would have been right
- **precision** 25.0%, **recall** 16.7% (of 12 cells that would have been wrong)
- **unknown** 3 withdrawals whose withheld figure was never recorded — excluded from precision rather than assumed either way (predictions cached before `assess()` kept it)

## Calibration

Does a stated confidence mean what it says? ECE **0.006** over 2215 answered cells; a negative gap is overconfidence.

| confidence | n | mean stated | observed accuracy | gap |
|---|---:|---:|---:|---:|
| 0.85–0.95 | 122 | 0.856 | 94.3% | 0.087 |
| 0.95–1.00 | 2093 | 1.000 | 99.9% | -0.001 |

## Slices

Each row carries its n. A slice of four cells is an anecdote, and the
column is there so it cannot be quoted as anything else.

### ticker

| value | n | filings | correct | wrong | missed | accuracy | answered |
|---|---:|---:|---:|---:|---:|---:|---:|
| TOTL | 180 | 18 | 173 | 0 | 7 | 96.1% | 96.1% |
| AADI | 70 | 7 | 68 | 2 | 0 | 97.1% | 100.0% |
| ADMR | 180 | 18 | 176 | 4 | 0 | 97.8% | 100.0% |
| GTRA | 150 | 15 | 147 | 0 | 3 | 98.0% | 98.0% |
| JPFA | 180 | 18 | 177 | 0 | 3 | 98.3% | 98.3% |
| TLDN | 170 | 17 | 168 | 1 | 1 | 98.8% | 99.4% |
| LSIP | 180 | 18 | 178 | 2 | 0 | 98.9% | 100.0% |
| CPIN | 180 | 18 | 179 | 1 | 0 | 99.4% | 100.0% |
| ARCI | 180 | 18 | 180 | 0 | 0 | 100.0% | 100.0% |
| DSNG | 180 | 18 | 180 | 0 | 0 | 100.0% | 100.0% |
| PTBA | 180 | 18 | 180 | 0 | 0 | 100.0% | 100.0% |
| TAPG | 180 | 18 | 180 | 0 | 0 | 100.0% | 100.0% |
| ITMG | 179 | 18 | 179 | 0 | 0 | 100.0% | 100.0% |
| EMAS | 40 | 4 | 40 | 0 | 0 | 100.0% | 100.0% |

### field

| value | n | filings | correct | wrong | missed | accuracy | answered |
|---|---:|---:|---:|---:|---:|---:|---:|
| utang_bank | 223 | 223 | 213 | 8 | 2 | 95.5% | 99.1% |
| total_share | 222 | 223 | 215 | 1 | 6 | 96.8% | 97.3% |
| pendapatan | 223 | 223 | 221 | 0 | 2 | 99.1% | 99.1% |
| total_aset_lancar | 223 | 223 | 221 | 0 | 2 | 99.1% | 99.1% |
| kas | 223 | 223 | 222 | 1 | 0 | 99.6% | 100.0% |
| laba_bersih | 223 | 223 | 222 | 0 | 1 | 99.6% | 99.6% |
| liabilitas | 223 | 223 | 222 | 0 | 1 | 99.6% | 99.6% |
| aset | 223 | 223 | 223 | 0 | 0 | 100.0% | 100.0% |
| ekuitas | 223 | 223 | 223 | 0 | 0 | 100.0% | 100.0% |
| kas_dari_aktivitas_operasi | 223 | 223 | 223 | 0 | 0 | 100.0% | 100.0% |

### year

| value | n | filings | correct | wrong | missed | accuracy | answered |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 440 | 44 | 432 | 1 | 7 | 98.2% | 98.4% |
| 2025 | 539 | 54 | 532 | 3 | 4 | 98.7% | 99.3% |
| 2024 | 490 | 49 | 486 | 3 | 1 | 99.2% | 99.8% |
| 2026 | 280 | 28 | 278 | 2 | 0 | 99.3% | 100.0% |
| 2023 | 480 | 48 | 477 | 1 | 2 | 99.4% | 99.6% |

### quarter

| value | n | filings | correct | wrong | missed | accuracy | answered |
|---|---:|---:|---:|---:|---:|---:|---:|
| Q3 | 489 | 49 | 482 | 2 | 5 | 98.6% | 99.0% |
| Q1 | 610 | 61 | 602 | 1 | 7 | 98.7% | 98.9% |
| Q2 | 620 | 62 | 615 | 4 | 1 | 99.2% | 99.8% |
| Q4 | 510 | 51 | 506 | 3 | 1 | 99.2% | 99.8% |

### currency

| value | n | filings | correct | wrong | missed | accuracy | answered |
|---|---:|---:|---:|---:|---:|---:|---:|
| IDR | 1580 | 158 | 1562 | 4 | 14 | 98.9% | 99.1% |
| USD | 649 | 65 | 643 | 6 | 0 | 99.1% | 100.0% |

### reporting_scale

| value | n | filings | correct | wrong | missed | accuracy | answered |
|---|---:|---:|---:|---:|---:|---:|---:|
| THOUSANDS | 649 | 65 | 636 | 5 | 8 | 98.0% | 98.8% |
| FULL | 500 | 50 | 495 | 2 | 3 | 99.0% | 99.4% |
| MILLIONS | 1080 | 108 | 1074 | 3 | 3 | 99.4% | 99.7% |

### text_layer

| value | n | filings | correct | wrong | missed | accuracy | answered |
|---|---:|---:|---:|---:|---:|---:|---:|
| shredded | 120 | 12 | 113 | 0 | 7 | 94.2% | 94.2% |
| clean | 2109 | 211 | 2092 | 10 | 7 | 99.2% | 99.7% |

### model

| value | n | filings | correct | wrong | missed | accuracy | answered |
|---|---:|---:|---:|---:|---:|---:|---:|
| unknown | 80 | 8 | 77 | 0 | 3 | 96.2% | 96.2% |
| gemini:gemini-3.5-flash-lite | 890 | 89 | 879 | 3 | 8 | 98.8% | 99.1% |
| gemini:gemini-3.1-flash-lite | 1259 | 126 | 1249 | 7 | 3 | 99.2% | 99.8% |

## Failures by kind

| kind | n |
|---|---:|
| wrong_value | 9 |
| wrong_near_miss | 1 |

## Worst cells

| filing | field | predicted | truth | error | conf | kind | why |
|---|---|---:|---:|---:|---:|---|---|
| LSIP Q3 2025 | utang_bank | 177,362,000,000 | 0 | 17736200000000.00% | 0.86 | wrong_value | derived from utang_bank_jangka_pendek, utang_bank_bagian_lancar; graded on those |
| AADI Q2 2025 | utang_bank | 7,990,758,064,516 | 349,516,129,032 | 2186.23% | 0.86 | wrong_value | derived from utang_bank_jangka_pendek, utang_bank_bagian_lancar; graded on those |
| ADMR Q2 2025 | utang_bank | 0 | 5,284,096,774 | 100.00% | 0.86 | wrong_value | derived from utang_bank_jangka_pendek, utang_bank_bagian_lancar; graded on those |
| ADMR Q1 2026 | utang_bank | 637,406,779,661 | 16,264,593,220,339 | 96.08% | 0.86 | wrong_value | derived from utang_bank_jangka_pendek, utang_bank_bagian_lancar; graded on those |
| AADI Q4 2024 | utang_bank | 659,419,354,839 | 11,074,016,129,032 | 94.05% | 0.86 | wrong_value | derived from utang_bank_jangka_pendek, utang_bank_bagian_lancar; graded on those |
| ADMR Q2 2026 | utang_bank | 5,638,607,142,857 | 20,674,714,285,714 | 72.73% | 0.86 | wrong_value | derived from utang_bank_jangka_pendek, utang_bank_bagian_lancar; graded on those |
| CPIN Q4 2024 | utang_bank | 5,400,000,000,000 | 7,392,848,000,000 | 26.96% | 1.00 | wrong_value | derived from utang_bank_jangka_pendek, utang_bank_bagian_lancar; graded on those |
| ADMR Q2 2022 | kas | 5,495,776,552,239 | 6,346,501,388,060 | 13.40% | 1.00 | wrong_value | — |
| TLDN Q3 2023 | utang_bank | 441,100,000,000 | 504,707,348,000 | 12.60% | 0.86 | wrong_value | derived from utang_bank_jangka_pendek, utang_bank_bagian_lancar; graded on those |
| LSIP Q4 2024 | total_share | 6,822,863,965 | 6,819,963,965 | 0.04% | 1.00 | wrong_near_miss | — |

---

Figures are compared in full Rupiah. The conversion is cached arithmetic over
the model's own output (`_derived` beside each prediction), not a second
source of truth: refreshing it cannot change what the model said.
