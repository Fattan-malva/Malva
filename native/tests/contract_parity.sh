#!/usr/bin/env bash
# Memastikan daftar event sama di tiga tempat: Python (sumber asli), Rust, dan TypeScript.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

py=$(sed -n '/^EVENT_TYPES = (/,/^)/p' "$ROOT/legacy/malva/shell/session.py" | grep -o '"[a-z_]*"' | tr -d '"')
rs=$(sed -n '/pub const EVENT_TYPES/,/^];/p' "$ROOT/native/core/src/events.rs" | grep -o '"[a-z_]*"' | tr -d '"')
ts=$(sed -n '/export const EVENT_TYPES/,/] as const;/p' "$ROOT/native/ui/src/contract.ts" | grep -o '"[a-z_]*"' | tr -d '"')

n_py=$(echo "$py" | wc -l)
echo "Python: $n_py event"
if [ "$py" != "$rs" ]; then echo "GAGAL: Python vs Rust berbeda"; diff <(echo "$py") <(echo "$rs") || true; exit 1; fi
if [ "$py" != "$ts" ]; then echo "GAGAL: Python vs TypeScript berbeda"; diff <(echo "$py") <(echo "$ts") || true; exit 1; fi
echo "OK: daftar event identik di Python, Rust, dan TypeScript"
