# Baseline changelog

Every promotion, with the reason a person gave for it. A baseline that moves
without an entry here is a gate that was quietly lowered.

| date | provider | commit | prompt | accuracy | reason |
|---|---|---|---|---|---|
| 2026-09-23 | gemini_gemini-3.1-flash-lite_image | `e02530d` | `db09b37780b3` | 93.1% (2065/2219) | first full-corpus pass |
| 2026-09-23 | gemini_gemini-3.1-flash-lite_image | `e02530d` | `db09b37780b3` | 93.2% (2077/2229), was 93.1% | bootstrap: first full-corpus pass, 223 filings on the deployed 3.1-lite/3.5-lite chain; GTRA labels known shifted, JPFA total_share labels known stale |
| 2026-09-23 | gemini_gemini-3.1-flash-lite_image | `e02530d` | `db09b37780b3` | 98.9% (2204/2229), was 93.2% | re-promoted after the GTRA column shift and the JPFA stale outstanding count were corrected; the previous baseline measured against labels now known wrong |
| 2026-09-23 | gemini_gemini-3.1-flash-lite_image | `e02530d` | `db09b37780b3` | 98.9% (2205/2229), was 98.9% | after the GTRA J8 double-count and the Q/R shift leftovers were corrected; every remaining wrong cell is the extractor's own |
