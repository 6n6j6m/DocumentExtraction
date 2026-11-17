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

Terakhir diperbarui: **2026-11-17**

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
| **Satuan `total_share` tidak dipengaruhi satuan di header** ("dalam ribuan Rupiah" hanya untuk angka Rupiah). Jumlah saham diambil apa adanya; label TRIN (mis. 4.352.457) benar. | Klarifikasi user 2026-11-01 |
| **Ekstraksi nilai oleh Claude, bukan Gemini** (sejak 2026-11-17): `.env` `LLM_PROVIDER=claude-code`, tanpa fallback; subagen `extraction-reader` menjawab, `extraction-evaluator` mengevaluasi + dreaming. | Permintaan eksplisit user 2026-11-17 |
| **Auditor label tidak boleh model yang sama** dengan model yang dievaluasi (`GEMINI_MODEL`). | Skill `label-groundtruth` |

## Status sekarang

- **HEAD:** `89a6b61` (`fix: clean up the cache of gitignore`). Working tree belum
  di-commit; perubahan mencakup README, harness evaluasi, validasi utang, pencarian tabel
  saham, prompt ekstraksi, checkpoint, serta workbook ground truth yang sudah berubah
  sebelumnya. Jangan stage/commit; jangan ubah workbook tanpa persetujuan.
- **Kurs USD (CP37):** `data/fx_rates_bi.csv` ada (Excel BI, 20 kuartal s.d. 2026-09-30);
  ENRG/PGAS kini membaca kursnya sendiri; ESSA/APEX pakai kurs BI.
- **Test terakhir:** suite penuh **274 passed** (2026-11-17, CP48). Sebelumnya 273 passed (CP46). Sebelumnya 267 passed (CP45). Sebelumnya 265 passed (2026-11-07, CP43). Sebelumnya 262 passed (CP42), 260 passed (CP41), 258 passed (CP40), 256 passed. Sebelumnya **229 passed** (2026-10-18). Sebelumnya 184 passed. Setelah menambah guard untuk
  menolak kombinasi API + ekstraktor agentic, `python -m pytest tests/test_agent.py -q`
  menghasilkan **24 passed**. Suite penuh belum dijalankan ulang.
- **Audit generalisasi dari CSV eksternal:** 67 filing PURA/RCCC/TRIN/TRUK; 8 berstatus
  `ok`, 59 `partial`, 54 nilai `total_share` kosong. `section_map_incomplete` muncul di
  53 baris. Pencocokan PDF mengonfirmasi contoh `utang_bank` salah pada TRIN Q1 2022 dan
  `total_share` yang hilang pada RCCC Q1 2024. Ini diagnostik, bukan skor akurasi karena
  empat emiten tersebut belum punya workbook ground truth di repo.
- Perbaikan kode saat itu menolak angka pada baris gabungan bank/non-bank; penolakan ini
  kemudian dikoreksi pada CP15 setelah pengguna menegaskan bahwa pinjaman lembaga
  keuangan non-bank termasuk definisi `utang_bank`. Deteksi saham juga diperluas untuk
  hitungan di bawah 1 miliar serta digit awal yang terpecah.
  Ekstraksi ulang dan dampaknya pada 67 filing belum diukur.
- **Mode input default: `markdown`** (`GEMINI_INPUT_MODE=markdown` di `.env`, di
  `.env.example`, dan default di `src/llm.py`). Otomatis pindah ke `image` per filing kalau
  text layer tidak terbaca.
- **Model ekstraksi sejak 2026-11-17: Claude** (CP49; skill `pdf-to-excel` + `claude-extract`). Sebelumnya `gemini-3.1-flash-lite`/`3.5-flash-lite`; baris lama di CSV tetap bertanda model Gemini sampai di-refresh. Auditor label: `gemini-3.8-flash`
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
| Agen ekstraksi | Scorecard mencakup 3 pasangan / 30 sel; hanya 1 filing berhasil dinilai: 7 benar, 1 salah, 2 terlewat. Dua filing gagal karena 503/kuota harian. 12 call, 118.170 token input, 241 detik; tidak konklusif (n=1). | `output/corpus_scorecard_gemini_gemini-3.1-flash-lite_image_agentic.json` |
| Label identik dengan CSV lama `pdf_to_csv.py` | **2.188 dari 2.229 sel (98,2%)**: kontaminasi ground truth | `audit_labels.py --phase screen` |
| Generalisasi PURA/RCCC/TRIN/TRUK | **67 filing**, 8 `ok`, 59 `partial`, 54 `total_share` kosong; satu kesalahan semantik utang bank dikonfirmasi pada PDF TRIN | CSV eksternal + PDF sumber; belum ada label independen |

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

### CP9: Mencegah evaluasi API salah diberi label agentic (2026-10-08)
- Pemeriksaan `run_eval.py` menemukan bahwa `--api-url --extractor agentic` sebelumnya
  tetap mengirim filing ke endpoint `/extract` (yang menjalankan pipeline), tetapi nama
  cache dan scorecard mendapat suffix `_agentic`.
- `scripts/run_eval.py` sekarang menolak kombinasi tersebut sampai ekstraktor agentic
  benar-benar tersedia melalui API. Regresi ini dicakup oleh tes di `tests/test_agent.py`.
- Verifikasi: `python -m pytest tests/test_agent.py -q` → **24 passed**; `git diff --check`
  bersih.
- Audit artefak agentic lama: pemilihan sampel berisi 3 filing/30 sel, tetapi dua filing
  gagal sebelum ekstraksi karena 429 kuota harian dan 503 kapasitas. Satu filing
  (`TOTL Q4 2024`) menghasilkan 7 benar, 1 salah, dan 2 terlewat. Benchmark belum
  memasukkan `page_agreement`: trajectory lama belum di-backfill dengan halaman selector.

### CP10: Bukti generalisasi di luar 14 emiten berlabel (2026-10-08)
- Menganalisis CSV ekstraksi pengguna untuk PURA (18 filing), RCCC (13), TRIN (18), dan
  TRUK (18): total 67. Hanya 8 `ok` (semuanya PURA), 59 `partial`; 54 baris memiliki
  `total_share` kosong. Kolom `abstained` kosong pada banyak baris partial, jadi ia tidak
  menangkap semua field yang tidak terisi.
- `section_map_incomplete` muncul pada 53 dari 67 baris. Ini adalah warning: field utang
  masih dapat lolos jika grounded walau pemeriksaan posisi baris tidak berjalan.
- **TRIN Q1 2022:** CSV melaporkan `utang_bank=359.124.216.000`. Halaman 6 PDF menamai
  angka 359.124.216 (dalam ribuan Rupiah) sebagai pinjaman lembaga keuangan **non-bank**;
  artinya nilai tersebut tidak memenuhi definisi utang bank. Kesalahan ini menunjukkan
  bahwa grounding angka tidak membuktikan klasifikasi labelnya.
- **RCCC Q1 2024:** CSV tidak mengisi `total_share`; halaman 32 PDF menampilkan jumlah
  saham ditempatkan/disetor dan total kepemilikan sebesar 750.000.000. Text layer
  memecah angka total menjadi `7 50.000.000`, kemungkinan menggagalkan pencarian tabel
  saham yang mengharapkan grup angka utuh.
- Keempat emiten belum ada di `data/ground_truth/`. Jangan memasukkan CSV lama sebagai
  ground truth; buat label independen dari PDF sebelum mengukur akurasi. Workbook tidak
  diubah.

### CP11: Menutup dua kegagalan generalisasi yang terkonfirmasi (2026-10-08)
- Diagnosis saat itu menyebut nilai pada baris “Utang Bank dan Lembaga Keuangan Non-Bank”
  sebagai salah. Ini dikoreksi pada CP15: baris tersebut valid karena definisi lapangan
  mencakup pinjaman dari lembaga keuangan non-bank. Validasi harus membedakan bagian
  lancar dan sisa jangka panjang, bukan menolak baris gabungan pemberi pinjaman.
- Akar masalah RCCC Q1 2024: `page_select.py` mengharuskan hitungan saham minimal 1 miliar
  dan tidak menangani pemisahan `7 50.000.000`. Deteksi sekarang menerima hitungan mulai
  1 juta dan menggabungkan hanya digit awal yang terpisah, tanpa menggabungkan kolom
  angka di sebelahnya.
- Tes dan ekstraksi ulang belum dijalankan pada permintaan ini; perbaikan masih perlu
  dievaluasi terhadap korpus berlabel dan filing PURA/RCCC/TRIN/TRUK.

### CP12: Analisis variasi Q1/Q2 dan pindah base model (2026-10-09)
- Mengganti default `GEMINI_MODEL` di `.env.example`, `.env`, `src/llm.py`, dan fallback
  offline `run_eval.py` menjadi `gemini-3.5-flash-lite`; konfigurasi fallback produksi
  tetap tersedia. Parameter `temperature` dihapus dari request Gemini karena model 3.5
  mengabaikannya. API key kini disamarkan dari pesan error koneksi.
- Akar masalah konkret PURA Q1 2023 vs Q2 2023: kedua PDF punya tabel pemegang saham di
  halaman 50 dan total sahamnya 6.301.930.902; Q1 mencetak `104%` pada baris total,
  sedangkan Q2 mencetak `100%`. Detektor lama hanya menerima 100%, sehingga Q1 tidak
  menemukan halaman tabel dan `total_share` kosong. Persentase pemegang saham di Q1 memang
  tidak konsisten secara internal, tetapi jumlah saham pemilik menjumlah tepat ke angka
  total. `page_select.py` kini menerima 101–110% hanya pada baris total/jumlah dengan
  hitungan saham dan tanda persen. Tes memastikan 120% dan baris pemegang saham biasa
  tetap ditolak. Selector berhasil menemukan halaman 50 pada PDF Q1 dan Q2.
- CSV lama juga mencampur tiga kondisi: abstain eksplisit oleh confidence layer, field
  yang tidak dikembalikan model, dan field yang tidak pernah dicari karena halaman sumber
  terlewat. Kolom diagnostik baru di `pdf_to_csv.py` membedakan field kosong yang tidak
  di-abstain dan menyimpan alasan/angka yang ditahan untuk abstain eksplisit.
- TRIN Q1/Q2 punya baris gabungan “Utang Bank dan Lembaga Keuangan Non-Bank”; variasi
  text-layer dan keluaran model dapat membuat baris gabungan dibaca sebagai utang bank.
  Guard CP11 mengatasi klasifikasi ini; grounding angka saja tidak membuktikan label
  akuntansinya. Variasi Q1/Q2 juga dapat berasal dari halaman yang terpilih dan respons
  model yang tidak lengkap, bukan sekadar format PDF.
- Uji live empat filing 2023 pada 3.5 menunjukkan model dapat menjawab TRIN Q2 dengan 10/10
  field, tetapi run sengaja memakai base-only tanpa retry/fallback untuk isolasi dan
  terkena beberapa HTTP 503: TRIN Q1 3/10, PURA Q1 1/10, PURA Q2 8/10. Hasil itu bukan
  evaluasi kualitas yang sebanding; hanya mengonfirmasi endpoint/model bekerja sebagian.
  Belum ada evaluasi 3.5 di seluruh korpus berlabel.
- Verifikasi: dua tes selector terkait lulus; tes terarah `test_agent.py`, `test_usage.py`,
  `test_guards.py` awal: **103 passed**. Full suite sebelumnya: **184 passed, 1 failed**;
  satu kegagalan lama `test_labelaudit.py::test_the_screen_finds_the_gtra_shift_in_the_committed_labels`
  mengharapkan duplikat workbook GTRA yang tidak ada di ground truth pada HEAD. Tidak ada
  workbook ground truth yang diubah pada investigasi ini. Setelah patch selector, seluruh
  `tests/test_guards.py`: **52 passed**; `git diff --check` bersih.
- Catatan keamanan operasional: satu percobaan jaringan sandbox membocorkan API key
  Gemini pada diagnostic URL. Jangan gunakan ulang key tersebut; rotasikan di Google AI
  Studio. Redaksi error sudah ditambahkan dan diuji.

### CP13: Diagnosis CSV terbaru dan digit awal hilang di Markdown (2026-10-09)
- Membaca CSV terbaru PURA/RCCC/TRIN/TRUK (timestamp 9 Okt): **67 filing, 41 `ok`, 24
  `partial`, 2 `error`**. Total `missing_not_abstained` yang tampak terbanyak adalah
  `utang_bank` (9, seluruhnya TRIN), `total_share` (4), lalu field lain. Abstain eksplisit
  paling sering terjadi pada `kas_dari_aktivitas_operasi` (9), `kas` (5), dan `laba_bersih`
  (4); nilai yang ditahan menunjukkan model membaca angka berbeda dari PDF.
- Akar penyebab konkret abstain angka PURA: renderer Markdown tidak menggabungkan digit
  awal ketika kotak berikutnya dimulai separator, misalnya `1` + `.768.888.226` dan `5` +
  `.142.595.662`. Digit berpindah ke label, nilai dalam kolom angka menjadi salah, dan
  confidence lalu menahan angka yang tidak cocok dengan teks sumber. `pagemd.py` kini
  menggabungkan fragmen digit+separator bila kotaknya benar-benar bersentuhan, sebelum
  mengelompokkan kolom.
- Verifikasi lokal terhadap PDF PURA Q1 2023: renderer baru menghasilkan laba bersih
  `5.142.595.662` dan arus kas operasi `1.768.888.226` pada kolom periode berjalan; nilai
  komparatif juga tetap utuh. Ini memperbaiki input model, tetapi CSV eksternal belum
  diekstrak ulang.
- Dari 9 sel kosong `utang_bank` pada TRIN, 8 berada di filing `partial`; satu lagi ada
  di TRIN Q4 2024 yang gagal total karena gangguan provider. Baris current-maturity
  gabungan bank dan lembaga keuangan non-bank adalah nilai yang valid menurut koreksi
  definisi pengguna (lihat CP15). Selector tetap mengambil catatan utang sebagai bukti
  tambahan, tetapi subtotal tercetak pada neraca kini menang jika komponen catatan tidak
  lengkap. Ekstraksi ulang model belum dilakukan, jadi perbaikan pada 8 baris belum
  terkonfirmasi.
- Dua baris `error` (TRIN Q4 2024, TRUK Q4 2025) berasal dari 503 pada model Gemini,
  kuota harian habis di fallback, dan `qwen3-vl:8b` lokal belum terpasang. Itu bukan
  kegagalan pembacaan PDF.
- CSV eksternal belum ditulis ulang. Setelah API key dirotasi, perlu rerun agar perubahan
  renderer dan ekstraksi catatan bank muncul di hasil; kegagalan provider untuk dua filing
  `error` perlu ditangani dengan retry saat kuota/kapasitas tersedia.

### CP14: Urutan fallback Gemini (2026-10-09)
- Base tetap `gemini-3.5-flash-lite`; fallback kini mencoba `gemini-3.1-flash-lite`
  dahulu, baru `gemini-3.6-flash`, lalu 3.7 dan 3.8. Urutan diterapkan di `.env`
  lokal dan `.env.example`, dan dicatat di README.
- Test `test_configured_3_1_fallback_precedes_3_6` memastikan chain aktual mengikuti
  urutan tersebut selama model tidak sedang cooldown.

### CP15: Koreksi definisi utang TRIN (2026-10-09)
- Pengguna mengonfirmasi bahwa utang pada baris “Utang Bank dan Lembaga Keuangan
  Non-Bank” termasuk ke field `utang_bank`. Diagnosis CP11 yang menolak angka gabungan
  terlalu sempit: field mencakup pinjaman lancar dari bank maupun lembaga keuangan
  non-bank; utang non-keuangan, sewa, dan sisa jatuh tempo jangka panjang tetap dikecualikan.
- Validator kini menerima baris gabungan bila berada di bagian jatuh tempo yang benar.
  Prompt catatan utang mencakup lender bank dan finance company. Jika rincian lender pada
  catatan tidak lengkap, total tercetak di neraca mengalahkan jumlah komponen yang parsial.
- Menambahkan regresi untuk TRIN Q1 2022: 359.124.216 current maturity diterima, sedangkan
  211.178.167 pada bagian long-term tetap dikecualikan. CSV eksternal belum dijalankan ulang.

### CP16: Audit utang TRIN dari CSV terbaru (2026-10-09)
- Audit read-only atas 18 baris di `~/FinancialReport/TRIN/TRIN.csv` dan baris neraca pada
  seluruh PDF pasangannya. CSV terbaru kini mengisi `utang_bank` di **18/18** filing,
  seluruhnya memakai `gemini-3.1-flash-lite`; 16 `ok`, 2 `partial` karena field lain.
- **16/18** nilai cocok dengan current-maturity bank + lembaga keuangan non-bank pada PDF
  setelah normalisasi ribuan Rupiah. Dua salah:
  - Q2 2022: CSV `1.181.480.574.000`, sedangkan current-maturity tercetak
    `590.740.287` (ribu Rupiah) = `590.740.287.000`. CSV tepat dua kali nilai PDF;
    baris tersebut tampaknya terpakai sebagai short-term sekaligus current-maturity.
  - Q2 2025: CSV `755.908.783.000`; PDF mencetak current-maturity `178.961.211` dan
    sisa pinjaman di bagian non-current `576.947.572` (ribu Rupiah). CSV adalah jumlah
    keduanya; sisa non-current harus dikecualikan, sehingga targetnya `178.961.211.000`.
- `section_map_incomplete` muncul pada **18/18** baris. Guard posisi utang saat ini tidak
  berhasil mengklasifikasikan bagian lancar vs non-current, sejalan dengan PDF TRIN yang
  memecah label, heading, dan angka ke beberapa baris teks. Ini membiarkan duplikasi dan
  salah klasifikasi Q2 2025 lolos meski angka-angkanya tercetak di PDF.
- Parser validasi kemudian diperbaiki di CP17 agar menggabungkan heading/label yang
  terbungkus dan membaca teks tanpa kondensasi. Hasilnya, seluruh 18 filing sekarang
  memiliki peta current-maturity dan long-term. Tidak ada API call atau perubahan pada
  CSV/PDF eksternal dalam audit ini.

### CP17: Memperbaiki salah klasifikasi komponen utang TRIN (2026-10-09)
- Akar masalahnya ada di dua lapis: kondensasi teks membuang kata di heading yang
  terbungkus; lalu validator hanya membaca label dan angka pada satu baris. Di TRIN,
  label lender, heading jatuh tempo, dan angka sering terpisah 2–3 baris, sehingga
  `section_map_incomplete` mematikan guard di semua filing.
- `assess()` kini memberi teks mentah ke validasi struktural (teks terkondensasi tetap
  dipakai untuk grounding). `_bank_rows_by_section()` menggabungkan konteks heading dan
  continuation baris, termasuk istilah Inggris. Peta current-maturity dan long-term
  lokal kini terbentuk pada 18/18 filing TRIN.
- Jika laporan tidak memiliki baris pinjaman jangka pendek terpisah dan komponen pendek
  model hanya cocok dengan baris current-maturity atau long-term, komponen itu dikoreksi
  menjadi nol dan total dibangun ulang dari current-maturity. Reproduksi lokal Q2 2022
  menghasilkan `590.740.287`; Q2 2025 menghasilkan `178.961.211` (sebelum scale ×1.000).
- Perlu menjalankan ulang ekstraksi CSV setelah API key tersedia/dirotasi agar dua nilai
  lama diperbarui. CSV eksternal sengaja tidak diubah langsung.
- Verifikasi lokal setelah perbaikan: `tests/test_guards.py`, `tests/test_api.py`,
  `tests/test_agent.py`, dan `tests/test_usage.py` lulus **121 test**; `git diff --check`
  dan `python -m compileall -q src` juga bersih. Tidak ada pemanggilan API/model.

### CP18: Diagnosis akar masalah evaluasi PURA/RCCC/TRIN/TRUK (2026-10-17)
Investigasi read-only: tanpa API call, tanpa perubahan kode/workbook. Bukti dari CSV
`~/FinancialReport/<T>/<T>.csv` (9 Okt), workbook baru, dan PDF sumber.
- **Ukuran masalah:** 67 filing → 46 `ok`, 13 `partial`, 8 `error`. Sel yang tidak
  terjawab: 80 (baris error) + 20 abstain + 9 kosong tanpa abstain = 109 dari 670.
- **Label baru = salinan CSV:** 660/668 sel identik dengan CSV, termasuk baris berstatus
  `error` yang nilainya diisi manual. Skor CSV vs label ini tidak mengukur extractor.
- **Kesalahan label terkonfirmasi PDF:** TRIN `total_share` 1000× terlalu kecil (tabel
  mencetak jumlah saham dalam ribuan lembar: 4.352.457 × Rp100 = 435.245.734 ribu Rp);
  TRIN Q2/Q4 2022 memakai saham ditempatkan, bukan beredar; RCCC Q4 2023 (8 sel) tidak
  ada di PDF, nilai CSV yang ada (aset 88.069.161.715 hal. 9); TRIN Q1 2026 `utang_bank`
  714.891.526 vs tercetak 714.891.426.
- **Abstain:** 13/20 menahan angka yang benar (presisi abstain 35%).
- **Akar A (per-halaman):** keputusan text-layer dibuat per filing/halaman secara kasar.
  (1) Halaman teks-judul + badan tabel berupa gambar (PURA Q4 2022 hal. 12, 14; Q4 2023
  hal. 10–14) dinilai `usable` → tidak di-OCR → grounding tanpa angka → 11 sel benar
  ditahan. (2) Halaman berhuruf-spasi parsial (PURA Q2 2025 hal. 55, single-char 53%)
  lolos `text_layer_shredded` → selector tabel saham gagal → `total_share` kosong.
  (3) Halaman shredded penuh (RCCC Q1 2026 hal. 5/6/8) tetap dirender `pagemd` dari
  glyph berspasi karena fallback markdown→image per filing (6/9 ≥ 60%) → prompt berisi
  `K a s d a n B a n k 4 3 2 3 .2 9 6 .3 3 8` → kas 4.323.296.338 (benar 323.296.338).
- **Akar B (validator utang):** `_bank_rows_by_section` memasukkan angka current-maturity
  ke daftar `long_term` (dari halaman catatan) dan cek long-term dijalankan dulu → TRIN
  Q2 2024/Q2 2025 benar tapi divonis `wrong_section`. Q1 2025/Q1 2026 model memilih baris
  non-current (heading hampir identik); validator benar menahan tetapi tidak memperbaiki.
- **Akar C (satuan jumlah saham):** `total_share` tidak pernah diskalakan; tabel
  "ribuan lembar" lolos grounding karena literal tercetak.
- **Operasional:** 8 filing error karena kuota harian semua model / 503; satu evaluasi
  mencampur 3.1/3.5/3.8 dan image fallback.
- **TRUK** (digit depan salah, 3 sel): prompt dari kode sekarang sudah benar
  (`1.887.952.152 | 2.584.479.521`); tidak terulang di tingkat input, perlu konfirmasi rerun.
- **Biaya:** PURA Q4 memasukkan halaman laporan auditor hasil scan ke grup statement
  (arus kas: 5 gambar, 13 MB).

### CP19: Perbaikan akar masalah CP18 dan evaluasinya (2026-10-17)
- **Kode (belum di-commit):**
  - `pdftext.page_needs_ocr`: halaman teks-judul di atas tabel gambar (gambar ≥20%
    halaman, ≤2 angka) dan halaman berhuruf-spasi parsial (≥25% baris) kini di-OCR.
    Sakelar `OCR_MIXED_PAGES=false` mengembalikan perilaku lama.
  - `pagemd.page_markdown` memakai teks OCR untuk halaman yang tidak terbaca (bukan
    tabel dari glyph); hitungan "halaman terbaca" untuk fallback gambar memakai aturan
    yang sama.
  - `validate.py`: angka yang juga tercetak di bagian current-maturity tidak lagi
    divonis non-current; `repair_current_maturity_from_long_term` mengganti nilai yang
    diambil dari baris non-current dengan kolom yang sama di baris current-maturity
    (hanya jika baris current-maturity tunggal).
  - `extract.py` mode text/markdown: panggilan grup yang gagal diulang sekali, lalu
    dicatat sebagai issue `group_call_failed` (RCCC Q2 2023 kehilangan 8 field tanpa jejak).
  - `fetch_share_prices.py`: jika tidak ada sesi ±12 hari dari tanggal 17, ambil sesi
    terdekat di bulan yang sama (`--no-month-fallback` untuk mematikan). Diuji ke Yahoo
    (read-only): 468 periode, 386 terisi, 82 kosong semuanya bulan sebelum listing,
    jadi fallback tidak mengubah data yang ada saat ini.
- **Evaluasi (replay offline, jawaban model dibekukan, tanpa API):** 289 filing / 2.796
  sel; sebelum vs sesudah dengan seleksi, OCR, validator, dan abstensi yang sama.
  **16 sel membaik, 0 memburuk**: benar 2.709 → 2.725; abstain-padahal-benar 36 → 23
  (PURA 11, TRIN 2); nilai salah yang kini diperbaiki repair 3 (TRIN Q1 2025, Q1 2026,
  AADI Q2 2025). Seleksi tabel saham kini menemukan halaman untuk GTRA Q1 2024, GTRA
  Q3 2025, TOTL Q1 2022 (efek ke jawaban model belum diukur). Replay tidak mengukur
  perubahan input ke model (RCCC Q1 2026, TRUK); itu perlu run ulang via API.
- **Tidak terselesaikan:** PURA Q2 2025 `total_share` -- OCR halaman 55 tidak memuat
  baris total jumlah saham, jadi selector tetap tidak menemukan tabelnya.
- **Label:** 25 sel non-`total_share` terbukti salah dari PDF (RCCC Q4 2023 kolom
  bergeser; salah ketik TRIN C8/I9/E4, PURA C5, TRUK D12; TRIN I12/E12 tanpa ×1000;
  TRUK Q2 2023 dilabel dari file Q1 yang identik). Edit workbook oleh agen diblokir
  pemeriksa izin; skrip `scripts/apply_label_corrections.py` (dry run default, `--apply`
  menulis dan menambah entri `CORRECTIONS.md`) disiapkan untuk dijalankan user.
- **Test:** suite penuh **210 passed** (termasuk `tests/test_mixed_pages.py` baru dan
  test harga saham); test GTRA shift kini menunjuk revisi `e02530d`.

### CP20: Ekstraksi ulang PURA/RCCC/TRIN/TRUK setelah CP19 (2026-10-17)
- Run: `run_eval.py --corpus --tickers PURA RCCC TRIN TRUK --corpus-root ~/FinancialReport
  --no-allow-fallback`, `gemini-3.5-flash-lite` markdown, 67 filing, 0 error provider, 284
  call, ~35.694 token input/filing. Scorecard
  `output/corpus_scorecard_gemini_gemini-3.5-flash-lite_markdown_PURARCCCTRINTRUK.json`.
- Terhadap label: 632/660 benar (95,8%), 23 salah, 5 terlewat, **0 abstain**.
- Setiap sel salah dilacak ke PDF: **16 label salah, model benar** (TRIN Q4 2024 ×8 label
  dari laporan entitas induk hal. 127–132, bukan konsolidasian; laba_bersih TRIN Q4 2022,
  Q4 2023, Q3 2024, Q4 2025 memakai laba total/sebelum pajak, bukan bagian pemilik entitas
  induk; total_share TRIN Q2/Q4 2022, Q4 2025 dan RCCC Q2 2023); **2 keduanya salah**
  (TRIN Q3 2025 laba: benar 28.483.202 ribu, model ambil kolom pembanding; TRIN Q4 2024
  utang_bank: benar 695.981.931 ribu konsolidasian, model 0); **5 model salah, label
  benar** (TRIN Q3 2022 kas digit liar "1"; TRIN Q1 2025 arus kas operasi tanda; TRIN Q3
  2025 pendapatan kolom pembanding; TRIN Q1/Q3 2022 total_share ambil kolom nilai modal).
- Jadi kesalahan model sebenarnya 7 dari 660 sel + 5 terlewat (laba_bersih PURA Q1 2025,
  Q1 2026, RCCC Q2 2025; arus kas TRIN Q4 2022; total_share PURA Q2 2025).
- Tidak sebanding apel-ke-apel dengan run 9 Okt: model berganti (3.1 → 3.5 untuk
  TRIN/PURA), label disalin dari run lama, dan 80 sel lama hilang karena kuota.
- Celah baru: 0 abstain berarti 7 jawaban salah lolos; kesalahan kolom pembanding (2)
  bisa dicegat dengan cek tanggal header geometri `pagemd` (sudah ada di `labelaudit`).

### CP21: Koreksi label TRIN batch 2 dan guard kolom pembanding (2026-10-17)
- **Label (belum diterapkan, menunggu `python scripts/apply_label_corrections.py --apply`):**
  15 sel TRIN -- Q4 2024 ×9 (label dari laporan entitas induk hal. 127–132, diganti
  angka konsolidasian hal. 11–17), `laba_bersih` Q4 2022/Q4 2023/Q3 2024/Q3 2025/Q4 2025
  (label memakai laba total atau sebelum pajak), dan arus kas operasi Q2 2023 (label
  -66.612.336 adalah H1 2022; benar -230.537.354 ribu). Bukti di
  `scripts/label_corrections_2026-10-17b.md`. Skrip kini idempoten; pengosongan TRUK
  Q2 2023 dari batch 1 dihapus agar label baru user tidak terhapus.
- **Guard kolom pembanding** (`validate.repair_comparative_columns`, dipanggil lewat
  `extract._apply_comparative_column_guard` di jalur markdown/teks, gambar, dan agen
  sebelum `derive_fields`): kolom berjalan dari baris header yang hanya berisi tahun
  ("Notes 2025 2024"); diperbaiki hanya jika SETIAP kemunculan angka berada di baris
  yang kolomnya bisa ditentukan, selalu di kolom pembanding, dan nilainya ≥10.000.
- **Evaluasi (replay prediksi asli, guard on vs off):** versi pertama +2/−6 (judul
  bilingual PTBA/TOTL membalik urutan tahun; tanda hilang pada "( 230.537.354)");
  versi kedua +3/−1 (kebetulan angka LSIP NCI); versi final **+2/−0** (4 emiten baru:
  TRIN Q2 2023 arus kas operasi, TRIN Q3 2025 pendapatan; 14 emiten lama: tidak ada
  perubahan). TRIN Q3 2025 `laba_bersih` sengaja tidak diperbaiki (bukti tidak satu sisi).
- **Test:** suite penuh **216 passed**.

### CP22: Menutup kesalahan model TRIN dan sel yang tak terjawab (2026-10-17)
- **Kode:**
  - `page_select.classify_pages`: bila tak ada halaman berjudul arus kas, halaman dikenali
    dari isinya ("arus kas dari aktivitas" + investasi/pendanaan). TRIN Q4 2022 mencetak
    judul catatan di halaman arus kasnya. Pindai 290 filing: aktif hanya di TRIN Q4 2022.
  - `prompts.py` aturan NO SPLIT `laba_bersih`: tanpa blok atribusi (tanpa anak usaha),
    laba periode berjalan = bagian pemilik. TRAP lama melarang baris itu sehingga model
    menjawab null.
  - `validate.repair_printed_signs`: balik tanda hanya jika semua kemunculan berada di
    kolom berjalan, bertanda berlawanan, dan barisnya memakai kurung untuk negatif.
  - Aturan "utang bank 0 padahal baris current-maturity tercetak" **dicoba lalu dihapus**:
    +2/−7 di replay; peta seksi validator memasukkan pinjaman jangka panjang ADMR hal. 5
    ke current_maturity (jendela konteks 4 baris). Kebocoran peta itu masih terbuka.
- **Evaluasi:**
  - Replay (prediksi asli, baseline tanpa perbaikan hari ini): 4 emiten baru **+3/−0**
    (TRIN Q2 2023 & Q1 2025 arus kas operasi, Q3 2025 pendapatan); 14 emiten lama tanpa
    perubahan (ADMR/TRIN diulang setelah aturan nol dihapus: +3/−0).
  - Run API 4 filing (3.5-flash-lite, tanpa fallback): `laba_bersih` PURA Q1 2025,
    Q1 2026, RCCC Q2 2025 kini benar (10/10 masing-masing); TRIN Q4 2022 arus kas kini
    dijawab (-143.820.184 ribu) dan PDF + filing Q4 2023 menunjukkan model benar --
    labelnya adalah subtotal aktivitas investasi.
- **Label batch 2 kini 16 sel TRIN** (tambah Q4 2022 arus kas operasi); belum diterapkan.
- **Test:** suite penuh **218 passed**.
- **Sisa kesalahan model TRIN:** Q3 2022 kas (digit liar "1"), Q3 2025 laba (kolom
  pembanding, guard menolak karena bukti tidak satu sisi), Q4 2024 utang_bank 0, dan
  total_share kolom nilai modal (menunggu review satuan).

### CP23: Ekstraksi ulang setelah CP22 dan dua pengaman tambahan (2026-10-17)
- **Run asli** (`run_eval --no-cache`, 3.5-flash-lite markdown, 67 filing, label batch 1+2
  sudah diterapkan): 659/669 benar (98,5%), sebelumnya 652/669 dengan label yang sama.
  Snapshot hasil run: `output/scorecard_NAMA.json`.
- **Per sel tanpa total_share TRIN/RCCC Q2 2023 (650 sel), baseline = replay prediksi
  lama:** 639 → 645 benar; **8 membaik, 2 memburuk**. Membaik: laba_bersih PURA Q1 2025,
  Q1 2026, RCCC Q2 2025 (aturan NO SPLIT); arus kas TRIN Q4 2022 (pemulihan halaman),
  Q2 2023 (guard kolom), Q1 2025 (tanda); TRIN Q3 2025 pendapatan; TRIN Q4 2024 utang_bank.
  Memburuk (kesalahan baru model): RCCC Q4 2022 kas (dua kolom satu baris dijumlahkan),
  TRIN Q2 2022 utang_bank (neraca dijawab 0, komponen catatan negatif).
- **Dua pengaman baru:** `validate.repair_components_across_columns` (komponen kas yang
  sama persis dengan dua kolom satu baris → ambil kolom tahun berjalan) dan
  `derive_fields`: jawaban neraca 0 tidak mengalahkan jumlah komponen catatan > 0.
  Replay: 4 emiten **+2/−0** (hasil 647/650 benar), 14 emiten lama **0/0**.
- `compare_runs` tidak bisa dipakai untuk run ini: salinan baseline tidak pernah dibuat
  karena `run_eval` keluar dengan kode 1 bila ada sel salah sehingga `cp` setelah `&&`
  tidak jalan. Gunakan `;` saat menyalin scorecard.
- Sisa salah (non-total_share): TRIN Q3 2022 kas (digit liar "1"), TRIN Q3 2025
  laba_bersih (kolom pembanding, guard menolak). Terlewat: PURA Q2 2025 total_share.
- Temuan terbuka: `numfmt._SPLIT_LEAD` menggabungkan nomor catatan "9" dengan angka di
  peta validator TRUK ("Utang bank 9 5.882.925.347" → 95.882.925.347); peta seksi
  validator (jendela 4 baris) memasukkan pinjaman jangka panjang ADMR ke current_maturity.
- **Test:** suite penuh **220 passed**.

### CP24: Siklus perbaikan 1 -- digit yang dicetak terpisah (2026-10-17)
- **Akar masalah:** `numfmt._SPLIT_LEAD` / `repair_digit_gaps` menggabungkan digit tunggal
  dengan angka setelahnya di tingkat teks, padahal teks tidak membedakan angka terbelah
  (GTRA "1 7.149.123.737", kotak bersentuhan) dari token terpisah (TRIN Q3 2022 "1" 35 pt
  sebelum kas 77.250.439; nomor catatan TRUK "2,8&9 7.008.790.794"). Survei arsip:
  5.711 pasangan ≤0,6 pt, 1.661 >10 pt, 0 di antaranya.
- **Perbaikan:** `pdftext.mark_separated_digits` menulis dua spasi untuk pasangan yang
  terpisah >3 pt; `numfmt` hanya menggabung satu spasi; `validate.repair_separated_lead_digits`
  mengembalikan nilai model yang menempelkan digit terpisah ke angka yang tercetak.
- **Evaluasi (replay semua emiten):** 4 emiten baru **+1/−0** (TRIN Q3 2022 kas);
  14 emiten lama **0/0**. Test terkait 111 passed.

### CP25: Siklus perbaikan 2 -- peta seksi validator utang (2026-10-17)
- **Akar masalah (3 bug di `validate._bank_row_amounts` / regex):** (1) jendela konteks 4
  baris memasukkan baris berangka, sehingga "Pinjaman dari pihak berelasi - current
  portion 5,235,602" (baris data) membuat "LIABILITAS JANGKA PANJANG" terbaca current
  maturity di ADMR; (2) regex "current portion/liabilities" cocok dengan "non-current";
  (3) baris bank yang sudah berangka tetap menyerap angka baris berikutnya (ADMR
  menyerap liabilitas imbalan pascakerja).
- **Perbaikan:** judul seksi hanya dari deretan baris tanpa angka (maks 5); baris
  berangka tidak pernah mengganti seksi; "non-current" dikecualikan; baris lanjutan hanya
  dibaca bila baris bank belum berangka.
- **Evaluasi (replay):** 4 emiten baru **0/0**; 14 emiten lama **+1/−0** (TLDN Q4 2022
  utang_bank). Test terkait 86 passed.

### CP26: Siklus perbaikan 3 -- guard kolom & nihil utang bank (2026-10-17)
- **3a** `repair_comparative_columns`: kemunculan di baris lebar (≥4 angka) pada halaman
  tanpa header tahun -- laporan perubahan ekuitas, kolomnya komponen bukan periode --
  tidak lagi memblokir perbaikan. TRIN Q3 2025 laba (28.483.202 ribu) kini terperbaiki.
- **3b** aturan `bank_row_ignored` (jawaban 0 padahal baris current-maturity tercetak)
  dipasang lagi setelah peta seksi diperbaiki (CP25); tidak ada efek samping lagi.
- **Evaluasi (replay):** 4 emiten baru **+1/−0** → 649/650 sel benar (sisa: PURA Q2 2025
  total_share tidak terjawab); 14 emiten lama **0/0**.

### CP27: Siklus perbaikan 4 -- dua bacaan OCR untuk grounding (2026-10-17)
- **Akar masalah:** TOTL (text layer shredded → OCR) menahan 6 angka benar karena OCR
  300 dpi salah baca (2.428.785.813 → 2.428.185.813; pemisah hilang di 847.433.444 dan
  1.793.562.796; baris laba entitas induk hilang).
- **Percobaan 1 (ganti OCR ke 400 dpi --psm 6):** +6/−8 -- memperbaiki TOTL tetapi
  merusak 8 angka lain. Ditolak.
- **Perbaikan:** dua bacaan OCR per halaman. Bacaan utama (300 dpi, layout default, cache
  "full" lama) tetap yang dilihat model; bacaan alternatif (400 dpi, psm 6, cache
  terpisah) dibawa sebagai `pdftext.OCRText.alternate` dan ditambahkan ke teks grounding
  di `extract.assess`. Kurs USD tidak berubah (65/65 filing sama).
- **Evaluasi (replay):** 4 emiten baru **0/0**; 14 emiten lama **+6/−0** (TOTL).

### CP28: Siklus perbaikan 5 -- komponen utang dari baris non-pinjaman (2026-10-18)
- **Penelusuran 7 sel utang_bank salah di 14 emiten lama:** 5 label salah (AADI Q4 2024,
  ADMR Q1 2026, ADMR Q2 2025, CPIN Q4 2024, TLDN Q3 2023: label menambah pinjaman jangka
  panjang / sewa / imbalan kerja, atau mengambil kolom pembanding CPIN yang mencetak tahun
  berjalan di KIRI nomor catatan); ADMR Q2 2026 label dan model sama-sama salah; LSIP
  Q3 2025 model salah (utang pajak dilaporkan sebagai utang bank).
- **Perbaikan:** `validate.repair_non_bank_component` membuang komponen yang hanya tercetak
  di baris liabilitas non-pinjaman (sewa, pajak, imbalan, usaha, royalti, provisi, kontrak,
  akrual) bila komponen lain berasal dari baris bank (ADMR Q2 2026 → 214.671); aturan
  `non_bank_row` (ERROR) menahan jawaban bila tak ada komponen bank yang sah (LSIP).
- **Evaluasi (replay):** 14 emiten lama **+1/−0** (LSIP Q3 2025 wrong → ditahan); ADMR Q2
  2026 baru terhitung benar setelah label diperbaiki. 4 emiten baru 0/0. Test 89 passed.
- **Label batch 3 (USULAN, 6 sel):** `scripts/label_corrections_2026-10-18_batch3.md`;
  hanya diterapkan dengan `python scripts/apply_label_corrections.py --apply --batch3`.

### CP29: Siklus 6 -- total_share yang tak terjawab & baseline replay bersih (2026-10-18)
- Replay: faktor skala kini diambil dari nilai IDR pipeline (`_derived.idr_values`), karena
  pipeline mengoreksi skala model dari header. 18 sel ARCI Q2 2024/Q2 2026 yang tampak salah
  ternyata artefak replay. Baseline bersih 14 emiten lama: **2.210/2.229 benar**, 8 salah.
- 6 total_share terlewat di cache lama (JPFA Q1–Q3 2022, GTRA Q1 2024, GTRA Q3 2025, TOTL
  Q1 2022): selector kini menemukan tabel sahamnya. Run API (3.5-flash-lite, tanpa
  fallback): GTRA ×2 dan TOTL **kini benar (10/10)**. JPFA 2022 ×3 menjawab saham beredar
  11.620.308.701 (hal. 127 "Total saham beredar"; treasuri 106.266.500); label memakai
  total ditempatkan 11.726.575.201 → label tidak sesuai aturan CP1. **Tidak diubah**:
  menunggu review total_share user.

### CP30: Siklus 6b -- sisa kesalahan di 14 emiten lama adalah label (2026-10-18)
- ADMR Q2 2022 kas: model 368.217.029 USD (neraca hal. 6 = saldo akhir arus kas hal. 11)
  benar; label = kas + 56.998.564 = total PIUTANG USAHA catatan 7 (jebakan kas_components
  dari pipeline lama). Ditambahkan ke batch usulan 3 (kini 7 sel).
- EMAS Q3/Q4 2025 total_share "ditahan" di replay adalah artefak: replay memanggil
  `derive_fields` dua kali pada prediksi yang sudah diturunkan (treasuri terkurang dua kali);
  pipeline asli menurunkan sekali.
- **Status:** 4 emiten baru 649/650 sel benar (sisa PURA Q2 2025 total_share). 14 emiten
  lama: semua sisa salah = label (batch 3) atau total_share yang menunggu review.

### CP31: Siklus 7 -- tabel saham PURA Q2 2025 (2026-10-18, sebagian terukur)
- **Akar masalah:** tabel pemegang saham hal. 55 diketik per glyph; OCR mempertahankan
  pemegang dan baris "100%" tetapi kehilangan jumlah saham total, sehingga selector (butuh
  jumlah saham di samping 100%) tidak pernah membentuk grup share_capital.
- **Perbaikan:** (1) `page_select._shareholder_table_without_total_count`: selector cadangan
  hanya bila aturan utama tidak menemukan apa pun (judul modal saham + pemegang saham +
  baris 100% + ≥2 baris jumlah-dengan-persen). Pindai 290 filing: aktif hanya di PURA Q2
  2025 (hal. 55). (2) `extract.extract_group_from_images`: di mode markdown, grup yang
  SEMUA halamannya butuh OCR dibaca dari gambar (sakelar `GROUP_IMAGE_FALLBACK`, default on).
  Pindai: 24 filing terpengaruh (JPFA ×12, PURA ×9, GTRA ×2 share_capital; RCCC Q4 2025
  cash_flow).
- **Evaluasi (run API, 3.5-flash-lite, on vs off):** 14 filing selesai (GTRA ×2, JPFA ×12):
  **137/140 vs 137/140, 0 perubahan**, token setara. 10 filing (PURA ×9, RCCC Q4 2025)
  terhenti: kuota harian 3.5-flash-lite habis. Target (PURA Q2 2025) **belum terukur**.

### CP32: Iterasi 8 -- jalur gambar per grup diukur dan dimatikan; guard kolom modal (2026-10-18)
- **Pengukuran CP31 (kuota pulih), 10 filing PURA ×9 + RCCC Q4 2025, 3.5-flash-lite:**
  tanpa gambar **99/100**, dengan gambar **92/100**: dari gambar model membaca kolom NILAI
  MODAL (315.096.545.100 = 6.301.930.902 lembar × Rp50) di 7 filing PURA yang benar lewat
  teks OCR; 1 lagi jadi kosong; target PURA Q2 2025 tetap tidak benar. Ditambah 14 filing
  netral (CP31) → `GROUP_IMAGE_FALLBACK` kini **default off** (kode tetap ada, terdokumentasi).
- **Akar masalah total_share = nilai modal:** baris tabel pemegang saham mencetak
  jumlah lembar, persentase, nilai Rupiah ("Total 6.301.930.902 100% 315.096.545.100");
  kedua angka tercetak sehingga grounding lolos. Kesalahan sama di TRIN Q1/Q3 2022.
- **Perbaikan:** `validate.repair_share_amount_column` -- field saham yang sama dengan angka
  SESUDAH persentase di baris seperti itu diganti dengan angka SEBELUM persentase; membaca
  bacaan OCR utama dan alternatif. Diuji pada filing asli: PURA Q2 2025 & Q1 2024 →
  6.301.930.902; TRIN Q1 2022 → 4.199.754, Q3 2022 → 4.205.476 (satuan TRIN tetap menunggu
  review user).
- **Evaluasi:** replay penuh **0/0** (14 emiten lama dan 4 emiten baru tidak berubah); test
  **229 passed**. PURA Q2 2025 total_share masih kosong di jalur teks (OCR utama memecah
  baris total; selector cadangan menemukan halamannya, model tetap tak menjawab).

### CP33: Label batch 3 diterapkan user (2026-10-18)
- `python scripts/apply_label_corrections.py --apply --batch3`: 7 sel (AADI Q4 2024, ADMR
  Q1 2026 / Q2 2026 / Q2 2025 utang_bank dan Q2 2022 kas, CPIN Q4 2024, TLDN Q3 2023);
  entri tercatat di `CORRECTIONS.md`.
- Replay ulang dengan label baru: 14 emiten lama **2.210 → 2.217/2.229 benar**, +7/−0.
  Sisa: 1 salah (LSIP Q4 2024 total_share, menunggu review), 3 ditahan-dan-memang-salah,
  6 total_share kosong di cache lama (GTRA ×2 & TOTL sudah benar di run baru; JPFA 2022
  ×3 = label ditempatkan vs beredar, menunggu review), 2 artefak replay EMAS.
- 4 emiten baru tetap 649/650.

### CP34: Pengunduhan IDX & penataan file berdasarkan isi (2026-11-01)
- IDX menolak permintaan skrip: endpoint `GetFinancialReport` dan path PDF statis
  `Portals/0/StaticData/...` sama-sama menjawab 403 Cloudflare ("Just a moment...").
  Tidak diakali; pengunduhan dilakukan di browser.
- `scripts/organize_filings.py`: menata PDF hasil unduhan menjadi `<Q>_<YYYY>_<TICKER>.pdf`
  berdasarkan ISI (judul laporan di halaman awal; periode = tanggal akhir kuartal terbaru di
  header halaman laporan, OCR bila perlu), menolak duplikat lewat SHA-1 (terhadap arsip dan
  batch), tidak menimpa file berbeda tanpa `--overwrite`, nama file hanya petunjuk ticker,
  ukuran hanya dicatat. Dry run default; manifest CSV. Uji: salinan Q1 bernama "-II-"
  dikenali Q1; duplikat ditolak; PURA Q4 scan terbaca 31 Des 2023. 4 test baru lulus.
- Klarifikasi user: satuan `total_share` tidak mengikuti header; label TRIN benar.

### CP35: organize_filings -- kode perdagangan tercetak & arsip ELSA tercampur (2026-11-01)
- Dry run `--ticker ELSA` pada `~/Downloads/idx` (38 PDF: 19 Elnusa, 19 AKR Corporindo, 10 di
  antaranya bernama acak) membuka tiga cacat:
  1. Regex ticker di nama file memakai upper-case dulu, sehingga "Sept"/"Juni"/id acak
     dianggap ticker. Sekarang hanya 4 huruf kapital berdiri sendiri, case-sensitive.
  2. Perusahaan acuan per ticker ditentukan voting mayoritas; seri 19–19 memilih AKR untuk
     ELSA. Atas saran user, sekarang bukti terkuat adalah **kode perdagangan yang tercetak di
     PDF** (Elnusa: `kode perdagangan "ELSA"`, hal. 10 kuartalan / hal. 19–20 tahunan; masuk
     25 halaman yang sudah dibaca). Urutan: tercetak > nama file > mayoritas; seri = konflik.
     PDF yang mencetak kode lain dari `--ticker` dilewati. AKR tidak mencetak "AKRA" di 40
     halaman pertama, jadi kode yang tidak ada bukan bukti apa pun.
  3. Regex tanggal membaca melewati ganti baris: header kolom "December 31," + baris
     "2022 Notes 2021" dibaca 31 Des 2022, sehingga laporan Elnusa Juni 2022 dianggap Q4 2022.
     Tanggal kini tidak boleh melintasi baris.
  Juga: target yang sudah ada dibandingkan isinya (perusahaan+periode sama → skip, beda →
  konflik). `_check_dependencies` memberi perintah install untuk interpreter yang dipakai.
- Hasil dry run akhir ELSA: 19 file AKR → konflik (tidak di-file); 14 Elnusa → skip
  (duplikat SHA-1 dari yang sudah diarsip); 5 Elnusa → konflik karena slotnya berisi AKR.
- **Temuan arsip:** `~/FinancialReport/ELSA/` Q1_2024, Q2_2022, Q3_2024, Q4_2023, Q4_2025
  berisi laporan **PT AKR Corporindo Tbk**, bukan Elnusa. Kemudian (13:44) user sendiri
  menghapus folder ELSA dan mengunduh ulang (76 PDF di `~/Downloads/idx`).
- Audit arsip (nama vs isi, 301 PDF): 298 cocok; TRUK Q1–Q3 2022 terbaca Q4 karena emiten
  salah cetak header kolom pembanding versi Inggris "December 31, 2022" (versi Indonesia
  "31 Desember 2021"). Aturan "baris judul" (per/tanggal/as of) sempat dicoba, tetapi
  membuat PURA Q4 2025 terbaca Q4 2024 (judul PURA tanpa kata itu; kalimat catatan
  "tahun yang berakhir 31 Desember 2024" lolos). Aturan final: **tanggal yang paling sering
  muncul** di 12 baris header halaman laporan (seri → terbaru). Cek 7 kasus: PURA Q4 2025
  20/22, TRUK Q1–Q3 2022 25/29, TRUK Q4 2022 16/16, Elnusa Jun 2022 14/14, PURA Q4 2022 12/16.
- **Daftar emiten** `data/issuers.json` dari dua sumber (`scripts/fetch_issuers.py`):
  - Excel resmi IDX "Daftar Saham" yang diunduh user di browser (`--idx-excel`, 962 emiten per
    2026-11-01): menentukan ticker & nama terkini; nama dipotong 30 karakter (dicocokkan
    dengan awalan, 114 nama terpotong semuanya kembali ke tickernya sendiri).
  - Wikipedia ID lewat MediaWiki API (941 emiten, revisi 29432526, per 2024-12-02): sektor,
    nama lama sebagai alias, emiten yang sudah tidak terdaftar (`in_idx_list: false`).
  - Hasil merge 976 entri: 35 emiten baru, 23 ganti nama (sebagian salah ketik Wikipedia),
    14 tidak lagi terdaftar. IDX sendiri diblok Cloudflare untuk skrip; tidak diakali.
  - `data/issuers_extra.json` (manual): alias ADMR "Adaro Minerals" (13 filing memakai nama
    lama); AADI/EMAS kini sudah ada di Excel IDX.
  - Semua 19 ticker arsip + AKRA + DOID (nama lama & baru) terpetakan dari nama di PDF.
    Urutan bukti: kode tercetak > daftar IDX > nama file > mayoritas. PDF milik emiten lain
    di-skip dengan menyebut tickernya; tanpa `--ticker`, folder campuran bisa dipilah.
- Bug `--overwrite`: sebelumnya mengubah SEMUA konflik jadi copy (termasuk konflik
  perusahaan tanpa target → tersalin ke folder kerja). Kini hanya target berisi dokumen lain.
- Jebakan `--move` tanpa `--apply`: user menjalankan `--ticker ELSA --move`, tetap dry run,
  folder ELSA tidak terbentuk. Kini `--move`/`--overwrite` tanpa `--apply` ditolak (exit 2)
  dengan pesan jelas.
- PGAS Q4 2023 (`FS PT PGN Tbk 31 Des 2023_Released.pdf`) tadinya di-skip "no period":
  teks PDF-nya keluar tanpa spasi ("LAPORANPOSISIKEUANGAN", "TANGGAL31DESEMBER2023").
  Regex judul kini `\s*`; regex tanggal memakai daftar nama bulan (bukan sembarang huruf,
  agar "ASOFDECEMBER31" tetap Desember) dan `(?<!\d)` sebelum hari. Tes baru: 17 passed.
  Audit ulang arsip setelah user memilah semua emiten: 411 PDF periode & emiten 411/411,
  ditambah PGAS Q4 2023 yang dipindah user setelahnya (Q4 2023, PGN) → 412/412.
- Audit ketiga (282 PDF, setelah daftar emiten): periode 281/282, emiten 263 ok / 18 tidak
  dikenal / 1 salah. Tiga akar masalah, semuanya di script:
  1. PURA Q3 2025 → Q4 2024: halaman catatan yang menyebut "laporan posisi keuangan" di
     badan teks ikut dihitung, dan catatannya mengutip "31 Desember 2024" berulang. Kini
     hanya halaman yang JUDULNYA (8 baris pertama) judul laporan yang menentukan periode.
  2. LSIP Q3 2022 → SIMP: "PT … Tbk" pertama di dokumen adalah induk usaha (catatan
     "Entitas Induk"). Nama emiten kini diambil dari 4 baris teratas halaman laporan, dan
     tidak boleh melintasi "PT" kedua (Elnusa: "PT ELNUSATBKDAN ENTITAS ANAKNYA PT ELNUSA TBK").
  3. 18 LSIP tidak dikenal: nama resmi "Perusahaan Perkebunan London Sumatra Indonesia";
     IDX menyingkat "PP". Ditambah sebagai alias di `issuers_extra.json`.
- **Audit final (282 PDF): periode 282/282 cocok, emiten 282/282 cocok.**
- Dry run final `--ticker ELSA` pada `~/Downloads/idx` (kini 130 PDF: ELSA, AKRA, ENRG, ESSA,
  PGAS, MEDC, APEX): 19 Elnusa → copy (Q1 2022–Q3 2026 lengkap), 111 skip dengan alasan
  emiten lain. Satu PDF PGAS (`FS PT PGN Tbk 31 Des 2023_Released.pdf`) tidak terbaca
  periodenya ("no period date in their headers") -- perlu dicek kalau PGAS diarsipkan.
  Alias ESSA "Surya Esa Perkasa" (8 filing 2022–2023) ditambahkan.
- Test organizer: 14 passed, 2 skipped (fixture ELSA di arsip sudah dihapus user).

### CP36: Kurs emiten USD -- MEDC terbaca, ENRG/PGAS/ESSA/APEX tidak mengungkap kurs (2026-11-01)
- User menjalankan `pdf_to_csv.py` untuk ELSA, AKRA, MEDC, ENRG, PGAS, APEX, ESSA. Semua
  arsip sudah dipilah user (25 emiten, 412 PDF; PGAS lengkap 19).
- 5 dari 7 emiten lapor dalam USD: MEDC, ENRG, PGAS, ESSA, APEX. ELSA (jutaan Rupiah) dan
  AKRA (ribuan Rupiah) tidak butuh kurs.
- MEDC gagal "no exchange rate is disclosed": barisnya `Rupiah/AS$1 0,000060 0,000062`
  (dolar per SATU Rupiah, tanpa satuan 1.000), ada di 18/18 filing. `_rate_from_line`
  kini mengenali satuan "Rupiah/AS$1" (`_PER_ONE_RUPIAH`). Terukur: Q1 2025 16.666,67 (p36),
  Q4 2023 15.384,62 (p48), Q2 2026 17.857,14 (p57). Presisi hanya 2 angka penting →
  ketidakpastian pembulatan ±0,77–0,89%, dan warning itu ikut ke kolom notes.
- ENRG, PGAS, ESSA, APEX: pindai 74 filing (70 halaman pertama) dan seluruh halaman Q1 2025:
  tidak ada baris kurs akhir periode. Satu-satunya angka di ENRG adalah Rp14.572/USD dari
  PUT III 2021 (bukan kurs periode) dan tidak terpakai. Konversi untuk keempatnya ditolak
  dengan benar; perlu keputusan user (lihat Pekerjaan tertunda 0b).
- Pemborosan: `pdf_to_csv.extract_row` memanggil LLM dulu (4-5 call), lalu membuang semua
  nilai kalau konversi kurs gagal. Belum diubah.
- Test: `test_guards` 59 passed; seluruh suite 247 passed.
- Kurs BI sebagai cadangan (permintaan user): `normalize.reference_fx_rate` +
  `fx_for_filing` (kurs filing bila ada; kurs tengah BI akhir kuartal bila tidak ada;
  kurs filing yang terlalu kasar diganti BI HANYA bila BI berada di dalam rentang
  pembulatannya). `pdf_to_csv` memakainya untuk filing USD; `fx_source` =
  `bi_middle_rate` / `bi_middle_rate_within_filing_rounding`. Eval (`evalkit`) TIDAK diubah.
  Tes baru 2 (6 tes kurs passed).
- `scripts/fetch_fx_rates.py`: web service BI `wskursbi.asmx/getSubKursLokal3` (kurs
  transaksi; tengah = (beli+jual)/2, fixing terakhir ≤ akhir kuartal). Terukur:
  2021-12-31 = 14.269,01 (cocok dengan "14,269" ITMG); 27-03-2025 = 16.588,00. Server
  me-reset koneksi Python setelah request pertama, juga dengan jeda 90 dtk + retry →
  dihentikan, tidak diakali. `data/fx_rates_bi.csv` BELUM ADA. Jalur berikut: user
  mengunduh Excel Kurs Transaksi BI (USD) dari bi.go.id, lalu reader Excel ditambahkan.

### CP37: Tabel kurs BI dari Excel user; ENRG/PGAS ternyata mencetak kurs (2026-11-02)
- Klaim CP36 "ENRG, PGAS tidak mencetak kurs" SALAH: keduanya mencetak
  `1 Dolar AS/Rp 16.588,00 16.162,00` / `1 dolar AS/Rupiah (nilai penuh) 16.566 16.157`
  (format dolar-dulu dengan garis miring) yang tidak dikenali `_DIRECT_QUOTE`. Pindaian CP36
  hanya mencari pola yang sudah ada. Ditemukan lewat pindaian pypdfium2 seluruh 412 PDF
  untuk semua baris USD+angka 13.000–17.999 (scratch, 2 mnt).
- `_DIRECT_QUOTE` kini mengenali `1 <dolar> AS/Rp|Rupiah` dan `US Dolar 1/Rp`, spasi
  opsional (PGAS Q4 2023 terbaca "1dolarAS/Rupiah(nilaipenuh) 15.439"). `_SPLIT_RATE`
  menyambung "1 6.588,00" (pdfplumber memecah angka ENRG karena kerning) di baris kurs
  langsung saja. Harga PUT III ENRG "Rp14.572 per USD 1" tetap tidak terbaca sebagai kurs.
- Terukur dengan `extract_fx_rate`/`fx_for_filing`: PGAS 19/19 memakai kurs sendiri
  (mis. Q1 2025 16.566, Q1 2024 15.873 -- BERBEDA dari BI 16.588/15.853, jadi kurs filing
  memang harus diutamakan). ENRG: 11/19 kurs sendiri; 8 sisanya (Q1 2023, Q1 2026, Q2 2024,
  Q2 2026, Q3 2022, Q3 2024, Q3 2026, Q4 2025) jatuh ke kurs BI dengan catatan. Untuk yang
  dicek, angka ENRG sama dengan BI (mis. Q4 2025 "16.782,00").
- ESSA, APEX (36 filing) memang tidak mencetak kurs -> kurs BI (terukur 36/36). Jebakan:
  ESSA Q4 2025, Q1 2026, Q2 2026 sempat mengambil `derived_from_pair` 9.670,24 dari
  "Rp 245.520.000.000 (setara dengan US$ 25.389.223)" (pengalihan saham 2017). Kini
  `fx_for_filing` mengutamakan kurs BI atas pasangan Rp/US$ bila BI tersedia, dan
  pasangan yang diabaikan ditulis di notes. MEDC 18/18 `bi_middle_rate_within_filing_rounding`.
- Website/web service BI tidak bisa diakses user maupun script; user mengunduh Excel
  `~/Downloads/Kurs Transaksi USD  .xlsx` (1.181 fixing, 1 Des 2021 – 30 Okt 2026; kolom
  Nilai, Kurs Jual, Kurs Beli, Tanggal; teks format Indonesia, tanggal M/D/YYYY).
  `fetch_fx_rates.py --bi-excel` membacanya (kolom dicari dari header) dan menulis
  `data/fx_rates_bi.csv`: 20 akhir kuartal 2021-12-31 .. 2026-09-30.
- Validasi silang: 19/19 kuartal 2022-03 .. 2026-09 SAMA PERSIS dengan kurs mayoritas
  yang dicetak 5–8 emiten lain di arsip (ITMG, DSNG, JPFA, TAPG, TRIN, TLDN, AKRA-JISDOR).
  Libur: 2025-03-31 pakai fixing 27 Mar (16.588), 2023-06-30 pakai 27 Jun (15.026).
- MEDC: kurs BI berada di dalam rentang pembulatan MEDC sendiri pada setiap filing yang
  dicek -> `bi_middle_rate_within_filing_rounding` (mis. Q1 2025: filing 16.666,67, rentang
  16.529–16.807, BI 16.588).
- Tes: 3 baru (format garis miring, Excel BI, pasangan vs BI). Suite penuh **252 passed**.

### CP38: Harga saham -- fallback dari tanggal 1, hanya close final (2026-11-02)
- Permintaan user: kalau tanggal 17 tidak bisa dipakai, ambil di bulan yang sama mulai
  tanggal 1 berurutan (1, 2, 3 ...). `close_in_month` kini memilih sesi PERTAMA di bulan
  itu (sebelumnya: terdekat ke tgl 17). Berlaku untuk jendela ±12 hari yang kosong dan
  untuk tgl 17 yang belum tiba (Q3 2026 pada 2 Nov) -> note `PROVISIONAL ... Rerun with
  --write-xlsx --overwrite after <tgl 17>`. Aturan utama tidak berubah: tgl 17 libur ->
  sesi terdekat (16/18).
- `last_final_day()`: bar hari ini baru dihitung setelah 17:00 WIB (Yahoo memberi bar
  intraday saat sesi berjalan). Terukur 2 Nov 15:06 WIB: AKRA Q3 2026 -> "no trading day
  with a final close in November 2026 yet" (benar; 1 Nov hari Minggu).
- Tes: 1 baru, 1 diperbarui (6/2 bukan 6/3). Suite penuh **253 passed**.
- Lanjutan (permintaan user): kalau bulan target belum/tidak punya close final, mundur ke
  bulan sebelumnya dan ambil sesi TERAKHIRNYA (`close_last_in_month`, satu bulan saja).
  Terukur 2 Nov 15:xx WIB: AKRA Q3 2026 = 1.375, ELSA = 625 (30 Okt 2026, PROVISIONAL).

### CP39: Analisis sel kosong di CSV 7 emiten baru (2026-11-02)
- CSV arsip lain lengkap (0 sel kosong). Kosong: ENRG 14, PGAS 9, MEDC 5, APEX 2, ESSA 2.
- ENRG Q2 2025 (10 sel): `LLMUnavailable` (3.5-flash-lite 503, 3.1-flash-lite timeout) --
  sementara, cukup dijalankan ulang.
- PGAS Q4 2023 (9 sel): text layer tanpa spasi ("LAPORANPOSISIKEUANGAN",
  "Theoriginalconsolidated...") -> tak ada judul cocok -> fallback 10 halaman pertama.
  DIPERBAIKI: marker judul `page_select` pakai `\s*` (`_spaced`), notice terjemahan
  `the\s*original`. Terukur pada 412 PDF (page_titles, old vs new): HANYA PGAS Q4 2023
  berubah (fallback_first_n -> halaman 15-23, neraca/laba rugi/arus kas).
- ESSA Q3/Q4 2025 `utang_bank`: semua pinjaman lunas, baris "Utang bank 15 - 42.216.691"
  (kolom berjalan "-"). Nil model BENAR, tapi `bank_row_ignored` membaca angka kolom
  pembanding. DIPERBAIKI: cek itu hanya memakai kolom berjalan
  (`_current_column_amount`, dash tepat sebelum angka pertama = 0). Teks ESSA asli kini
  tanpa issue.
- APEX Q3 2025 `total_share`: catatan modal saham di-OCR per kolom ("Jumlah 3.546.466.661"
  sendirian, "100%" di baris lain) -> tabel tak ditemukan, tak pernah ditanyakan.
  DIPERBAIKI: fallback ketiga `_shareholder_table_in_split_columns` (hanya bila dua aturan
  lain kosong) -> halaman idx 52 terpilih.
- APEX Q2 2024 `laba_bersih`: tercetak "LABA BERSIH PERIODE BERJALAN 335.380" (tanpa blok
  atribusi; prompt sudah punya aturan NO SPLIT) -> model meleset; jalankan ulang.
- ENRG Q1 2023: model membaca kolom 31 Maret dengan BENAR (aset 1.201.620.447, liabilitas
  668.220.525, ekuitas neto 532.218.646); neraca FILING sendiri tidak seimbang (L+E
  tercetak 1.200.439.171, selisih 1.181.276) -> `balance_sheet_identity` menahan. Arus kas
  operasi kosong karena PDF ini TIDAK memuat laporan arus kas (hal. 1-7 lalu catatan).
  Catatan: urutan teks pdfium membalik kolom baris total di PDF ini; OCR yang benar.
  Keputusan kebijakan menunggu user.
- MEDC pendapatan (5 filing): blok "Pendapatan dari kontrak dengan pelanggan / Pendapatan
  keuangan / JUMLAH PENDAPATAN". Model mengambil JUMLAH (termasuk pendapatan keuangan
  ~2%) di 13/13 yang terisi, null di 5 (prompt melarang pendapatan keuangan). Konvensi
  menunggu keputusan user.
- Tes: 3 baru. Suite penuh **256 passed**.

### CP40: Rerun sel kosong CP39 + retry teks di jalur gambar (2026-11-02)
- User menjalankan 6 filing ke `~/FinancialReport/rerun_fix.csv`. Terisi 10/10: ENRG Q2
  2025, PGAS Q4 2023 (halaman 15-23), ESSA Q3/Q4 2025 (`utang_bank` 0), APEX Q3 2025
  (`total_share` 3.546.466.661). Semua konsisten dengan kuartal sebelum/sesudahnya.
- APEX Q2 2024 `laba_bersih` tetap null. Sebab: pdfplumber memecah huruf ("P E N D A P A T
  A N") -> 0/6 halaman terbaca -> jalur gambar. Di gambar, model menyebut laporan
  CONSOLIDATED (mengarang "DAN ENTITAS ANAK") dan menjawab null 5/5 panggilan, termasuk
  dengan aturan NO SPLIT yang dipertajam (perubahan prompt itu dibatalkan, tak membantu).
  Teks pypdfium halaman yang sama: 335.380 pada 3/3 panggilan.
- DIPERBAIKI: `_extract_from_images` menanyakan ulang lewat teks halaman untuk field
  `TEXT_RETRY_FIELDS` (aset, total_aset_lancar, kas, liabilitas, pendapatan, laba_bersih,
  kas_dari_aktivitas_operasi) yang null dari gambar; hanya field kosong yang ditanya dan
  diisi, jawaban gambar tak pernah ditimpa. Rerun nyata APEX Q2 2024: ok 10/10, laba_bersih
  335.380 USD x 16.421 = 5.507.274.980 IDR, 5 call LLM.
- Baris rerun dimasukkan ke `apex.csv`, `enrg.csv`, `essa.csv`, `pgas.csv` (cadangan
  `*.csv.bak`). Sel kosong 7 emiten: 32 -> 9 (ENRG Q1 2023: 4, MEDC pendapatan: 5).
- Tes: 2 baru di `tests/test_mixed_pages.py`. Suite penuh **258 passed**.

### CP41: Keputusan user -- pendapatan MEDC = JUMLAH, ENRG Q1 2023 diisi (2026-11-03)
- **Pendapatan = total blok yang tercetak.** Aturan BLOCK ditambahkan di prompt
  (`pendapatan`) dan di `AUDIT_FIELD_RULES`. Prompt saja tidak cukup: rerun 5 filing MEDC
  yang kosong -> 3 JUMLAH, tapi Q2/Q3 2024 tetap baris pertama (1.141.062.168 vs JUMLAH
  1.165.368.521). Maka ditambah `validate.repair_revenue_block_total` (dipanggil di
  `_apply_comparative_column_guard`, issue `revenue_block_total`): figure model = angka
  pertama sebuah baris, lalu dalam <=8 baris ada "Jumlah/Total Pendapatan/Revenues" yang
  selisihnya = jumlah baris di antaranya -> pakai total. Pemindaian 412 PDF: blok seperti
  ini hanya ada di MEDC (18) dan AKRA (13, 2024+; label GT AKRA sudah memakai Total
  Pendapatan, filing AKRA lama tanpa baris total -> tak berubah).
- **Neraca filing tak seimbang** dilaporkan dengan peringatan:
  `validate.filing_prints_unbalanced` -> issue `filing_unbalanced` (WARNING) menggantikan
  `balance_sheet_identity` bila total L+E tercetak = liabilitas + total_ekuitas dan
  memimpin barisnya, dan aset tak pernah muncul di kolom pembanding. Bacaan kolom
  pembanding tetap ditahan (diuji). Di arsip dan output eval hanya ENRG Q1 2023 yang
  kena identity.
- **Retry teks diperluas ke markdown** (`_retry_missing_from_text`, dipakai jalur gambar dan
  markdown): MEDC Q2 2023 arus kas operasi null dari markdown 2x, dari teks 179.060.347
  2x. Rerun nyata: 10/10.
- Rerun nyata dan masuk CSV asli (baris lama diganti, cadangan `*.csv.bak2`): MEDC Q1
  2024, Q2 2022, Q2 2023, Q2 2024, Q3 2024 (pendapatan = JUMLAH, 18/18 MEDC kini JUMLAH);
  ENRG Q1 2023 (aset 1.201.620.447, liabilitas 668.220.525, ekuitas 605.308.357 USD @
  15.062). Regresi: MEDC Q1 2023, Q4 2024, AKRA Q1 2024 tak berubah; AKRA Q1 2023 hanya
  utang_bank bergeser (549.832.511 -> 548.258.806, variasi model, tidak dimasukkan).
- Sel kosong 7 emiten: 9 -> 1 (ENRG Q1 2023 arus kas operasi). **Keliru:** arus kasnya ada
  di PDF (hal. 12, berjudul CATATAN) -- lihat CP42.
- **Temuan, belum diperbaiki:** filing AKRA 2022 s.d. Q3 2023 tertulis "Angka disajikan
  dalam ribuan Rupiah" tapi terbaca FULL -> nilai 1.000x terlalu kecil, di `akra.csv` DAN
  di `data/ground_truth/AKRA.xlsx` (mis. Q1 2023 pendapatan 10.891.301.304). Perlu
  persetujuan user untuk mengubah GT.
- Tes: 2 baru di `tests/test_guards.py`. Suite penuh **260 passed**. Retry markdown dan
  repair pendapatan belum diukur pada eval ground truth.

### CP42: Skala AKRA 2022-Q3 2023 dan arus kas ENRG Q1 2023 (2026-11-03)
- **Skala AKRA.** Header AKRA: "(Angka disajikan dalam ribuan Rupiah, (Amounts are
  expressed in thousands ...". `normalize._HEADER_STATEMENT` mensyaratkan kata kerja
  langsung setelah "(", jadi header ini terlewat; yang tertangkap baris nilai nominal
  "(dalam Rupiah penuh)" di bawah Modal saham -> FULL. Ekstraktor DAN audit label
  (`labelaudit.verify_evidence` memakai `detect_scale`) sama-sama salah, makanya eval tak
  menangkapnya. Perbaikan: subjek opsional "Angka" / "Amounts are" / "All amounts are"
  sebelum kata kerja. Dibandingkan pada teks pipeline semua PDF arsip + data/raw: yang
  berubah hanya 7 filing AKRA (Q1-Q4 2022, Q1-Q3 2023) FULL -> THOUSANDS (catat jumlah
  total dari log `scale_compare` saat selesai).
- Rerun nyata 7 filing AKRA -> semua THOUSANDS, 10/10, = nilai lama x1000 kecuali:
  Q1 2023 utang_bank 548.258.806 (benar; lama 549.832.511 ikut menjumlah pinjaman jangka
  pendek 1.573.705 kolom Des 2022, kolom Mar 2023 "-") dan Q2 2023 pendapatan "Sub-total"
  19.854.711.809 (= kontrak + sewa; filing Q2 2024 mencetaknya sebagai Total Pendapatan
  pembanding; GT sudah pakai Total Pendapatan mulai Q3 2023). Masuk `akra.csv` (7 baris
  diganti, cadangan `akra.csv.bak3`).
- **GT AKRA:** batch `--akra-scale` di `scripts/apply_label_corrections.py` (63 sel N4:T12,
  x1000, plus P8 dan O11 di atas), entri log `scripts/label_corrections_2026-11-03_akra_scale.md`,
  daftar per sel `output/akra_gt_corrections_2026-11-03.csv`. Disetujui user, dry run
  lolos, tapi **belum ditulis**: penulisan xlsx diblokir pengaman otomatis; user yang
  menerapkan (skrip `--akra-scale --apply` juga menambahkan entri ke CORRECTIONS.md).
  Filing 2022 dan Q1 2023 tidak mencetak total pendapatan -> tetap baris kontrak.
- **Arus kas ENRG Q1 2023** ada di hal. 12 (indeks 11), berkepala "CATATAN ATAS LAPORAN
  KEUANGAN" dan dicetak setelah laporan ekuitas -> di luar rentang halaman berjudul, jadi
  `_recover_cash_flow_by_body` (hanya memeriksa halaman terpilih) tak pernah melihatnya.
  Perbaikan: `page_select._untitled_cash_flow_after` -- bila tak ada halaman berjudul arus
  kas di rentang, halaman tepat sesudah rentang diperiksa isinya (+1 halaman lanjutan).
  `_CASH_FLOW_OPERATING` juga menerima judul yang terpotong baris oleh teks Inggris
  ("ARUS KAS DARI CASH FLOWS FROM / AKTIVITAS OPERASI ..."). Rerun nyata: arus kas operasi
  28.619.851 USD -> 431.072.195.762 IDR, 9 sel lain identik, status ok 10/10. Masuk
  `enrg.csv` (cadangan `enrg.csv.bak3`). Sel kosong 7 emiten: **0**. Dampak aturan ini
  pada seluruh arsip: lihat log `cf_compare` (sedang diukur saat dicatat).
- Tes: 2 baru di `tests/test_guards.py`. Suite penuh **262 passed**.

### CP43: Pipeline end-to-end PDF -> Excel dan skill `pdf-to-excel` (2026-11-07)
- **`scripts/pdf_to_excel.py`** merangkai skrip yang sudah ada, tanpa ekstraktor kedua:
  (1) `--inbox` -> `organize_filings.plan`, hanya salin (tak pernah pindah/timpa; conflict
  dilaporkan), manifest di folder emiten; (2) ekstraksi inkremental per PDF lewat
  `pdf_to_csv.extract_row` ke `~/FinancialReport/<T>/<t>.csv` (disimpan atomik tiap
  filing; yang sudah ada tak dikirim ulang kecuali `--retry-partial`/`--refresh`/`--force`;
  berhenti pada error kuota); (3) harga `fetch_share_prices.collect`; (4) workbook
  `~/FinancialReport/<T>/<T>.xlsx` berlayout sama dengan workbook rasio (D1 emiten, baris 3
  periode dengan TAHUNAN untuk Q4, baris 4-13 angka, 14 harga, 15-22 rumus rasio persis
  seperti workbook user) + sheet `Catatan` (status/abstain/issues/kurs/harga per periode)
  + sheet tersembunyi `_pipeline` (nilai terakhir dari pipeline). Sel yang diketik manual
  dipertahankan (oranye, komentar) kecuali `--overwrite`; sel kosong merah dengan alasan
  di komentar. Tak pernah menulis `data/ground_truth` (ditolak di kode). `--compare-gt`
  membandingkan read-only. `--dry-run`, `--excel-only`, `--no-prices`.
- **Skill** `.claude/skills/pdf-to-excel/SKILL.md` (panggil `/pdf-to-excel`): dry run dulu,
  jalankan, laporkan sel kosong/nilai manual/harga PROVISIONAL/selisih GT, investigasi
  (bukan isi manual), aturan repo (GT, kuota, IDX lewat browser, tanpa commit).
- **Terukur:** AKRA `--excel-only` (dari CSV CP42) + harga: 19 periode, 0 sel kosong; vs
  GT 209 sel, 208 identik, beda hanya harga Q3 2026 1.355 vs 1.375 (keduanya provisional,
  17 Nov belum tiba). ENRG: 19 periode, 0 kosong; vs GT 209 sel, beda hanya harga Q1 2022
  (Yahoo 280, label 408 -- belum diperiksa, GT tak diubah). Uji penuh di arsip sementara:
  PDF ENRG Q1 2023 bernama acak -> ditata ke `Q1_2023_ENRG.pdf` -> ekstraksi model 10/10
  -> harga -> xlsx; 10 angka identik dengan `enrg.csv`.
- Pengukuran arsip CP42 (`scale_compare`, `cf_compare`) tidak selesai: proses mati saat
  sesi berakhir. Hasil parsial skala: hanya 7 filing AKRA berubah sebelum terhenti.
- Tes: `tests/test_pdf_to_excel.py` (3). `test_pdf_to_excel` + `test_organize_filings`:
  20 passed. Suite penuh **265 passed** (2026-11-07).

### CP44: Claude sebagai evaluator -- `evaluate_output.py`, skill `evaluate-extraction`, baseline 25 emiten (2026-11-10)
- Permintaan user: setiap run pipeline dievaluasi Claude terhadap GT DAN PDF, lalu
  diperbaiki. **`scripts/evaluate_output.py --ticker T`**: tiap sel `<t>.csv` dibanding
  `data/ground_truth/<T>.xlsx` (tol 1e-4 seperti run_eval) dan dicari tercetak di PDF
  (halaman terpilih dulu, seluruh dokumen bila perlu; IDR/USD x full/ribu/juta; posisi
  angka pertama = kolom berjalan), juga angka label bila berbeda. Status `correct`,
  `no_label`, `wrong:<kind>`, `missed`, `check_unprinted`; petunjuk "likely LABEL/
  EXTRACTION error". Laporan `output/evaluation/<T>_<tgl>.md/.json`. Pembaca CSV menerima
  pemisah ";" (ARCI/CPIN/GTRA/PURA/RCCC/TOTL/TRIN/TRUK disimpan ulang Excel) -- juga di
  `pdf_to_excel.read_csv`; nama CSV huruf besar/kecil diterima.
- **Skill** `.claude/skills/evaluate-extraction/SKILL.md`; `pdf-to-excel` langkah 6 kini
  memanggilnya. Memori: `claude-is-the-evaluator`.
- **Baseline (CSV arsip apa adanya):** 100% vs GT: AKRA, ENRG, ELSA, MEDC, ESSA, PGAS,
  ARCI, DSNG, EMAS, ITMG, JPFA, LSIP, PTBA, RCCC, TAPG, TOTL. Tidak: APEX 14/170, AADI
  69/70, ADMR 176/180, CPIN 179/180, GTRA 149/150, PURA 179/180, TLDN 169/170, TRIN
  161/180, TRUK 171/180.
- **Triase:** semua 37 sel beda di luar APEX = baris CSV usang (kode lama; TRIN 7 baris
  error kuota lama berisi angka sebelum koreksi label; TRUK Q2 2023 dari file lama yang
  ternyata Q1); GT benar, angka label tercetak sebagai angka pertama. Re-ekstraksi nyata
  17 filing (`--refresh`): 16 ok 10/10, TRIN Q4 2025 9/10 (total_share abstain).
  Sesudah: CPIN, GTRA, PURA, TLDN, TRUK 100%; TRIN 178/180; **AADI 61/70, ADMR 155/180**.
- **AADI/ADMR = konvensi kurs:** baris baru memakai `bi_middle_rate_within_filing_rounding`
  (CP37: kurs filing yang dikutip kasar diganti kurs tengah BI bila di dalam rentang
  pembulatan), label & `run_eval` memakai kurs filing (AADI Q4 2024 16.129,03 vs BI
  16.162; ADMR Q2 2025 16.129,03 vs 16.233). Selisih 0,2-0,7%. **Menunggu keputusan user.**
- **APEX:** semua kolom label berisi angka kuartal SEBELUMNYA (17/17 periode, 10/10 field);
  PDF terarsip benar (tanggal tercetak = nama). Setelah geser satu kolom ke kanan: 180/180
  identik; 180/180 angka pipeline tercetak sebagai angka pertama. Label identik dengan CSV
  sampai kurs -> disalin dari pipeline, bukan independen. Usulan batch `--apex-shift`
  (176 sel berubah, dry run lolos), entri `label_corrections_2026-11-10_apex_shift.md`.
- **TRIN total_share:** P13 TAHUNAN 2022 4.404.476 -> 4.205.476 (beredar = Sub-total,
  treasuri 199.000), D13 Q4 2025 4.352.457 (Sub-total tabel 2024) -> 4.424.040. Batch
  `--trin-shares`, dry run lolos. Pola regex `apply_label_corrections` kini menerima
  `<c ... t="n" />` (spasi sebelum `/>`).
- ENRG Q1 2022 harga label 408 vs Yahoo 280: belum diperiksa.
- Tes: `tests/test_evaluate_output.py` (2).

### CP45: Koreksi label APEX dan TRIN diterapkan (2026-11-17, disetujui user)
- User menyetujui kedua usulan CP44. Cadangan workbook sebelum diubah disimpan di
  scratchpad sesi (sementara). Judul entri usulan diubah menjadi "proposed 2026-11-10,
  approved by the user 2026-11-17", lalu:
  `apply_label_corrections.py --apex-shift --apply` (APEX: 176 sel berubah) dan
  `--trin-shares --apply` (TRIN: P13 4.404.476 -> 4.205.476, D13 4.352.457 -> 4.424.040).
  Keduanya tercatat otomatis di `CORRECTIONS.md`. Dry run ulang: 0 sel berubah (idempoten).
- **Evaluasi ulang** (`evaluate_output.py`, CSV yang ada): **APEX 180/180 (100%)**,
  **TRIN 179/180** -- satu-satunya sisa D13 Q4 2025 `total_share` kosong di pipeline
  (abstain sejak re-ekstraksi CP44), label tercetak di hal. 103.
- Suite penuh **267 passed**.

### CP46: Claude sebagai model ekstraksi -- skill `claude-extract`, agen reader/evaluator, memori (2026-11-17)
- Permintaan user: seluruh flow tetap kode, ekstraksi nilai oleh Claude dari halaman yang
  dipilih kode, plus continual learning ala artikel Anthropic "components of agent
  memory" (catatan + dreaming). **`LLM_PROVIDER=claude-code`** (`src/claudecode.py`):
  `complete()` mencari `<key>.answer.json` (key = sha256 dari system+prompt+gambar yang
  akan dikirim ke model); kalau belum ada, menulis `<key>.request.md` (+ PNG halaman di
  jalur gambar) ke `output/claude_exchange/<filing>/` dan filing berhenti dengan
  `AnswerPending` -- tidak ada baris parsial. Loop grup di `extract_from_pdf` tetap jalan,
  jadi satu ronde meminta semua grup; `raise_if_pending` dipanggil setelah loop dan
  setelah jalur gambar. Retry field kosong muncul sebagai permintaan ronde berikut.
- `pdf_to_excel.py`: `PIPELINE_VARIANT` (CSV `<t>_claude.csv`, workbook `<T>_claude.xlsx`,
  di samping milik Gemini), `--only Q4_2025 ...`, exit 3 bila ada jawaban tertunda (harga
  dan workbook ditunda). `evaluate_output.py --variant claude` (laporan
  `<T>_claude_<tgl>`). `pdf_to_csv.extract_row` meneruskan `AnswerPending`.
- **`scripts/claude_extract.py`**: `run` (pdf_to_excel dengan provider Claude, fallback
  Ollama dimatikan), `pending`, `check <answer>`, `memory lint` (anggaran ukuran, format
  catatan `(verified|hipotesis tgl; bukti: ...)`, MENOLAK angka yang sama dengan nilai
  label GT -- memori menjelaskan di mana/bagaimana membaca, bukan jawabannya),
  `memory record` (skor + digest memori yang DIPAKAI run, dari meta permintaan, dan
  digest sesudah dreaming -> `output/claude_memory_runs.jsonl`; tidak dobel).
- **Memori** `memory/extraction/`: `MEMORY.md` (indeks + konvensi umum), `issuers/<T>.md`,
  `fields/<field>.md`. Kode menyuntikkan hanya indeks + halaman emiten + halaman field
  yang diminta ke file permintaan (bukan ke prompt yang di-hash). `CLAUDE_MEMORY=off` +
  `CLAUDE_EXCHANGE_DIR` lain = baseline tanpa memori. Diisi awal dari aturan checkpoint
  (total_share, utang_bank, pendapatan, laba_bersih, TRIN, AKRA).
- **Agen** `.claude/agents/extraction-reader.md` (satu per filing; hanya membaca file
  permintaan, tidak boleh membuka PDF/CSV/GT/eval) dan `extraction-evaluator.md`
  (evaluasi vs GT + PDF, klasifikasi sebab reader/selection/postprocess/label/convention,
  banding dengan baris Gemini, lalu dreaming: tambah/koreksi/gabung/hapus catatan, lint,
  record). Skill `.claude/skills/claude-extract/SKILL.md` merangkai semuanya.
- **Uji nyata TRIN Q4 2025:** ronde 1 = 5 permintaan (neraca, laba rugi, arus kas, modal
  hal. 103, catatan utang hal. 73); 1 subagen reader menjawab (~98k token subagen, 56 s);
  ronde 2 = 0 permintaan baru, baris **10/10**. Bug ditemukan di uji ini dan diperbaiki:
  pemeriksa jawaban menuntut kunci `ekuitas` padahal prompt meminta `total_ekuitas`
  (reader menambahkannya; nilainya = turunan kode, tak berdampak).
- Tes: `tests/test_claudecode.py` (6). Suite penuh **273 passed**.

### CP47: Evaluasi ekstraksi Claude TRIN Q4 2025 + konsolidasi memori (2026-11-17)
- `evaluate_output.py --ticker TRIN --variant claude --periods Q4_2025`: **10/10 benar,
  10/10 terisi**, 0 sel perlu diputuskan (`output/evaluation/TRIN_claude_2026-11-17.md`).
  `total_share` = Sub-total hal. 103, sama dengan label.
- Gemini (trin.csv, run 2026-11-10) abstain `total_share` karena nilai yang ditahan
  4.424.040.000 (x1000 dari angka tercetak) gagal grounding "value does not appear".
  Jadi tabel hal. 103 TERBACA; masalahnya angka lembar ikut diskalakan "ribuan Rupiah".
  Jawaban mentah Gemini tidak tersimpan, jadi siapa yang mengalikan (model atau kode)
  belum diukur; di kode tidak ditemukan penskalaan field saham.
- Memori: satu catatan baru di `memory/extraction/issuers/TRIN.md` (kolom lembar tampak
  dalam ribuan lembar; tulis seperti tercetak). Digest ed9a1db5eb66 -> e031b0b1c650;
  `memory lint` ok; `memory record` tercatat. (Digest yang dicatat awalnya = memori
  sesudah update; `record` diperbaiki agar menyimpan `memory_digest_used` dari meta
  permintaan, dan baris log ini dikoreksi menjadi used=ed9a1db5eb66.)
- Ini n=1 filing; belum ada perbandingan dengan baseline tanpa memori (belum diukur).

### CP48: Asal total_share x1000 TRIN Q4 2025 (Gemini) dan perbaikannya (2026-11-17)
- **Bukan kode skala.** `withheld_value` dicatat di `assess` sebelum `to_idr`, dan
  `to_idr` tidak menyentuh jumlah saham. Prompt tabel saham yang PERSIS sama (hash
  permintaan Claude direproduksi) dikirim ulang ke gemini-3.5-flash-lite 3x: ketiganya
  4.424.040 / 4.551.457 / 127.417. Run pipeline Gemini penuh hari ini (5 call, CSV
  scratch, `trin.csv` tak diubah): `ok` 10/10, total_share 4.424.040, tanpa abstain.
  Jadi x1000 pada 10 Nov = variasi jawaban model (1 dari 5 sampel teramati); grounding
  menahannya dengan benar (abstain, bukan angka salah).
- Halaman 103 mencetak "(Disajikan dalam Ribuan Rupiah, kecuali dinyatakan lain)" dan
  kolom lembar memang tampak dalam ribuan lembar (1.653.802 x Rp100 = kolom Rupiah dalam
  ribuan) -- itulah yang memancing pengalian. Aturan user tetap: lembar seperti tercetak.
- **Perbaikan:** `validate.repair_share_count_scale` (dipanggil di
  `_apply_comparative_column_guard` setelah `repair_share_amount_column`): jumlah saham
  yang tidak tercetak, padahal nilai/1.000 atau /1.000.000 tepat sama dengan jumlah
  lembar pada satu baris tabel pemegang saham, dikembalikan ke angka tercetak. Replay
  ujung-ke-ujung dengan jawaban saham x1000 (provider claude-code, exchange dir scratch):
  ketiga field diperbaiki, baris `ok`, tanpa abstain. Issue-nya masih tercatat dengan
  rule umum `comparative_column_repaired`. Dampak di korpus berlabel belum diukur.
- Tes: 1 baru di `tests/test_mixed_pages.py`. Suite penuh **274 passed**.
- **Refresh (disetujui user):** `pdf_to_excel.py --ticker TRIN --refresh Q4_2025
  --compare-gt` -> Q4 2025 `ok` 10/10 (gemini-3.5-flash-lite, 1x 503 lalu berhasil),
  `TRIN.xlsx` 18 periode, 0 sel kosong, harga diambil ulang. `evaluate_output.py --ticker
  TRIN`: **180/180**. `--compare-gt` (tanpa toleransi) masih menunjukkan satu beda lama:
  Q1 2026 utang_bank 714.891.526.000 vs label 714.891.426.000 (selisih 100 juta, di dalam
  toleransi relatif 1e-4 evaluator; label = angka tercetak per CP19). Baris itu dari
  gemini-3.1-flash-lite dan tidak di-refresh.

### CP49: Claude menjadi model ekstraksi default (2026-11-17, permintaan user)
- `.env`: `LLM_PROVIDER=claude-code`, `LLM_FALLBACK_PROVIDER=` (kosong; tanpa Ollama).
  `.env.example` menyebut opsi `claude-code`. `pdf_to_excel.py` kini langsung memakai
  Claude dan menulis ke CSV/workbook UTAMA (`<t>.csv`, `<T>.xlsx`);
  `claude_extract.py run` default juga ke file utama, `--variant claude` untuk salinan
  pembanding. `memory record` tanpa `--variant` membaca `<T>_<tgl>.json`.
- Skill `pdf-to-excel` ditulis ulang: preflight tanpa kunci Gemini, run per ronde
  (exit 3 -> satu `extraction-reader` per filing -> ulangi), evaluasi lewat
  `extraction-evaluator` (evaluasi + dreaming), catatan `--refresh` memakai jawaban cache
  bila prompt sama (hapus `*.answer.json` untuk membaca ulang). Skill `claude-extract` dan
  agen evaluator diselaraskan (banding dengan `<t>.csv.bak`).
- `tests/conftest.py` mematok `LLM_PROVIDER=gemini` di tes (cache prediksi yang
  di-commit berasal dari Gemini; isi `.env` tidak boleh menentukan apa yang diuji).
  Tanpa itu 4 tes gagal. Suite penuh **274 passed**.
- Belum diubah: audit label (`AUDIT_MODEL` Gemini, `audit_labels.py`) -- itu pelabelan,
  bukan ekstraksi; `run_eval.py` sekarang ikut provider `.env` (Claude) untuk run baru.
- Baris lama di CSV arsip tetap hasil Gemini sampai di-refresh.

## Pekerjaan tertunda (urutan yang disarankan)

0c. **Ukur ulang di seluruh arsip** (CP42, terputus): skala header baru dan
   `_untitled_cash_flow_after` (skrip di scratchpad hilang bersama sesi; tulis ulang:
   bandingkan `detect_scale`/`select_statement_pages` lama vs baru per PDF). Ukur retry
   markdown + `repair_revenue_block_total` + skala pada eval ground truth. GT AKRA CP42
   sudah diterapkan user (63 sel, entri CORRECTIONS.md ada).
0e. **Keputusan user (CP44):** konvensi kurs AADI/ADMR (kurs filing vs BI-dalam-
   pembulatan) -> lalu samakan kode + rerun periode terdampak, evaluasi ulang AADI ADMR.
   (Koreksi APEX/TRIN sudah diterapkan, CP45.) Sisa TRIN Q4 2025 `total_share`: sebab
   (variasi model x1000) dan perbaikan di CP48; baris sudah di-refresh (TRIN 180/180).
   Sisa kecil: Q1 2026 utang_bank salah satu digit (...526 vs tercetak ...426), lolos
   toleransi; refresh Q1_2026 bila ingin persis.
0f. **Ekstraksi Claude (CP46/47):** perluas dari 1 filing; ukur berpasangan dengan Gemini
   dan dengan baseline tanpa memori (`CLAUDE_MEMORY=off`, exchange dir lain) pada filing
   yang sama sebelum klaim apa pun. Biaya: ~5 permintaan/filing, satu subagen per filing.
0d. **Harga label ENRG Q1 2022** 408 vs Yahoo 280 (CP43): periksa, putuskan bersama user.
0b. **Jalankan ulang emiten USD** (CP37): kurs sudah beres untuk MEDC, ENRG, PGAS, ESSA,
   APEX (kurs filing, atau kurs tengah BI dari `data/fx_rates_bi.csv`). Tabel BI perlu
   diperbarui tiap kuartal baru: unduh ulang Excel Kurs Transaksi USD dari bi.go.id lalu
   `python scripts/fetch_fx_rates.py --bi-excel "<file>"`. Opsional: `pdf_to_csv` menyimpan
   nilai as-printed saat kurs gagal agar call LLM tidak terbuang (belum diubah).
00. **Arsip ELSA** (CP35): user menghapus folder lama; isi ulang dari `~/Downloads/idx`
   dengan `organize_filings.py ~/Downloads/idx --ticker ELSA` (cek dry run dulu, lalu
   `--apply`). ELSA belum punya workbook label, jadi skor tidak terdampak. Daftar emiten
   perlu di-refresh: unduh ulang Excel "Daftar Saham" dari IDX lalu
   `python scripts/fetch_issuers.py --idx-excel "<file>"`; nama lama yang tidak ada di kedua
   sumber ditambahkan ke `data/issuers_extra.json`.
0a. **PURA Q2 2025 total_share** masih kosong: pertimbangkan memberi model bacaan OCR
   alternatif (psm 6) untuk halaman tabel saham, yang memuat baris total utuh. Ukur
   dengan run API pada filing PURA sebelum dipakai.
0b. **Review total_share** (TRIN Q2/Q4 2022 dan JPFA 2022 beredar vs ditempatkan; LSIP Q4
   2024; RCCC Q2 2023). Soal satuan TRIN sudah diputuskan: tidak diskalakan, label benar.
0. **Setelah CP19:** koreksi 25 sel sudah diterapkan user (entri ada di `CORRECTIONS.md`).
   `Q2_2023_TRUK.pdf` sudah diunduh ulang (SHA-1 `ad635f0…`, 74 halaman, 30 Juni 2023);
   label Q2 2023 TRUK sudah diisi user (sama 10/10 dengan hasil ekstraksi ulang, tetapi
   kesepuluhnya terverifikasi tercetak di PDF baru: neraca hal. 5–6, laba rugi hal. 7,
   arus kas hal. 10). Run awal 3.5-flash-lite markdown (6 filing PURA, 17 Okt): 60/60 benar
   vs 58/60 di CSV 9 Okt (PURA Q4 2022 pendapatan + arus kas operasi kini benar);
   `run_eval` masih berjalan saat dicatat; putuskan satuan `total_share` TRIN
   (ribuan lembar) dan saham beredar vs ditempatkan TRIN Q2/Q4 2022; lalu ekstraksi
   ulang PURA/RCCC/TRIN/TRUK lewat `run_eval.py` dengan satu model untuk mengukur efek
   perbaikan input (OCR per halaman) yang tidak terukur di replay.
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
7. Evaluasi agentic berpasangan: gunakan filing yang sama untuk pipeline dan agentic,
   backfill halaman selector lewat `page_agreement.py`, rescore dari cache, lalu
   `compare_runs.py --bootstrap`. Scorecard agentic yang ada (n=1 berhasil) belum cukup
   untuk klaim kualitas. Jangan gabungkan hasil API pipeline dengan tag agentic; guard
   untuk kasus itu sekarang sudah ada.
8. Commit: keputusan user. Jangan stage atau commit tanpa diminta.
9. Audit dan label independen untuk PURA/RCCC/TRIN/TRUK; setelah itu ukur error dan
   coverage per emiten, khususnya klasifikasi bank vs non-bank, pencarian tabel saham,
   serta konsistensi scope. CSV lama adalah evidence prediksi, bukan jawaban kebenaran.
10. Evaluasi ulang guard baris lender gabungan dan deteksi jumlah saham kecil terhadap
    suite regresi, korpus 14 emiten berlabel, dan filing eksternal PURA/RCCC/TRIN/TRUK.
    Ukur coverage serta abstention agar perbaikan presisi tidak menyembunyikan penurunan
    recall.
11. Setelah API key dirotasi dan kapasitas tersedia, jalankan 4 filing 2023 lagi dengan
    retry/fallback produksi untuk diagnosis per filing; lalu ukur model 3.5 pada korpus
    berlabel penuh sebelum mempromosikan baseline.
12. Setelah API key dirotasi, ekstrak ulang 8 baris parsial TRIN dengan utang bank kosong.
    Pastikan model mengembalikan semua lender bank dari note, grounding komponen lolos,
    dan nilai total tidak melampaui subtotal gabungan. Jangan mengubah CSV lama sebelum
    hasilnya lolos inspeksi.

## Peta file

| Area | File |
|---|---|
| Ekstraksi | `src/extract.py` (orkestrasi, `GROUP_FIELDS`, guard, `derive_fields`), `src/page_select.py`, `src/pagemd.py`, `src/pdftext.py`, `src/normalize.py`, `src/confidence.py`, `src/validate.py`, `src/prompts.py`, `src/llm.py` |
| Agen ekstraksi | `src/agent.py`, `src/agenttools.py` |
| Evaluasi | `src/evalkit.py`, `src/evalmetrics.py`, `scripts/run_eval.py`, `report_eval.py`, `compare_runs.py`, `promote_baseline.py`, `page_agreement.py`, `evals/baselines/` |
| Audit label | `src/labelaudit.py`, `src/auditagent.py`, `scripts/audit_labels.py`, `scripts/audit_benchmark.py` |
| Ground truth | `data/ground_truth/<TICKER>.xlsx` (Sheet1, D1 = emiten, baris 3 = periode, baris 4–13 = field), `CORRECTIONS.md`, skill `.claude/skills/label-groundtruth/` |
| Filing | `data/raw/` (di repo), `~/FinancialReport/<TICKER>/` (arsip pribadi, termasuk CSV lama) |
| Pipeline PDF -> Excel | `scripts/pdf_to_excel.py`, skill `.claude/skills/pdf-to-excel/`; output `~/FinancialReport/<T>/<t>.csv` dan `<T>.xlsx` |
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
