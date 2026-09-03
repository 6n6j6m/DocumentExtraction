# Prompt untuk Claude Code — Serving layer (FastAPI + Docker) & sisa gap Technical Notes

> Paste seluruh isi di bawah ini sebagai satu prompt di Claude Code, dijalankan di root repo.

---

Kamu bekerja di repo ini (IDX quarterly financial statement extraction). Baca dulu, jangan langsung menulis kode:

1. `AI_Engineer_Take-Home_Test_Document_Extraction.pdf` — bagian **Technical Notes** dan **Evaluation Criteria**.
2. `README.md` — terutama section `Architecture`, `Evaluation`, `Production notes`, dan `Not built yet`.
3. `src/extract.py` (`extract_from_pdf`), `src/llm.py`, `src/confidence.py`, `src/schema.py`, `scripts/run_eval.py`.

Tujuan tugas ini: menutup gap yang secara eksplisit disebut di Technical Notes dan masih terdaftar di `Not built yet`. Jangan menambah fitur di luar daftar ini. Jangan menulis ulang logika ekstraksi yang sudah bekerja — semua yang baru adalah **lapisan di atasnya**.

## Prinsip yang tidak boleh dilanggar

- **Extraction logic tetap milik repo, bukan framework.** FastAPI hanya transport. Tidak ada logika parsing/scoring baru di dalam route handler.
- **Satu sumber kebenaran.** `run_eval.py` sekarang memanggil `extract_from_pdf` langsung; setelah ada API ia harus bisa memanggil API — tapi jalur lokal tetap dipertahankan sebagai default agar test tetap jalan tanpa container. Jangan menduplikasi kode evaluasi menjadi dua versi.
- **Tidak ada secret yang di-commit.** Semua konfigurasi lewat env yang sudah ada di `.env.example`; tambahkan key baru ke `.env.example` bila perlu.
- **Jangan mengarang angka.** Setiap klaim baru di README (latency, cost, dampak optimisasi) harus berasal dari run yang benar-benar kamu jalankan, bukan estimasi.
- Kalau ada keputusan desain yang menurutmu keliru dalam instruksi ini, katakan dan beri alasan sebelum mengerjakan — jangan diam-diam menyimpang.

## Yang harus dibangun

### 1. HTTP API (FastAPI)

Buat `src/api.py` (atau `src/service/`) dengan minimal:

- `GET /health` — liveness. Balas status, provider aktif, model, git commit, dan apakah provider bisa dihubungi (cek murah, jangan panggil model).
- `POST /extract` — terima **satu** PDF (`multipart/form-data`, field `file`), kembalikan objek hasil `FinancialStatementExtraction` yang sudah ter-validate, plus per-field confidence, daftar field yang abstain, `issues` dari validasi, dan blok `usage` (latency per tahap, jumlah panggilan LLM, token bila provider melaporkannya).
- `POST /extract/batch` — terima banyak file dalam satu request, proses dengan concurrency terbatas (env `API_MAX_CONCURRENCY`, default kecil), kembalikan hasil per-dokumen **dengan kegagalan per-dokumen yang terisolasi** (satu PDF gagal tidak menggagalkan batch; tiap entry punya `status: ok|error` dan pesan). Ini yang menjawab kriteria "handling more than one document at a time".
- `GET /schema` — kembalikan field schema yang berlaku, supaya kontrak API terdokumentasi sendiri.

Ketentuan:
- Response model pakai **pydantic** (`pydantic` sudah ada di `requirements.txt` tapi belum dipakai — ini sekaligus menutup item *Type validation at the boundary* di `Not built yet`). Sekalian: buat `from_dict` di `schema.py` menolak tipe yang salah dengan pesan jelas, bukan meledak di dalam `validate()`.
- Error handling: file bukan PDF / rusak → 400 dengan pesan spesifik; `LLMUnavailable` → 503 dan sebutkan providernya; `LLMError` per-halaman tetap diteruskan sebagai hasil parsial dengan `issues` terisi, bukan 500.
- Batas ukuran upload dan jumlah file per batch lewat env, dengan default masuk akal.
- Logging terstruktur (JSON line) per request: request id, nama file, jumlah halaman terpilih, provider, latency, jumlah field terisi, jumlah abstain.
- Jangan menyimpan file upload permanen; pakai temp dir dan bersihkan.

### 2. Cost & latency visibility

Technical Notes minta cost/latency terlihat; sekarang cost belum dilacak sama sekali.

- Tambahkan `src/usage.py`: akumulator token in/out per panggilan (Gemini melaporkan `usageMetadata`; Ollama melaporkan `prompt_eval_count`/`eval_count`), plus tabel harga per model yang **dibaca dari config/env**, bukan hardcode di tengah logika. Model lokal berbiaya nol — tampilkan tetap, dengan tokennya, supaya perbandingan cloud vs lokal jujur.
- Sertakan agregatnya di response `usage`, di scorecard (`run_eval.py`), dan di ringkasan CLI.
- Kalau provider tidak melaporkan token, jangan menebak — tulis `null` dan sebutkan alasannya.

### 3. Docker & compose

Persis seperti yang diminta Technical Notes, tidak lebih:

- `Dockerfile` untuk service ekstraksi. Perhatikan dependensi non-Python: `pdf2image` butuh **poppler-utils**, jalur OCR butuh **tesseract** (+ data bahasa `ind` bila dipakai). Build multi-stage agar image tidak gemuk; jalankan sebagai non-root user.
- `docker-compose.yml` dengan dua service dalam **satu compose project**:
  - `api` — `docker compose up` membuatnya melayani di port yang terekspos, dengan healthcheck yang memakai `GET /health`.
  - `eval` — one-shot, `profiles`/tanpa auto-start, dijalankan sebagai `docker compose run --rm eval`, `depends_on: api (service_healthy)`, menjalankan harness **terhadap API itu** (bukan memanggil library langsung) dan menulis scorecard + per-document results ke **direktori output yang di-mount** ke host.
  - Mount `./data` read-only, `./output` read-write.
- Env dari `.env`; jangan bake key ke image. Untuk Ollama di host dari dalam container, dokumentasikan `host.docker.internal` (dan catat bahwa di Linux perlu `extra_hosts`).
- `run_eval.py` mendapat flag `--api-url` (atau env `EVAL_TARGET`): bila diisi, ia memanggil endpoint; bila kosong, jalur in-process seperti sekarang. Perilaku scoring identik di kedua jalur — bukti: jalankan keduanya dan bandingkan scorecard-nya.
- Verifikasi sendiri, jangan asumsikan: build image, `docker compose up -d`, cek `/health`, jalankan `docker compose run --rm eval`, pastikan scorecard muncul di `output/` di host. Laporkan output nyatanya.

### 4. Artefak yang harus ikut ter-commit

Technical Notes minta artefak dari run yang benar-benar dilakukan:

- Scorecard hasil run lewat container, di `output/`.
- **Scorecard baseline kedua** supaya `compare_runs.py` bisa didemokan reviewer tanpa harus generate run sendiri (ini item terakhir di `Not built yet`).
- Per-document results yang menyertainya.

### 5. README

Update, jangan tulis ulang dari nol. Yang berubah:
- `Quick start` dapat jalur Docker sebagai cara utama menjalankan (`docker compose up`, lalu `docker compose run --rm eval`), jalur lokal tetap ada di bawahnya.
- Section baru ringkas: **API surface** — daftar endpoint, contoh request/response yang dipangkas, dan alasan desainnya (kenapa batch mengisolasi kegagalan per dokumen, kenapa abstain dikembalikan eksplisit).
- Tabel **Cost** di `Production notes`, dengan angka nyata dari run, di sebelah tabel latency yang sudah ada.
- Pindahkan item yang sudah selesai keluar dari `Not built yet` — dan **jangan menghapus** yang masih belum selesai (kalibrasi confidence, cross-provider agreement, issuer kedua yang berlabel). Kejujuran daftar itu adalah nilai plus, bukan kelemahan.
- Catatan trade-off: kenapa API-nya sinkron dan bukan job queue (dan kapan itu jadi salah).

### 6. Test

Tambah ke `tests/`:
- Endpoint test dengan `TestClient` dan provider yang di-stub — tanpa panggilan jaringan: happy path, PDF rusak, provider unavailable → 503, isolasi kegagalan dalam batch.
- Test bahwa `from_dict` menolak tipe salah dengan pesan jelas.
- Test bahwa akumulasi usage/cost benar untuk payload provider yang di-fake.

## Cara kerja yang diharapkan

1. Mulai dengan **rencana singkat** — daftar file yang akan dibuat/diubah dan kontrak endpoint — dan tunggu konfirmasi sebelum mengeksekusi.
2. Kerjakan bertahap, commit per langkah bermakna dengan pesan yang menjelaskan *kenapa*, mengikuti gaya git history yang sudah ada.
3. Setelah tiap tahap, **jalankan** apa yang kamu buat dan tempelkan output nyatanya. Klaim tanpa run tidak diterima.
4. Perbarui `Checkpoint.md` di root repo setiap menyelesaikan satu instruksi development: apa yang dikerjakan, apa yang diverifikasi, apa yang masih terbuka. Sesi tanya-jawab tidak perlu dicatat.
5. Terakhir, lakukan review sendiri terhadap **Evaluation Criteria** di PDF baris per baris, dan sebutkan terus terang aspek mana yang masih tipis.
