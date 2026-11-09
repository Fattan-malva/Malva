# HANDOFF.md — Malva

> Terakhir diperbarui: 2026-11-09.
> Blueprint produk: **`BLUEPRINT.md`**. Keputusan produk yang berlaku ada di §3.
> Status: tahap test awal. Semua cloud disetujui, tier gratis Gemini, tanpa model lokal.

---

## 1. Ringkasan

- Transkripsi berjalan lewat **Gemini Live** (`gemini-3.5-transcribe-live`), satu stream per sumber audio.
- Faster-whisper, SpeechRecognition, dan semua model lokal sudah dihapus.
- Cloud disetujui untuk transkripsi (Gemini), AI (Ollama cloud), dan pencarian web. Satu saklar: `CLOUD_ENABLED` di `.env` (default `true`).
- Semua tool desktop diberi izin otomatis. Hanya aksi hapus yang butuh persetujuan: klik di panel, atau ucapan dari mikrofon ("setuju" / "ya hapus" untuk setuju, "batal" untuk tolak). Persetujuan berlaku 120 detik.
- Startup: pembukaan perangkat audio dipindah ke thread latar, dan `scipy` dimuat saat pertama dipakai.

## 2. Mode dan sumber audio (BLUEPRINT §4)

| Mode | Sumber default | Catatan |
|---|---|---|
| Asisten | Mikrofon + audio sistem (track terpisah) | Audio sistem hanya konteks transkrip |
| Meeting | Audio sistem saja | |
| Latihan wawancara | Mikrofon | Jawaban hanya maju lewat aksi eksplisit |
| Catatan wawancara | Mikrofon | |
| Input suara | Mikrofon saja | Menolak audio sistem |

Audio sistem tidak pernah dialihkan diam-diam ke mikrofon. Jika loopback gagal, sumber dilaporkan dengan `capture_error`.

## 3. Transkripsi (BLUEPRINT §9)

- `malva/asr/gemini_live.py`: `GeminiLiveStream`. Audio PCM 16 kHz mono dikirim per potongan. `interim_input_transcription` menjadi teks sementara (ditampilkan, tidak disimpan). `input_transcription` menjadi teks final (masuk transkrip dan AI).
- Stream menyambung ulang setelah 9 menit (batas API 10 menit). Antrean dibatasi 300 potongan; saat jaringan macet, audio tertua dibuang dan dihitung di `dropped_chunks`.
- `malva/asr/service.py`: `ASRService` memutuskan apakah transkripsi boleh jalan (ada `GEMINI_API_KEY` dan `CLOUD_ENABLED` tidak `false`).
- `malva/audio/capture.py`: mengirim PCM 16 kHz (resample dari rate perangkat). Tidak ada segmentasi utterance.

## 4. Privasi dan cloud (BLUEPRINT §3, §11)

- `malva/privacy/manager.py`: `allows_cloud()` adalah satu-satunya gerbang. Dipakai oleh transkripsi, orchestrator AI, dan pencarian web.
- Tidak ada opt-in di aplikasi dan tidak ada toggle di Setelan. Setelan hanya menampilkan status.
- Hidden Mode tetap memakai `SetWindowDisplayAffinity`. Ini bukan jaminan tidak terlihat.

## 5. Izin tool dan persetujuan (BLUEPRINT §10)

- `malva/desktop/gateway.py`: `requires_approval(tool, args)` = nama tool mengandung `delete`, atau argumen cocok dengan pola hapus di `safety.py`.
- Panggilan non-destruktif jalan langsung. Destruktif menunggu persetujuan (`approved=True`).
- `malva/shell/session.py`: ucapan yang mengusulkan aksi non-destruktif langsung dijalankan. Yang destruktif masuk daftar pending. Persetujuan lewat ucapan hanya dari mikrofon (`_handle_voice_decision`).
- `malva/shell/policy.py`: `voice_decision()` hanya menerima frasa penuh, bukan kalimat yang mengandung kata itu.
- Lapisan `safety.py` tetap memblokir teks hapus di `keyboard.py` dan perintah shell tertentu. Jadi aksi hapus yang sudah disetujui bisa tetap ditolak di lapisan itu. Ini perlu diputuskan lagi.

## 6. Kontrak event (sumber kebenaran: `EVENT_TYPES` di `malva/shell/session.py`)

Event dikirim ke `app.py` lalu ke halaman lewat `window.<nama>`. `tests/test_event_contract.py` memastikan daftar, pemancar, dan penangan sama. Event transkripsi baru: `transcript_partial` (teks sementara) dan `asr_error` (kode `asr-not-configured`, `asr-cloud-disabled`, `asr-failed`).

## 7. Tes

```
pip install -r requirements-dev.txt
python -m pytest -q tests/
```

Status terakhir: **125 lolos**. Tes tidak memakai jaringan, mikrofon, atau Windows. Tes Gemini memakai klien SDK palsu.

Catatan lingkungan: di sandbox pengembangan, `httpx` tidak bisa dipasang dari PyPI. Tes dijalankan dengan `httpx` dari instalasi lain lewat `PYTHONPATH`. Di Windows dengan `pip install` biasa, langkah itu tidak diperlukan.

## 8. Yang TIDAK diverifikasi

- Panggilan nyata ke Gemini Live (SDK `google-genai` belum terpasang di sandbox; nama field SDK perlu dicek saat dijalankan).
- Batas free tier per model (RPM, TPM, RPD) dan kebijakan pemakaian data tier gratis. Halaman resmi tidak menyebutkannya. Untuk audio rapat, ini harus dicek sebelum production.
- Semua hal Windows: loopback WASAPI, mikrofon nyata, render WebView2, lebar panel kanan (keluhan terpotong belum dibuktikan dengan tangkapan layar), hotkey, drag jendela, Hidden Mode.
- Auto-sleep dan persetujuan suara di perangkat nyata. Persetujuan suara bisa dipicu suara lain di ruangan. Sudah dibatasi (frasa penuh, mikrofon saja, 120 detik), tetapi belum diuji.

## 9. Konfigurasi

Salin `.env.example` menjadi `.env`. Isi `GEMINI_API_KEY` untuk transkripsi, dan `OLLAMA_API_KEY` untuk AI. `CLOUD_ENABLED=false` mematikan semua cloud.

## 10. Log dan diagnosa

- `%LOCALAPPDATA%\Malva\logs\malva.log` dan `crash.log`. Log tidak berisi transkrip atau audio.
