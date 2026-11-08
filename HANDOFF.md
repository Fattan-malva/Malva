# HANDOFF.md — Malva Project
> **Update otomatis setiap sesi kerja. Baca file ini sebelum melanjutkan.**
> Last updated: 2026-11-09 · Phase: 1–3 SELESAI + CRITICAL BUGFIXES (Audio Spectrum & Solid Black Native Window)

---

## 1. Tujuan & Arsitektur

**Malva** adalah rebrand dan evolusi dari **Nana** — private AI desktop copilot untuk Windows.
Tagline: *"Your computer, understood."*
Referensi blueprint lengkap: [`Blueprint.md`](./Blueprint.md)

### Standar Kualitas Desain (Hallmark & Impeccable Standards)
- **Zero White Edges & Native DWM Rounded Window**: Window menggunakan `background_color="#000000"`, `transparent=False`, serta Win32 API `DwmSetWindowAttribute` (`DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2`) sehingga Windows 11 membulatkan sudut jendela secara native hardware tanpa sisa kotak putih di ujung-ujung.
- **Solid Pure Black (#000000), Tanpa Glass**: Seluruh efek translucent blur/glass dihilangkan. Warna murni hitam pekat solid `#000000` dengan border tipis `#222226`.
- **Zero Purple Color**: Seluruh warna ungu/indigo/violet telah diganti menjadi palet monokromatik netral (putih `#f8fafc`, slate `#a1a1aa`, zinc `#3f3f46`) dengan aksen fungsional hijau `#22c55e` (listening), merah `#ef4444` (mic/speech), dan kuning `#f59e0b` (processing).
- **5-Bar Responsive Live Spectrum**: 5-bar equalizer visualizer telah dipulihkan dan dikendalikan langsung oleh nilai RMS audio nyata dari mikrofon via `pyaudio` chunk per chunk (`window.updateBars(levels)`).
- **Audio Capture & VAD Stabil**: Dukungan multi-sample-rate fallback (`16000`, `44100`, `48000` Hz) untuk mencegah kegagalan mic rate Windows, dilengkapi pre-speech buffer (`PRE_BUFFER_CHUNKS = 12`) dan VAD threshold terkalibrasi (`SPEECH_THRESHOLD = 65.0`, `SILENCE_THRESHOLD = 35.0`).
- **In-Settings Model Manager**: Pemuatan Whisper berjalan asynchronous di background tanpa membekukan UI saat startup.

### Struktur Proyek (100% Modular & Clean)
```
Nana/
├── .env                 (Konfigurasi runtime lokal)
├── .env.example         (Contoh konfigurasi)
├── .gitignore           (Git ignore file)
├── app.py               (Entry point utama Malva)
├── Blueprint.md         (Malva Product & Technical Blueprint v1)
├── HANDOFF.md           (Dokumentasi progress & handoff terupdate)
├── requirements.txt     (Daftar dependensi runtime)
└── malva/               (Semua modul aplikasi Malva)
    ├── ai/              (AI Orchestrator & Cross-Meeting memory)
    ├── asr/             (ASR Model Router & cache detection)
    ├── audio/           (Dual-track capture: Mic dengan live 5-bar spectrum + System Audio)
    ├── desktop/         (Desktop Tool Gateway & Permissions)
    │   └── tools/       (Suite otomasi desktop, browser, shell)
    ├── interview/       (Interview Practice & Notes engines)
    ├── meeting/         (Meeting Intelligence, ringkasan & action items)
    ├── privacy/         # Hidden Mode (WDA_EXCLUDEFROMCAPTURE) manager
    ├── shell/           (Session lifecycle, Focus Mode, Sleep Mode)
    ├── storage/         (SQLite engine & memori lintas-sesi)
    ├── transcript/      (Transcript core segment pipeline)
    └── ui/              (Floating pill solid black UI & 5-bar spectrum)
```

---

## 2. Rincian Perbaikan Bug Terkini (Critical Fixes) ✅

1. **Sisa Kotak Putih & Sudut Window**:
   - `transparent=True` pada WebView2 menyebabkan clear-color default putih bocor di ujung sudut rounded.
   - Solusi: Window diatur ke `background_color="#000000"`, `transparent=False`, dengan `html, body` solid `#000000`.
   - Menambahkan panggilan native Win32 DWM `DwmSetWindowAttribute(hwnd, 33, DWMWCP_ROUND)` untuk pembulatan native Windows 11.
2. **Menghapus Warna Ungu & Glass**:
   - Menghapus semua color token ungu (`#6366f1`, `#818cf8`, `#a5b4fc`).
   - Menghapus `backdrop-filter: blur()`. Menggunakan warna solid hitam `#000000` dengan kontras tinggi.
3. **Spectrum Hilang & Tidak Bisa Listening**:
   - Memulihkan **5-bar Spectrum Visualizer** di statusbar floating pill.
   - Di `malva/audio/capture.py`: Menambahkan kalkulasi RMS 5-band per chunk audio dan callback `on_levels`.
   - Di `malva/shell/session.py` & `app.py`: Meneruskan event `audio_levels` secara live ke JavaScript `window.updateBars(levels)`.
   - Mengatasi masalah stream mic gagal dengan menambahkan sample rate fallback (`16000`, `44100`, `48000` Hz) dan VAD pre-buffering.

---

## 3. Cara Menjalankan 🚀

Jalankan di terminal PowerShell:

```powershell
python app.py
```
- Jendela solid black floating pill Malva akan langsung terbuka di desktop dengan sudut rounded rapi tanpa sisa putih.
- Saat berbicara ke mic, 5 bar visualizer akan langsung bergerak/menari mengikuti intensitas suara Anda.
