# HANDOFF.md — Malva

> Terakhir diperbarui: 2026-11-09.
> Blueprint produk: **`BLUEPRINT.md`** (bukan `Blueprint.md`).
> Status singkat: perbaikan kode dan test selesai di Linux (87 test lolos). **Belum pernah dijalankan di Windows.** Push belum berhasil (lihat §9).

---

## 1. Ringkasan status

- Audit P0 (audio, privasi, sleep/focus, event, UI) diperbaiki di kode dan dicakup test.
- UI (`malva/ui/html.py`) ditulis ulang. Sebelumnya ada kesalahan sintaks JavaScript (`});` tidak berpasangan) yang tidak tertangkap audit. Sekarang skrip inline lolos `node --check`, dan test kontrak memastikan setiap fungsi yang dipanggil Python ada di halaman.
- Yang belum selesai dari blueprint: integrasi Windows-MCP (P2), Qwen3-ASR, VAD untuk wawancara, memori lintas meeting, keputusan-ke-eksekusi, screen-aware, dan jembatan multibahasa (lihat §7).

## 2. Mode dan sumber audio (BLUEPRINT §4)

| Mode | Sumber default | Catatan |
|---|---|---|
| Asisten | Mikrofon + audio sistem (track terpisah) | Audio sistem hanya konteks transkrip, tidak memicu panggilan AI sendiri |
| Meeting | Audio sistem saja | |
| Latihan wawancara | Mikrofon | Pertanyaan dan jawaban hanya maju lewat aksi eksplisit |
| Catatan wawancara | Mikrofon | |
| Input suara | Mikrofon saja | Menolak audio sistem; hasil hanya ditampilkan untuk disalin |

Aturan dasar: audio sistem **tidak pernah** diam-diam dialihkan ke mikrofon. Jika loopback gagal, sumber dilaporkan gagal dengan `capture_error` yang bertipe.

## 3. Privasi

- Default **lokal saja**. Cloud diaktifkan hanya lewat tombol "Izinkan cloud" di tab Setelan, disimpan di tabel `app_settings` (kunci `cloud_processing`), dan bisa dicabut.
- Variabel lingkungan atau URL tidak dianggap persetujuan.
- **Tidak ada LLM lokal.** Satu-satunya model lokal adalah Whisper (faster-whisper) untuk ASR. Semua AI (chat, ringkasan, feedback) memakai Ollama cloud dari `OLLAMA_URL`, dan itu selalu dianggap cloud, termasuk jika URL-nya localhost. Pencarian web (Ollama, lalu DuckDuckGo) juga hanya jalan setelah opt-in.
- Google STT hanya dipakai setelah opt-in. Jika model Whisper lokal gagal, sistem **tidak** fallback ke cloud; pengguna diberi pesan.
- Partial (teks live) selalu lokal. Tidak pernah dikirim ke cloud dan tidak disimpan. Hanya hasil final yang masuk transkrip.
- Hidden Mode memakai `SetWindowDisplayAffinity` (WDA_EXCLUDEFROMCAPTURE). Ini **bukan** jaminan tidak terlihat. Status yang ditampilkan jujur: `disabled`, `active`, `unsupported` (Windows terlalu lama), `failed`.

## 4. Kontrak event (sumber kebenaran: `EVENT_TYPES` di `malva/shell/session.py`)

Session dan engine memancarkan event berikut ke `app.py`, yang meneruskannya ke halaman lewat fungsi `window.<nama>`:

`session_started`, `session_ended`, `source_state`, `capture_error`, `state_change`, `transcript_segment`, `audio_levels`, `ai_start`, `ai_chunk`, `ai_end`, `ai_error`, `action_proposed`, `action_result`, `voice_input_text`, `focus_mode`, `sleep_mode`, `interview_question`, `interview_answer_draft`, `interview_feedback`, `interview_report`, `meeting_report`, `asr_error`, `report_error`, `notice`.

Callback privasi memakai komponen `cloud_processing` dan `hidden_mode`. Itu bukan event sesi.

Test `tests/test_event_contract.py` memastikan: setiap event yang dipancarkan ada di daftar, setiap item daftar benar-benar dipancarkan, dan setiap item ditangani di `app.py`.

## 5. Yang sudah diverifikasi lewat test (Linux, 87 test)

Jalankan: `pip install -r requirements-dev.txt && python3 -m pytest -q tests/`

- `test_analysis.py`: pemetaan band sinus, band log-spaced, senyap, rentang nilai, decay, input buruk, reset, padding, error konfigurasi.
- `test_devices_and_capture.py`: pemilihan loopback, mic tidak pernah dipakai sebagai fallback sistem, WASAPI tidak ada, mic default tidak ada, kegagalan buka di semua sample rate, format stereo loopback, tidak ada track ganda, voice_input menolak audio sistem, level diberi tag sumber. Memakai fake PyAudio.
- `test_privacy_and_policy.py`: klasifikasi endpoint, cloud mati secara default, opt-in tersimpan dan bisa dicabut, DB gagal = fail-closed, ASR tanpa Google tanpa opt-in, LLM remote diblokir tanpa HTTP call, matriks sleep, parsing sleep.
- `test_session_flow.py`: SQLite nyata di folder sementara; startup per mode; invariant pause/sleep/focus; ucapan hanya mengusulkan aksi; approve/reject; instruksi ketik berjalan; audio sistem hanya konteks; model lokal hilang dilaporkan; latihan wawancara eksplisit; stop melepas sumber.
- `test_ui_contract.py`: skrip inline lolos `node --check`; setiap `_call("…")` di `app.py` punya fungsi `window.…`; setiap method API yang dipanggil JS ada di `MalvaAPI`; tidak ada interpolasi template di skrip; setiap kelas CSS yang dipakai punya aturan.
- `test_event_contract.py`: lihat §4.

Mutation check: tiga perbaikan pada modul inti (audio, privasi, session) sengaja dibatalkan satu per satu, dan tiap mutasi tertangkap oleh test. Satu mutasi pada kontrak UI (nama fungsi `showVoiceText` diubah) juga tertangkap. Setelah itu file dipulihkan dan diverifikasi dengan `cmp`.

## 6. Yang TIDAK diverifikasi

Semua ini membutuhkan Windows dan belum pernah diuji:

- Loopback WASAPI dengan perangkat audio nyata; PyAudio mikrofon nyata.
- Render WebView2, transparansi dan sudut membulat DWM, posisi awal jendela.
- Seret jendela (`start_drag`).
- Hotkey dan perilaku always-on-top.
- Hidden Mode (`SetWindowDisplayAffinity`) dan label statusnya di UI.
- Pemuatan model Whisper dari Hugging Face di CPU Windows.
- Tampilan pill di layar kecil dan skala DPI.

Daftar QA manual lengkap ada di `Malva_Repository_Audit_and_Agent_Prompt_v2.md`.

## 7. Belum dikerjakan dari blueprint

- **Windows-MCP (P2)**: dispatch aksi desktop masih lewat `malva/desktop/tools/runner.py`. Jangan dihapus sebelum penggantinya ada (sesuai catatan audit).
- **Qwen3-ASR**: belum ditambahkan.
- **VAD untuk wawancara**: belum.
- **Memori lintas meeting**: belum.
- **Keputusan-ke-eksekusi**: belum. Saat ini aksi dari ucapan hanya menjadi usulan yang harus disetujui.
- **Screen-aware** dan **jembatan multibahasa**: belum.
- **Drag**: kode ada, belum divalidasi di Windows.

## 8. Klaim audit yang sudah usang

- **P0.4** (nama event segmen): sebagian sudah benar di HEAD. Sekarang dicakup test kontrak event.
- **P0.5** (stuck processing): sebagian sudah benar di HEAD. Sekarang setiap jalur pemrosesan berakhir di state yang benar (listening, paused, sleeping, atau error).
- **P0.6**: sebagian sudah benar di HEAD. Sisanya diperbaiki di perubahan ini.
- **P0.7** (auto-sleep): sebelumnya tidak pernah aktif, karena LISTENING mode asisten selalu mereset timer. Sekarang timer direset hanya oleh ucapan atau teks yang diketik, dan mode yang menangkap audio (Meeting, Latihan) dikecualikan dari auto-sleep.

## 9. Status git dan push

- Perubahan di-commit secara lokal di `/home/claude/nana`.
- **Push ditolak**: Claude GitHub App belum punya akses ke `fattan-malva/nana` untuk organisasi ini. Perbaikan: pasang Claude GitHub App di https://github.com/apps/claude/installations/select_target, atau sambungkan ulang GitHub di https://claude.ai/customize/connectors?auth_start=github&auth_start_force=1. Setelah itu, push bisa diulang.

## 10. Konfigurasi

- Salin `.env.example` menjadi `.env`. Default-nya lokal saja.
- `OLLAMA_URL` adalah endpoint Ollama cloud. Isi API key di `OLLAMA_API_KEY`. Aktifkan "Izinkan cloud" di Setelan agar AI berjalan.
- `SLEEP_AFTER_SECONDS=60`; isi `0` untuk menonaktifkan auto-sleep.
- Jalankan di Windows: `pip install -r requirements.txt` lalu `python app.py`.

## 11. Log dan diagnosa crash

- Lokasi: `%LOCALAPPDATA%\Malva\logs\malva.log` (log aplikasi, exception dari semua thread) dan `crash.log` (crash native seperti access violation, lewat `faulthandler`).
- Jika aplikasi mati sendiri, kirim kedua file itu. Tanpa `crash.log`, crash native tidak meninggalkan jejak apa pun.
- Log tidak berisi transkrip atau audio.

## 12. Perubahan terbaru (2026-11-09)

- **Drag window**: sebelumnya `PostMessage(SC_MOVE)` dan tidak pernah menggerakkan window. Sekarang memakai mekanisme drag pywebview 6.2.1: `easy_drag=False` dan statusbar bertanda `pywebview-drag-region`. Belum diuji di Windows.
- **Teks live**: transkripsi sebelumnya baru jalan setelah 1,1 detik hening (atau 30 detik). Sekarang snapshot ucapan dikirim tiap ~1 detik ke Whisper lokal, dan hasilnya muncul sebagai `transcript_partial` di Chat dan Transkrip. Hasil final menggantikannya. Teks live hanya tampil saat panel terbuka; saat pill mengecil belum tampil.
- **Tanpa LLM lokal**: lihat §3.
- **Teks live lebih ringan**: partial hanya men-decode 8 detik terakhir (`PARTIAL_WINDOW_SECONDS`), bukan seluruh utterance tiap detik.
- **Bahasa default Indonesia** (`DEFAULT_ASR_LANGUAGE = "id"`): deteksi otomatis pada potongan pendek sering salah bahasa. Ubah lewat Setelan.
- **Opsi ASR yang dipertimbangkan (belum diimplementasi)**: lihat catatan di chat. Azure Speech (`id-ID`, real-time, 5 jam/bulan gratis) dan Vosk (streaming ringan, model Indonesia belum diverifikasi).
