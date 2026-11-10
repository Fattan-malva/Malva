# native/ — Malva: React Native Windows + Rust (tahap PoC)

> Status: **PoC awal, belum dijalankan di Windows.** Mengikuti `docs/adr/ADR-001-native-windows-stack-proposal.md`.
> Implementasi Python (`app.py`, pywebview) tetap menjadi basis yang berjalan sampai PoC lolos di perangkat Windows nyata.

## Isi

| Path | Isi | Status |
|---|---|---|
| `core/` | Crate Rust `malva-core`: kontrak event dan aturan Sleep/Focus/persetujuan suara (port `malva/shell/policy.py`) | 7 tes lolos (`cargo test`) |
| `ui/src/contract.ts` | Kontrak event, state, dan mode untuk UI TypeScript | Belum dikompilasi (belum ada project RN) |
| `tests/contract_parity.sh` | Memastikan daftar event sama di Python, Rust, dan TypeScript | Lolos (25 event) |

## Yang belum ada (sesuai ADR §5)

1. **Floating Pill** di React Native Windows: window transparan, always-on-top, bisa dipindah. Belum ada project RN.
2. **Jalur TypeScript → C++ (TurboModule) → Rust** dengan satu panggilan dan satu event balik. Belum ada kode C ABI/FFI.
3. **Capture mikrofon** lewat CPAL/WASAPI dengan level dikirim ke UI. Belum ada crate audio.
4. **Catatan hasil PoC** di Windows nyata (biaya build dan debug yang sebenarnya).

Migrasi penuh tidak dimulai sebelum butir 1–4 lolos.

## Cara menjalankan tes di sandbox ini

```bash
cd native/core && cargo test
cd native && ./tests/contract_parity.sh
```

Tes Rust tidak membutuhkan dependensi eksternal dan tidak butuh Windows.

## Keputusan terbuka

- **`requires_approval` belum lengkap.** Versi Rust hanya memeriksa nama tool (`delete`). Versi Python juga memeriksa pola teks lewat `safety.is_destructive`. Pola itu perlu dipindah atau diputuskan ulang sebelum dipakai.
- **Klaim "sangat ringan" belum terukur.** Hermes, runtime XAML, dan window transparan punya biaya memori dan CPU sendiri. Ukuran biner Rust sudah dikecilkan di `Cargo.toml` (`opt-level = "z"`, LTO, strip), tetapi angka pemakaian RAM dan CPU nyata hanya bisa diambil dengan mengukur di Windows.
- **Hidden Mode.** Implementasi Python memakai `SetWindowDisplayAffinity`. Versi native harus memasangnya lewat C++ dan perlu diuji ulang.
- **Lingkungan build.** Visual Studio dengan workload C++ dan Windows SDK, Rust (target `x86_64-pc-windows-msvc`), Node.js, dan React Native Windows 0.82+ (New Architecture).

## Yang tidak diverifikasi di sandbox ini

- Build dan jalan di Windows (tidak tersedia di lingkungan ini).
- React Native Windows, TurboModule, dan FFI Rust.
- WASAPI, loopback audio sistem, dan transparansi window.
- Ukuran biner dan pemakaian memori di perangkat nyata.
