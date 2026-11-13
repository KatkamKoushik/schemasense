## Description

Please include a summary of the change, relevant motivation, and context. Mention any dependencies required for this change.

Fixes # (issue)

---

## Type of Change

Please delete options that are not relevant:

- [ ] **Bug fix** (non-breaking change which fixes an issue)
- [ ] **New feature** (non-breaking change which adds functionality)
- [ ] **Performance improvement** (acceleration or memory optimization)
- [ ] **Breaking change** (fix or feature that would cause existing functionality to not work as expected)
- [ ] **Security hardening** (guardrail enhancement or vulnerability mitigation)
- [ ] **Documentation update**

---

## Architecture & Parity Checklist

- [ ] Changes in `crates/schemasense_core` adhere strictly to `#![deny(unsafe_code)]`.
- [ ] Pure-Python fallback paths exist and are verified with `SCHEMASENSE_DISABLE_NATIVE_CORE=1`.
- [ ] Zero database-level read-only security boundaries or row limit caps bypassed.
- [ ] Zero API keys, credentials, or secrets introduced or committed.

---

## Quality Gates Checklist

- [ ] `ruff check schemasense/ tests/` passes with zero errors.
- [ ] `ruff format --check schemasense/ tests/ app.py` passes.
- [ ] `mypy schemasense --ignore-missing-imports` passes.
- [ ] `cargo fmt --all -- --check` passes (if Rust code was changed).
- [ ] `cargo clippy --workspace --all-targets -- -D warnings` passes (if Rust code was changed).
- [ ] `cargo test --workspace` passes (if Rust code was changed).
- [ ] `pytest -v --ignore=tests/test_live_integration.py` passes with coverage >= 70%.
- [ ] `python scripts/security_audit.py` passes.
- [ ] `detect-secrets scan --baseline .secrets.baseline` passes.
