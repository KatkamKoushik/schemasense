# Phase 0: Risk Register & Mitigation Strategy

## Risk Assessment Matrix

| Risk ID | Category | Risk Description | Severity | Likelihood | Mitigation Strategy |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **R-01** | **Security** | AST validation discrepancies between `sqlglot` and `sqlparser-rs` leading to potential SQL injection or bypass. | Critical | Medium | **Dual-Execution Shadow Mode**: Run Python `sqlglot` authoritatively during initial phases. Log divergences with privacy-safe telemetry. Proceed to double-lock conjunction before any native-only cutover. |
| **R-02** | **Compatibility** | Python environment cannot load native binary wheel due to missing GLIBC, Windows VCRuntime, or unsupported architecture. | High | Medium | **Transparent Pure-Python Fallback**: `schemasense` remains pure-Python. If `import schemasense_core` fails, the application automatically runs Python implementations with zero user-facing errors. |
| **R-03** | **Memory Safety** | Unsafe FFI boundaries, buffer overflow, or use-after-free when passing Apache Arrow RecordBatches across FFI. | Critical | Low | **Enforce `#![deny(unsafe_code)]`**: Restrict `unsafe` solely to the vetted PyO3 C Data Interface boundary. Use Arrow's official `arrow-rs` FFI import/export wrappers. Validate buffer lifetimes with ASan/Miri. |
| **R-04** | **Packaging** | Increased packaging complexity and wheel build failures across cross-platform CI matrices. | Medium | Medium | **CPython ABI3 Stable ABI**: Target `cp310-abi3`. A single wheel per OS/architecture works across Python 3.10, 3.11, 3.12, and 3.13. Use standard GitHub Actions `PyO3/maturin-action`. |
| **R-05** | **Performance** | Data conversion overhead (Pandas $\rightarrow$ Arrow $\rightarrow$ Rust $\rightarrow$ Python) exceeding computational gains for small workloads. | Medium | High | **Dynamic Workload Thresholding**: Only dispatch to native Rust when row count exceeds threshold (e.g. $N > 1,000$ rows). Keep tiny datasets on the fast Python path. |
| **R-06** | **Denial of Service** | Maliciously crafted GGUF/SafeTensors binary headers triggering OOM or CPU freeze. | High | Low | **Strict Header Bounds**: Hard-cap header scan bytes (16MB-64MB), maximum KV pair count (1,000), and max string length (64KB). Zero tensor allocation. |
| **R-07** | **Developer Friction**| Contributing developers required to have Rust toolchain installed to run ordinary tests. | Medium | Low | **Dual Package Decoupling**: Main repository tests default to pure-Python implementations unless `schemasense-core` is explicitly installed. |

---

## Rollback & Escape Hatches

1. **Runtime Override Environment Variable**:
   Setting `SCHEMASENSE_DISABLE_NATIVE_CORE=1` immediately forces all subsystems to bypass native Rust extensions and execute pure-Python paths.
2. **Pip Uninstall**:
   `pip uninstall schemasense-core` restores the system to standard pure-Python execution with zero code changes required.

