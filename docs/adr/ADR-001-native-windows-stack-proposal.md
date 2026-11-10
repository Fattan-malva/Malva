# ADR-001 — Usulan stack native Windows (React Native Windows + Rust)

> Status: **Usulan (Proposed)**. Belum disetujui. Belum ada kode yang dipindahkan.
> Tanggal: 2026-11-11
> Konteks: implementasi saat ini (Python + pywebview, lihat `HANDOFF.md`) tetap menjadi basis yang berjalan.

## 1. Latar belakang

Implementasi saat ini memakai Python dengan UI berbasis pywebview (WebView2). Usulan ini mengevaluasi arsitektur
alternatif: UI memakai React Native Windows (TypeScript, Fabric), integrasi native memakai C++/JSI/TurboModules, dan
core engine (audio, ASR, orkestrasi AI, desktop automation, penyimpanan) memakai Rust.

## 2. Arsitektur yang diusulkan

- **UI**: React Native Windows + TypeScript. Komponen: Floating Pill, Chat Interface, Live Transcript, Workspace.
- **Integrasi native**: C++ / JSI / TurboModules. Lapisan ini hanya menghubungkan JavaScript dengan Rust.
- **Core engine**: Rust. Modul: audio, ai, asr, desktop, session, storage, privacy.
- **Audio**: CPAL + WASAPI (capture dan loopback). Audio mentah tetap di Rust.
- **AI/cloud**: Reqwest + Tokio; Gemini Live (WebSocket); Cloudflare Workers AI (HTTP).
- **Penyimpanan**: SQLite (rusqlite).
- **Automasi eksternal**: Windows-MCP sebagai layanan terpisah.

Koreksi terhadap usulan awal: React Native Windows tidak memanggil Rust secara langsung. Diperlukan lapisan C++ dengan
C ABI/FFI ke Rust, termasuk pengaturan kepemilikan memori dan thread.

## 3. Prinsip antarmuka lintas bahasa

- Audio mentah tidak dikirim per potongan melalui bridge JavaScript. TypeScript hanya menerima status, transkrip,
  dan event.
- Kontrak event harus didefinisikan satu kali (sumber kebenaran) dan diuji di kedua sisi, sama seperti
  `EVENT_TYPES` dan `tests/test_event_contract.py` yang sudah ada di implementasi Python.

## 4. Konsekuensi dan risiko

| Area | Risiko |
|---|---|
| Integrasi Rust | Perlu FFI C++/Rust yang dikelola sendiri |
| Build | Visual Studio, Windows SDK, Rust, Node.js |
| Ekosistem UI | Tidak semua library React Native mendukung Windows |
| Window kustom | Floating pill always-on-top, transparan, dan posisi perlu implementasi native |
| Debugging | Tiga lapisan: TypeScript, C++, Rust |
| Versi | Gunakan React Native Windows 0.82+ (New Architecture). Hindari tutorial Paper/UWP |

## 5. Rencana proof of concept (sebelum migrasi)

Migrasi penuh tidak dilakukan sebelum PoC berhasil. PoC mencakup empat hal:

1. Satu Floating Pill: window transparan, always-on-top, dapat dipindah posisinya.
2. Komunikasi TypeScript → C++ (TurboModule) → Rust, dengan satu panggilan dan satu event balik.
3. Satu tes audio capture dari mikrofon melalui CPAL/WASAPI, dengan hasil level audio dikirim ke UI sebagai event.
4. Catatan hasil: apa yang berhasil, apa yang gagal, dan biaya build/debug yang nyata.

Kriteria lanjut: keempat butir PoC berjalan di perangkat Windows nyata. Jika tidak, ADR ini ditolak dan implementasi
Python tetap dipakai.

## 6. Yang belum diverifikasi

- Semua item PoC di §5 belum dibuat.
- Kompatibilitas WASAPI loopback untuk audio sistem belum diuji.
- Perilaku transparansi dan always-on-top pada React Native Windows belum diuji.
- Biaya pemeliharaan dua basis kode (Python yang berjalan dan Rust/TS yang baru) belum dinilai.

## 7. Keputusan yang diminta

- Setujui atau tolak PoC di §5.
- Jika disetujui, tentukan apakah PoC dikerjakan di cabang terpisah dan kapan dinilai.
