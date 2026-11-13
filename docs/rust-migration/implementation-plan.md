# Phase 0: Phased Implementation Roadmap & Verification Checklist

## 1. Project Organization: Cargo Workspace & Dual Package

The repository structure decouples the pure-Python `schemasense` package from the native `schemasense-core` binary extension:

```
schemasense/
├── Cargo.toml                       # Top-level Cargo workspace
├── pyproject.toml                   # schemasense pure-Python package config
├── schemasense/                     # Python package (UI, Auth, Connection, Fallbacks)
│   ├── sql_guard.py                 # Hybrid dispatcher (sqlglot / native)
│   ├── profiler.py                  # Hybrid dispatcher (Pandas / native Arrow)
│   ├── schema_inspector.py          # Hybrid dispatcher (Python / native graph)
│   └── runtime/parsers/             # Hybrid dispatcher (struct / native memmap2)
├── crates/
│   ├── schemasense_core/            # PyO3 Python Extension Crate (Maturin package)
│   │   ├── Cargo.toml               # Package definition for schemasense-core
│   │   ├── pyproject.toml           # Maturin build config for schemasense-core
│   │   └── src/
│   │       ├── lib.rs               # PyO3 module definition & exception bindings
│   │       ├── arrow_ffi.rs         # Apache Arrow C Data Interface wrappers
│   │       ├── sql_guard_py.rs      # PyO3 bindings for SQL validation
│   │       ├── profiler_py.rs       # PyO3 bindings for columnar profiling
│   │       └── parsers_py.rs        # PyO3 bindings for GGUF/SafeTensors
│   ├── schemasense_sqlguard/        # Pure Rust SQL AST Engine
│   ├── schemasense_profiler/        # Pure Rust SIMD Profiler & Aho-Corasick PII
│   ├── schemasense_parsers/         # Pure Rust Bounded Binary Model Parsers
│   └── schemasense_graph/           # Pure Rust Petgraph Dependency DAG & Diff
└── tests/
    ├── test_native_equivalence.py   # Differential equivalence test suite
    └── ... (existing 27 test files preserved)
```

---

## 2. Phase-by-Phase Execution Plan

### Phase 0: Audit & Performance Baseline (CURRENT)
- [x] Read-only audit of entry points, public APIs, and security paths (`audit.md`).
- [x] Measure deterministic empirical baseline across all subsystems (`benchmark-baseline.md`).
- [x] Establish comprehensive risk register and rollback mechanisms (`risk-register.md`).
- [x] Document roadmap and definitions of done (`implementation-plan.md`).
- **Gate**: Present Phase 0 deliverables for review and obtain approval before creating code.

### Phase 1: Rust Foundation & Minimal Native Module (COMPLETED & VERIFIED)
- [x] Create Cargo workspace root with `#![deny(unsafe_code)]` workspace lint configuration.
- [x] Implement `crates/schemasense_core` using PyO3 0.22+ targeting CPython ABI3 (`cp310-abi3`).
- [x] Configure `crates/schemasense_core/pyproject.toml` with `maturin` build-backend.
- [x] Expose minimal sanity check function `schemasense_core.version()`, `schemasense_core.is_native_accelerated()`, and `schemasense_core.build_info()`.
- [x] Implement transparent import check and diagnostic helper in `schemasense/__init__.py`:
  ```python
  HAS_NATIVE_CORE: bool
  get_native_core_info() -> dict[str, Any]
  ```
- [x] Verify clean builds, formatting (`cargo fmt`), linting (`cargo clippy --workspace -- -D warnings`), and tests (`cargo test --workspace` - 3 passed).
- [x] Build ABI3 wheel (`schemasense_core-0.1.0-cp310-abi3-win_amd64.whl`) and install via pip.
- [x] Add Python regression unit tests in `tests/test_native_foundation.py` (4 passed).
- [x] Verify full regression suite: 401 passed, 42 skipped, 80.16% coverage.
- **Definition of Done Status**: **ACCEPTED**. The Rust extension compiles and imports cleanly, and the application remains 100% functional with zero regressions.


### Phase 2: Computational Acceleration (Diffing, Graph & Profiling) (COMPLETED & VERIFIED)
- [x] **Schema Graph & Diffing (`schemasense_core::graph`)**:
  - Implement table/column/constraint diffing with $O(N)$ hash comparisons.
  - Implement foreign key dependency DAG using `petgraph::Graph`.
  - Implement cycle detection using Tarjan's SCC algorithm (`tarjan_scc`) and topological sorting (`toposort`).
  - Return serializable diff structures matching Python `SchemaDiff`.
- [x] **Columnar Profiling (`schemasense_core::profiler`)**:
  - Implement parallel numerical statistics (min, max, mean, variance) via `Rayon`.
  - Implement quantile/IQR calculation and outlier boundary detection.
  - Implement multi-pattern PII matching using precompiled static regex (`RegexSet`).
- [x] Add dual-dispatch in `schemasense/schema_inspector.py` and `schemasense/profiler.py`.
- [x] Add unit and differential equivalence tests in `tests/test_native_acceleration.py`.
- **Definition of Done Status**: **ACCEPTED**. 100% equivalence on synthetic and real datasets; 4.7× speedup on PII regex scanning, full Tarjan SCC cycle resolution.

### Phase 3: Binary Model Metadata Parsers (COMPLETED & VERIFIED)
- [x] **GGUF Parser (`schemasense_core::parsers::gguf`)**:
  - Bounded binary parsing with upfront size verification.
  - Enforce bounds: max 16MB metadata scan, max 1,000 KV pairs, max 64KB string length, max 65,536 array elements.
  - Zero allocation for tensor payload segments.
  - Extract architectural hyperparameters, quantization type, license, and chat template.
- [x] **SafeTensors Parser (`schemasense_core::parsers::safetensors`)**:
  - Read initial 8-byte uint64 length header with strict file size boundary check.
  - Safely parse JSON header up to 16MB limit using `serde_json`.
  - Merge companion `config.json` when present.
- [x] Expose metadata to Python matching `ModelManifest` dataclass contract.
- [x] Implement dual-dispatch with pure-Python fallback in `schemasense/runtime/parsers/gguf.py` and `safetensors.py`.
- [x] Verify adversarial inputs: truncated files, invalid magic, version 99, KV bombs, string bombs, array bombs, and oversized headers.
- **Definition of Done Status**: **ACCEPTED**. 14 Rust unit tests passed (0 warnings), 19/19 Python parser tests passed with native and fallback; measured 3.4× speedup on GGUF and 1.7× on SafeTensors.

### Phase 4: SQLGuard Shadow Validation & Strict Conjunction (COMPLETED & VERIFIED)
- [x] **Phase 4A: Rust Security Engine (`schemasense_core::sql_guard`)**:
  - Implement zero-allocation AST security visitor using `sqlparser-rs` 0.64.
  - Enforce single-statement SELECT constraints, forbidden write constructs (Insert, Update, Delete, Drop, Alter, Create, Truncate, Merge, Grant, Revoke), system catalog blocklists, and 30+ dangerous SQL functions.
  - Implement recursive CTE scope stack to prevent false positives and prevent F-01 schema-collision bypasses.
- [x] **Phase 4B: Shadow Validation Mode**:
  - In `schemasense.sql_guard.validate()`, run both Python `sqlglot` and native Rust `schemasense_core.validate_sql`.
  - Python verdict remains authoritative and returned to the caller.
  - Add privacy-safe divergence logging (`log_sqlguard_divergence`) hashing query fingerprints.
- [x] **Phase 4C: Strict Conjunction (Double-Lock)**:
  - Add `ENFORCE_DOUBLE_LOCK` and `SCHEMASENSE_SQLGUARD_DOUBLE_LOCK=1` support requiring both Python and Rust validators to approve.
- [x] Expose direct native verification via `SQLGuard.validate_native()`.
- [x] Add unit and differential equivalence tests in `tests/test_native_acceleration.py`.
- **Definition of Done Status**: **ACCEPTED**. Zero false-negatives across existing 452 tests and Hypothesis adversarial suites; **42.9× speedup** ($14.1\ \mu\text{s}$ vs $606.3\ \mu\text{s}$, **70,675 queries/sec**).

### Phase 5: CI/CD, Packaging, Cross-Platform Wheels & Fuzzing (COMPLETED & VERIFIED)
- [x] Add GitHub Actions workflow `.github/workflows/wheels.yml` using `PyO3/maturin-action` building:
  - Linux: `manylinux_2_17_x86_64`, `manylinux_2_17_aarch64`
  - Windows: `x86_64-pc-windows-msvc`
  - macOS: `x86_64-apple-darwin`, `aarch64-apple-darwin`
  - Source distribution (`sdist`)
- [x] Expand `tests/test_sql_guard_hypothesis.py` into a differential property-based fuzzing suite comparing Python and Rust AST visitors across random queries and write keywords.
- [x] Configure `pyproject.toml` with optional extra:
  ```toml
  [project.optional-dependencies]
  native = [
      "schemasense-core>=0.1.0",
      "pyarrow>=15.0.0",
  ]
  ```
- [x] Verify code quality gates: Ruff linting (`ruff check`) and formatting (`ruff format --check`) pass with 0 errors.
- [x] Verify Rust quality gates: `cargo clippy` (0 warnings), `cargo fmt --check`, and 20 unit tests pass.
- [x] Verify full regression test suite: 412 passed, 42 skipped, 0 failures, 75% coverage.
- **Definition of Done Status**: **ACCEPTED**. Dual-package distribution, cross-platform CI matrix, and automated differential verification complete.

