# Checkpoint proyek

Rekap kerja yang sudah dilakukan, supaya sesi AI berikutnya (atau Anda sendiri) tahu
konteksnya tanpa membaca ulang percakapan lama. Semua angka di sini dari run nyata. Kalau
sebuah angka belum pernah diukur, file ini bilang begitu.

**Cara pakai**
- Baca bagian *Status sekarang* dan *Pekerjaan tertunda* dulu, sisanya sesuai kebutuhan.
- Setiap selesai satu pekerjaan berarti, tambahkan satu entri di *Log checkpoint* (terbaru
  di bawah), lalu perbarui *Status sekarang* dan *Pekerjaan tertunda*.
- Angka di file ini adalah snapshot. Sebelum dipakai untuk keputusan, cek ulang ke
  scorecard atau output yang disebut.

Terakhir diperbarui: **2026-09-29**

---

## Proyek dalam lima kalimat

Sistem ekstraksi dokumen berbasis AI untuk laporan keuangan emiten IDX. Input-nya PDF
laporan kuartalan/tahunan, output-nya 10 field (aset, total aset lancar, kas, liabilitas,
utang bank, ekuitas, laba bersih, pendapatan, kas dari aktivitas operasi, total share)
dalam Rupiah penuh, per filing. Awalnya take-home test, sekarang jadi pekerjaan freelance
nyata. Di sekelilingnya ada harness evaluasi atas 223 filing / 2.229 sel berlabel dari
14 emiten, ekstraktor agentic pembanding, dan (terbaru) agen audit untuk ground truth.
Setelah email penolakan, tujuannya adalah menunjukkan *agentic system end to end dengan
evaluasi yang mengukur kualitas, bukan mendemonstrasikannya*.

## Aturan tetap (jangan dilanggar)

| Aturan | Alasan / asal |
|---|---|
| **Jangan commit atau `git add` kecuali diminta.** Selesaikan, verifikasi, laporkan, berhenti. | Permintaan eksplisit user |
| **Tidak ada atribusi Claude/AI** (`Co-Authored-By`, "Generated with…") di commit atau PR, di semua proyek. | Permintaan eksplisit user |
| **Jangan ubah workbook ground truth tanpa persetujuan user.** Usulan koreksi ditulis sebagai formulir, dan setiap koreksi dicatat di `data/ground_truth/CORRECTIONS.md`. | Integritas label |
| **Jangan mengarang angka.** Setiap klaim harus dari run nyata. Kalau belum diukur, tulis "belum diukur". | Permintaan user |
| **Jangan mengakali batas API Google** (multi-akun atau multi-project). Kalau kuota habis, berhenti dan lanjutkan besok. | Permintaan user |
| **`total_share` = jumlah saham BEREDAR** dari tabel pemegang saham, bukan dari header ekuitas atau modal ÷ nominal. | Keputusan user |
| **Auditor label tidak boleh model yang sama** dengan model yang dievaluasi (`GEMINI_MODEL`). | Skill `label-groundtruth` |

## Status sekarang

- **Belum ada yang di-commit sejak `e02530d`.** Working tree berisi:
  - perubahan di `.env.example`, `.gitignore`, `README.md`, 4 workbook (ADMR, GTRA, JPFA,
    PTBA), `CORRECTIONS.md`, `src/` (`extract.py`, `llm.py`, `prompts.py`,
    `api_models.py`, `agenttools.py`), dan `scripts/`;
  - file baru yang belum di-track: `.github/`, `evals/`, `docs/`, `src/agent.py`,
    `src/agenttools.py`, `src/evalkit.py`, `src/evalmetrics.py`, `src/periods.py`,
    `src/pagemd.py`, `src/labelaudit.py`, `src/auditagent.py`, beberapa skrip baru, dan
    test baru;
  - scorecard serta 223 file prediksi di `output/predictions/`.

  Cek `git status` untuk daftar pastinya.
- **Test: 184 passed** (`python -m pytest -q`, ~3 menit, tanpa API key).
- **Mode input default: `markdown`** (`GEMINI_INPUT_MODE=markdown` di `.env`, di
  `.env.example`, dan default di `src/llm.py`). Otomatis pindah ke `image` per filing kalau
  text layer tidak terbaca.
- **Model yang dievaluasi:** `gemini-3.1-flash-lite`. Auditor label: `gemini-3.8-flash`
  (fallback ke 3.7-flash, lalu 3.6-flash).
- **Sedang tertahan:** pilot agen audit label. Pada 2026-09-28, 3.8-flash dan 3.7-flash
  kena 503 overload terus-menerus, dan kuota harian 3.6-flash habis. Lanjutkan dengan
  perintah di bagian *Pekerjaan tertunda* no. 1.

## Angka kunci (snapshot)

| Apa | Nilai | Sumber |
|---|---|---|
| Akurasi korpus, pipeline, mode image | **98,9% (2.205/2.229)**: 10 salah, 14 terlewat, 11 abstain | `output/corpus_scorecard_gemini_gemini-3.1-flash-lite_image.json` |
| Sisa 10 sel salah | 8 `utang_bank`, 1 `kas`, 1 `total_share`; semuanya kesalahan extractor, bukan label | scorecard di atas |
| Biaya pipeline | ~31.184 token input per filing, ~4 call per filing | scorecard di atas |
| Markdown vs image (12 filing) | image 117/120, markdown **118/120**; +0,83pp, CI 95% [0,00; +2,50]; token +7,0%; waktu p50 +5,2% | `output/corpus_scorecard_*_markdown__n12s1.json` vs `*_image__n12s1.json` |
| EMAS (4 filing, markdown + fallback image) | 40/40 | `output/corpus_scorecard_*_markdown_EMAS.json` |
| Agen ekstraksi (1 filing saja) | 7/10 benar, 12 call, 118.170 token input, 241 detik. Tidak konklusif (n=1). | `output/corpus_scorecard_*_image_agentic.json` |
| Label identik dengan CSV lama `pdf_to_csv.py` | **2.188 dari 2.229 sel (98,2%)**: kontaminasi ground truth | `audit_labels.py --phase screen` |

## Log checkpoint

### CP1: `total_share` hanya dari saham beredar
Sumber dari header ekuitas dibuang. Yang dicari hanya informasi jumlah saham beredar
(tabel pemegang saham). `GROUP_FIELDS` diubah: field saham pindah ke grup `share_capital`,
dan `merge_group` mengosongkan field saham dari grup lain. Ada juga guard
`_apply_treasury_date_guard` supaya saham treasuri diambil dari tanggal yang benar.

### CP2: JPFA, batch run, dan tipe `total_share`
- JPFA salah baca `total_share` → diperbaiki.
- Menjalankan satu folder emiten sekaligus: `scripts/pdf_to_csv.py --dir ~/FinancialReport/<T> --ticker <T> -o ...`.
- Kasus loop zsh: `caffeinate -i` tidak bisa langsung membungkus `for`; bungkus loop-nya
  di `zsh -c '...'`.
- `total_share` sekarang ditulis numerik di CSV.

### CP3: Harga saham otomatis ke semua workbook
`scripts/fetch_share_prices.py` mengisi harga penutupan per kuartal ke setiap workbook
ground truth. Tanggalnya tidak harus tepat tanggal 17; tanggal bursa terdekat dipakai.

### CP4: Harness evaluasi (rencana minggu 1–2)
- Corpus mode: 223 pasangan (ticker, periode), 2.229 sel berlabel, 14 emiten.
- Metrik: coverage, accuracy, accuracy_on_answered, presisi/recall abstain, kalibrasi +
  ECE, slice (ticker/field/tahun/kuartal/mata uang/skala/text layer/model), biaya dan
  latensi, bootstrap berpasangan per klaster (filing dan ticker).
- File: `src/evalkit.py`, `src/evalmetrics.py`, `src/periods.py`,
  `scripts/run_eval.py --corpus`, `report_eval.py`, `compare_runs.py`,
  `promote_baseline.py`, `.github/workflows/eval.yml` (gate CI tanpa key, memakai
  prediksi yang di-cache).
- Provenance: `provider_tag` = model + mode input (+ `_api`, `_agentic`). Scorecard subset
  diberi akhiran `_TICKERS` / `_nNsS` supaya tidak menimpa scorecard korpus (bug ini
  pernah terjadi dan sudah diperbaiki).

### CP5: Ekstraktor agentic (rencana minggu 3–4)
- `src/agent.py` + `src/agenttools.py`: loop tool-calling Gemini.
  - Tools: `list_pages`, `search_text`, `read_page_text`, `read_page_image`, empat
    `report_<group>`, dan `finish`.
  - `AgentBudget` membedakan budget yang menghentikan loop dan budget yang hanya menolak
    tool.
  - Trajectory disimpan sebagai bentuk (tanpa isi halaman) di samping prediksi.
  - Saat pindah provider, yang dibawa adalah temuan, bukan transcript, dan budget tidak
    di-reset.
- `run_eval.py --extractor agentic`. Transport ada di `llm.py`
  (`complete_with_tools`, tanpa `responseMimeType`).
- Hasil: baru 1 filing terukur (lihat Angka kunci). Hipotesis yang ditulis sebelum run:
  hasil paling mungkin adalah agen hanya menemukan ulang page selector dengan biaya ~3×.
- **Belum** disambungkan ke `pdf_to_csv.py` atau `src/api.py`. Agen bisa diukur, tapi
  belum bisa di-deploy.

### CP6: Perbaikan label dan analisis sisa error
- Kesalahan label yang ditemukan dan diperbaiki (semua tercatat di `CORRECTIONS.md`):
  - GTRA bergeser dua kolom (117 sel);
  - GTRA `J8` (Q2 2024 `utang_bank`) = 2 × 18.672.839.545, baris yang sama dihitung dua
    kali. Asalnya dilacak ke `gtra.csv` dari pipeline lama;
  - JPFA `total_share` basi (11 sel, selisih 7.361.200 saham);
  - ADMR dan PTBA `D1` menyebut emiten yang salah;
  - sisa GTRA `Q4:R13`.
- Akurasi naik dari 93,2% ke 98,9%.
- Hipotesis "batasi confidence `utang_bank` kalau salah satu komponennya hilang"
  **dibantah data**: akurasi 98,6% kalau kedua komponen ada, 92,3% kalau hanya bagian
  lancar, 88,9% kalau hanya jangka pendek. Aturan itu akan membuang ~73 jawaban benar
  untuk menangkap 7 yang salah (presisi 9%), jadi tidak dipasang.
- Bug `ZeroDivisionError` di `classify_failure` (saat `ratio == 0`) diperbaiki, dan
  test-nya ditambahkan.

### CP7: Input markdown menggantikan image
- `src/pagemd.py` membangun ulang halaman menjadi tabel markdown dari posisi kata:
  - kolom ditemukan dari tepi kanan angka (hanya angka yang dikelompokkan ribuan yang
    "memilih" kolom);
  - angka yang terpotong digabung kembali (celah −0,02pt vs 46–96pt untuk nomor catatan);
  - indentasi dipertahankan sebagai `·`;
  - header kolom diberi nama tanggal periode.
- Dua cacat versi pertama ditemukan dengan membaca output-nya: indentasi hilang (TLDN
  dijawab 2×), dan nomor catatan `3,10` menciptakan kolom palsu.
- Fallback per filing ke mode image berdasarkan **keterbacaan text layer mentah**
  (`text_layer_usable`), bukan berdasarkan "tabel berhasil dibuat". Filing glyph-id
  seperti EMAS Q3 2025 tetap menghasilkan tabel, tapi isinya sampah.
- **MarkItDown dicoba dan ditolak:** 419 dan 465 baris per dokumen berisi dua angka dalam
  satu sel, dibanding 0 untuk `pagemd`. Paket itu terpasang, tapi tidak masuk
  `requirements.txt`.
- Default diubah ke `markdown`. Catatan: bukti baru 16 filing dan CI-nya menyentuh nol.

### CP8: Agen audit ground truth (2026-09-28)
- **Tujuan:** memeriksa label secara independen, karena 98,2% label disalin dari output
  pipeline lama.
- **File:**
  - `src/labelaudit.py`: bagian deterministik, yaitu screen, verifikasi kutipan
    (angka ada di halaman + kolom periode dicek dari geometri `pagemd`), konversi skala
    dan FX, injeksi error, dan bootstrap;
  - `src/auditagent.py`: loop, compaction, pacer TPM, dan penanganan kuota harian;
  - `find_number` di `agenttools.py`;
  - `AUDIT_*` prompts di `prompts.py`;
  - `scripts/audit_labels.py` dan `scripts/audit_benchmark.py`;
  - 29 test baru (`tests/test_labelaudit.py`, `tests/test_auditagent.py`).
- **Tahap:**
  1. screen (gratis);
  2. baca **buta** (agen tidak pernah melihat label);
  3. adjudikasi hanya untuk sel yang berselisih. Vonis `label_wrong` hanya diterima kalau
     angka penggantinya lolos verifikasi; kalau tidak, statusnya `needs_human`.
- **Output:** `output/label_audit/audit_<model>/`, berisi cache per filing,
  `audit_report.md` dan `PROPOSED_CORRECTIONS.md`. **Tidak pernah menulis workbook**, dan
  ada test yang membuktikannya lewat hash file.
- **Hasil screen:**
  - pada `HEAD`: 4 kolom GTRA duplikat (masing-masing 9 field identik), 2 masalah D1,
    138 sel berbeda dengan extractor;
  - pada working tree: 0 duplikat, 0 masalah D1, 10 sel berbeda (= 10 sel salah
    extractor).
- **Pilot GTRA Q2 2024 belum menghasilkan audit.**
  - Percobaan 1: 9 call di 3.6-flash (56.296 token input) lalu koneksi putus.
  - Percobaan 2: 503 di 3.8 dan 3.7-flash, kuota harian 3.6-flash habis.
  - Dua cacat yang ditemukan pilot sudah diperbaiki: token dibaca dari kunci yang salah
    (`usage["tokens"]["input"]`), dan agen membaca ulang halaman yang sudah di-compact
    sebelum melapor. Retry 503 untuk audit juga dibuat lebih sabar (`AUDIT_RETRIES=4`,
    backoff 10 detik).
- **Batas gagal yang ditulis sebelum run** (`audit_benchmark.py`):
  - recall kunci HEAD < 80%;
  - alarm palsu > 5%;
  - sel yang tidak bisa dinilai > 20%;
  - GTRA tidak diberi penyebab `period_shift`.

## Pekerjaan tertunda (urutan yang disarankan)

1. **Lanjutkan audit label** setelah kuota atau kapasitas pulih:
   ```bash
   python scripts/audit_labels.py --filings GTRA_Q2_2024 JPFA_Q3_2023 ARCI_Q1_2022
   python scripts/audit_labels.py --corpus --estimate
   python scripts/audit_benchmark.py --tickers GTRA JPFA ADMR PTBA
   python scripts/audit_labels.py --corpus      # ulangi setiap hari sampai tidak ada yang tertunda
   ```
   Baca trajectory pilot dulu (`output/label_audit/audit_gemini-3.8-flash/filings/*.json`)
   sebelum menghabiskan kuota besar. Isi `AUDIT_TPM_LIMIT` / `AUDIT_RPD_LIMIT` di `.env`
   sesuai kuota.
2. **Run korpus penuh mode markdown** (~3 jam), lalu bandingkan dengan baseline image di
   `evals/baselines/gemini_gemini-3.1-flash-lite_image/`:
   ```bash
   GEMINI_INPUT_MODE=markdown python scripts/run_eval.py --corpus --corpus-root data/raw ~/FinancialReport
   python scripts/compare_runs.py evals/baselines/gemini_gemini-3.1-flash-lite_image/corpus_scorecard.json output/corpus_scorecard_gemini_gemini-3.1-flash-lite_markdown.json --bootstrap
   ```
3. **Verifikasi 9 sel sengketa tersisa ke filing-nya** (label = CSV lama, tapi run hari
   ini berbeda), seperti yang dulu dilakukan untuk GTRA `J8`. Agen audit bisa mengambil
   alih pekerjaan ini.
4. **Buat sampel berlabel yang independen**, dibaca manusia atau model lain, supaya ground
   truth tidak berasal dari output extractor sendiri.
5. **Sambungkan agen ekstraksi ke `pdf_to_csv.py` dan `src/api.py`.** Mode markdown sudah
   otomatis terpakai lewat `extract_from_pdf`.
6. Opsional: eksperimen agen vs pipeline per strata (A: filing yang butuh patch page
   selection, B: sampel acak 30, C: ARCI), dan promosi baseline dalam mode markdown.
7. Commit: keputusan user. Working tree-nya besar dan belum pernah di-commit sejak
   `e02530d`.

## Peta file

| Area | File |
|---|---|
| Ekstraksi | `src/extract.py` (orkestrasi, `GROUP_FIELDS`, guard, `derive_fields`), `src/page_select.py`, `src/pagemd.py`, `src/pdftext.py`, `src/normalize.py`, `src/confidence.py`, `src/validate.py`, `src/prompts.py`, `src/llm.py` |
| Agen ekstraksi | `src/agent.py`, `src/agenttools.py` |
| Evaluasi | `src/evalkit.py`, `src/evalmetrics.py`, `scripts/run_eval.py`, `report_eval.py`, `compare_runs.py`, `promote_baseline.py`, `page_agreement.py`, `evals/baselines/` |
| Audit label | `src/labelaudit.py`, `src/auditagent.py`, `scripts/audit_labels.py`, `scripts/audit_benchmark.py` |
| Ground truth | `data/ground_truth/<TICKER>.xlsx` (Sheet1, D1 = emiten, baris 3 = periode, baris 4–13 = field), `CORRECTIONS.md`, skill `.claude/skills/label-groundtruth/` |
| Filing | `data/raw/` (di repo), `~/FinancialReport/<TICKER>/` (arsip pribadi, termasuk CSV lama) |
| Dokumentasi utama | `README.md` (panjang; ada bagian per keputusan dan hasil terukur) |

## Jebakan yang sudah pernah kena

- `.env` menimpa default di kode. Mengubah default di `llm.py` saja tidak berpengaruh
  kalau `.env` masih berisi nilai lama.
- macOS tidak punya perintah `timeout`.
- Output yang di-pipe ke `tail` ter-buffer, jadi progres tidak terlihat. Pakai
  `PYTHONUNBUFFERED=1`.
- Menjalankan `run_eval.py` pada subset dulu pernah menimpa scorecard korpus. Sekarang ada
  akhiran subset. Jangan hapus mekanisme itu.
- Filing glyph-id (EMAS Q3 2025) punya word box tapi isinya bukan kata. Putuskan dari
  `text_layer_usable` pada teks mentah.
- Gemini: `responseMimeType` dan `tools` tidak boleh dikirim bersamaan (400).
- `usage.to_dict()` menyimpan token di `["tokens"]["input"]`, bukan `input_tokens`.
- Kuota Gemini berlaku per model. 429 per menit bisa ditunggu; 429 per hari tidak bisa
  (berhenti dan lanjutkan besok).
