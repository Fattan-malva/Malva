//! malva-core — logika murni Malva (tanpa thread, audio, UI, atau jaringan).
//!
//! Port dari `malva/shell/policy.py` dan `EVENT_TYPES` di `malva/shell/session.py`.
//! Kontrak event dijaga oleh `native/ui/src/contract.ts` dan dicek di `tests/contract_parity.sh`.

pub mod events;
pub mod policy;
