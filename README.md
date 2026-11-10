# Malva

Asisten desktop AI privat untuk Windows. *Your computer, understood.*

## Struktur

| Path | Isi |
|---|---|
| `native/` | Implementasi baru: core Rust (`native/core`) dan kontrak UI TypeScript (`native/ui`). Tahap PoC. |
| `legacy/` | Implementasi Python + pywebview yang masih berjalan. Dipindahkan dari root tanpa perubahan kode. |
| `docs/adr/` | Keputusan arsitektur. ADR-001 mengusulkan stack React Native Windows + Rust. |
| `BLUEPRINT.md`, `HANDOFF.md` | Blueprint produk dan catatan serah terima. Keduanya masih berlaku untuk perilaku aplikasi. |

## Status

- `native/`: PoC awal. Tes Rust dan cek paritas event lolos. Belum ada aplikasi React Native dan belum diuji di Windows.
- `legacy/`: masih berisi aplikasi yang bisa dijalankan. Jalankan dari folder itu (lihat `legacy/tests` dan `legacy/app.py`).

## Menjalankan tes

```bash
cd native/core && cargo test
cd native && ./tests/contract_parity.sh
cd legacy && python -m pytest -q tests/   # butuh requirements-dev.txt
```

Riwayat sebelum pemindahan ada di Git. Untuk mengembalikan struktur lama, gunakan `git revert` pada commit ini.
