# Phase 0: System Architecture & Repository Audit

## 1. Executive Context & Scope

SchemaSense is an enterprise database intelligence, data dictionary, and AST SQL security console. It combines structural database introspection, schema diffing, statistical data profiling with sensitive PII identification, and AST-based SQL sandboxing with multi-model AI inference (Google Gemini, Anthropic Claude, OpenAI, and local llama.cpp / GGUF runtimes).

This audit establishes the baseline technical state of the repository before introducing native Rust acceleration components via PyO3 and Maturin.

---

## 2. Repository Entry Points & Module Boundaries

```
schemasense/
├── app.py                            # Streamlit Reactive Web Console (Presentation & Session State)
├── schemasense/                      # Core Pure-Python Domain Package
│   ├── sql_guard.py                  # AST SQL Validator, single-statement enforcement & bounded execution
│   ├── profiler.py                   # Data Profiling, IQR Outlier Detection & PII Pattern Matching
│   ├── schema_inspector.py           # Relational Metadata Extraction, Foreign Keys, Schema Diffing
│   ├── connection.py                 # SQLAlchemy Connection Pools, Dialect Engines & SSRF Network Sandbox
│   ├── auth.py                       # SSO OAuth 2.0 (Google/GitHub), Token Gates & Session Validation
│   ├── ai_agent.py                   # LLM Query Generation, Grounding & Schema Fidelity Verification
│   ├── telemetry.py                  # Anonymous SQL Query Fingerprinting & PII-scrubbed Metrics
│   ├── rules_engine.py               # PDF Business Constraint Ingestion (pypdf) & XML Prompt Isolation
│   ├── benchmark.py                  # AI Agent SQL Correctness & Hallucination Benchmark Register
│   └── runtime/                      # Local AI Model Runtimes & Parsers
│       ├── types.py                  # Dataclasses (ModelManifest, Architecture, Hyperparameters)
│       ├── compatibility.py          # OS & Architecture Hardware Verification
│       ├── hardware.py               # Hardware Probing (RAM, VRAM, AVX2, Metal, CUDA)
│       ├── registry.py               # Local Model File Discovery & Cache Index
│       ├── backends/                 # Inference Provider Adapters (Gemini, Claude, OpenAI, Llama.cpp)
│       └── parsers/                  # Binary Metadata Extractors
│           ├── gguf.py               # Bounded Binary GGUF v2/v3 Header Parser
│           └── safetensors.py        # SafeTensors 8-byte Length Prefix & JSON Header Parser
```

---

## 3. Allocation of Responsibilities (Python vs. Rust)

Under the agreed hybrid architectural boundary:

### Functionality Retained in Python (Unchanged)
1. **Presentation & State**: `app.py` Streamlit reactive components, session locks, and Plotly charting.
2. **AI Provider Integrations**: Google GenAI (`google-genai`), Anthropic, OpenAI, and local execution invocation.
3. **SSO & Authentication**: OAuth 2.0 authorization code flows, token state nonces, reverse-proxy header checks.
4. **Database Lifecycle**: SQLAlchemy engine creation, dialect-specific reflection, and connection pool pre-ping.
5. **Business Rule PDF Ingestion**: `pypdf` extraction and prompt construction.

### Functionality Targeted for Native Rust Acceleration (`schemasense-core`)
1. **Schema Diffing & Graph Analysis** (`schemasense.schema_inspector`):
   - Fast $O(N)$ comparison of database table, column, and constraint snapshots.
   - Foreign key dependency DAG construction, cycle detection (Tarjan's SCC), and topological ordering using `petgraph`.
2. **Statistical Profiling & PII Scanning** (`schemasense.profiler`):
   - Multi-threaded columnar numeric aggregation (min, max, mean, variance) via `Rayon`.
   - SIMD-accelerated percentile and IQR calculation without Python GIL contention.
   - High-throughput sensitive pattern matching (emails, credit cards, phones) using `aho-corasick` pre-filtering.
3. **Binary Model Parsers** (`schemasense.runtime.parsers`):
   - Zero-copy, bounded memory-mapped GGUF v2/v3 header parsing (`memmap2`).
   - Zero-allocation SafeTensors JSON header extraction with strict size verification.
4. **SQLGuard Security AST Validation** (`schemasense.sql_guard`):
   - Phased migration: Dual-execution shadow validation $\rightarrow$ strict conjunction $\rightarrow$ dialect cutover.

---

## 4. Current Dependencies & Runtime Constraints

### Core Runtime Dependencies (`requirements.txt` / `pyproject.toml`)
- `python >= 3.10`
- `streamlit >= 1.39.0, < 1.60.0`
- `sqlalchemy >= 2.0.0, < 2.1.0`
- `sqlglot >= 30.24.0`
- `pandas >= 2.1.0, < 3.0.0`
- `plotly >= 5.20.0`
- `google-genai >= 2.33.0`
- `pypdf >= 6.21.2`
- `psycopg2-binary >= 2.9.0`
- `pymysql >= 1.1.0`

### Packaging & Compatibility Invariant
- `schemasense` remains a pure-Python package installable on any Python 3.10+ environment without requiring a Rust compiler.
- `schemasense-core` is an optional binary companion package distributed as pre-compiled wheels via PyO3 and Maturin using CPython ABI3 (`cp310-abi3`).
- Installation will be facilitated via optional extra: `pip install schemasense[native]`.

---

## 5. Existing Test Suite Baseline & Verification Status

Executed full offline regression suite via `pytest -m "not docker"`:
- **Total Tests Collected**: 439
- **Passed**: 397 (100% of offline runnable tests)
- **Skipped**: 42 (38 live PostgreSQL/MySQL Docker container integration tests, 3 live AppTest container tests, 1 llama-cpp missing binary test)
- **Failed**: 0
- **Line Coverage**: **80.28%** across 3,160 statements (surpasses 70% CI fail-under threshold).

---

## 6. Security-Critical Paths & Compatibility Hazards

1. **AST Validation Divergence**: Different SQL parsers (`sqlglot` vs `sqlparser-rs`) have subtle dialect-specific syntax differences. A shadow-mode phase with divergence telemetry is mandatory to prevent false positives or security bypasses.
2. **Arrow Buffer Lifetimes**: When passing Arrow RecordBatches across FFI, buffer ownership must be cleanly managed to prevent use-after-free or memory leaks.
3. **Memory Mapping Security**: `memmap2` must enforce upfront file-size and header-boundary checks (max 16MB-64MB) to prevent denial-of-service from maliciously crafted model files.
4. **Fail-Closed Fallback**: If the native `schemasense-core` module fails to load or panics, the system must fail gracefully to the pure-Python implementation without leaking internal tracebacks to end users.

