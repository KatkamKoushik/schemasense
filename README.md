# SchemaSense AI — Intelligent Data Dictionary & Enterprise Data Agent

> **Built for Enterprise Relational Databases** | Universal Multi-Cloud & Local AI Inference Engines (**Google Gemini**, **OpenAI**, **Anthropic Claude**, **DeepSeek**, **Groq**, **Ollama**, **Custom Gateways**, **llama.cpp**) | **SQLAlchemy** | **Streamlit**

[![SchemaSense CI](https://github.com/KatkamKoushik/neural-nexus-schemasense/actions/workflows/ci.yml/badge.svg)](https://github.com/KatkamKoushik/neural-nexus-schemasense/actions/workflows/ci.yml)
[![Python Versions](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.39%2B-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![Security: SQLGuard AST](https://img.shields.io/badge/Security-SQLGuard%20AST-10B981?logo=shield)](docs/security/threat-model.md)
[![Tests: Pytest](https://img.shields.io/badge/Tests-382%20Total%20%7C%20100%25%20Passing-brightgreen?logo=pytest)](tests/)
[![Coverage](https://img.shields.io/badge/Coverage-91%25-brightgreen)](tests/)
[![Supply Chain: CycloneDX](https://img.shields.io/badge/SBOM-CycloneDX%20v1.5-blue?logo=owasp)](sbom.cyclonedx.json)
[![Secrets: Scanned](https://img.shields.io/badge/Secret%20Scan-detect--secrets-success)](.secrets.baseline)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An enterprise AI Data Steward and Schema Intelligence Agent that connects to relational databases (**PostgreSQL**, **MySQL**, **SQLite**) to **generate interactive data dictionaries, enforce AST-based SQL guardrails, audit data quality, track schema evolution & drift, bound database concurrency, ground queries in business rules, and execute structured AI inference with any cloud or local model**.

---

## Highlights

- **Universal Multi-Cloud & Local AI Architecture**: Connect any model, any provider, and any custom gateway. Natively supports **Google Gemini**, **OpenAI** (GPT-4o, o1, o3-mini), **Anthropic Claude** (Claude 3.5 Sonnet, Haiku), **DeepSeek** (V3, R1), **Groq** (Llama 3.3 70B, Mixtral), **Ollama** (local HTTP/self-hosted), **Custom OpenAI-compatible gateways**, and **llama.cpp** (local in-process GGUF inference with lazy weight allocation and zero cloud fallback).
- **Interactive Multi-Palette Theme Engine**: Hand-crafted, high-contrast accessible visual designs including **Clean Light**, **Obsidian Dark**, **Steel Gray**, and **Deep Ocean Navy**. Adapts all text, cards, form inputs, and metric chips dynamically without page reloads.
- **AST-Based SQLGuard**: Dialect-aware parser powered by `sqlglot`. Strictly enforces single read-only `SELECT` statements, validates tables against an active allowlist, blocks destructive DDL/DML, and enforces database-level statement timeouts and row caps (1,000 rows).
- **Least-Privilege Enforcement**: Active runtime catalog inspection identifying superuser or admin credentials without relying on naive username heuristics. Includes interactive UI policy toggles to reject privileged connections.
- **Deep Schema Intelligence & Evolution Diffing**: Extracts tables, columns, primary keys, unique constraints, foreign keys, and indexes. Capture live schema snapshots and perform deterministic schema drift diffing (detecting added/removed tables, column additions, and type modifications).
- **Data Quality & Profiling**: Calculates null percentages, distinct counts, candidate primary keys, duplicate row rates, numeric outlier detection (IQR), and computes a composite Data Quality Score (0–100%).
- **Bounded Concurrency & Pool Management**: Bounded SQLAlchemy `QueuePool` with session timeouts, client-side concurrency semaphores, and safe pool disposal on disconnect.
- **Supply-Chain Security Gates**: Continuous vulnerability auditing (`pip-audit`), secret scanning (`detect-secrets`), reproducible builds (`constraints.txt`), and CycloneDX SBOM release artifacts.

---

## Supported Environments

| Component | Supported Versions | Notes |
|---|---|---|
| **Python** | 3.10, 3.11, 3.12 | Verified across automated GitHub Actions matrix. |
| **PostgreSQL** | 14, 15, 16 | Tested against `postgres:16-alpine`. Uses `psycopg2-binary`. |
| **MySQL** | 8.0, 8.4 LTS | Tested against `mysql:8.4`. Uses `pymysql` with `utf8mb4`. |
| **SQLite** | 3.x | In-memory and local file testing with zero driver install. |
| **Cloud AI Providers** | Google Gemini, OpenAI, Anthropic Claude, DeepSeek, Groq | Direct API integration with streaming, rate-limit retry, and structured Pydantic decoding. |
| **Local / Custom AI** | Ollama, OpenAI-compatible Gateways, llama.cpp (GGUF) | Flexible local and on-premise execution with zero cloud egress. |

---

## Quick Start

### 1. Clone & Install Dependencies

```bash
git clone https://github.com/KatkamKoushik/neural-nexus-schemasense.git
cd neural-nexus-schemasense

# Standard installation (cloud AI providers + database drivers):
pip install -r requirements.txt -r requirements-dev.txt

# Optional: Add local GGUF inference engine:
pip install -r requirements-local.txt

# For reproducible, constraint-locked deployment:
pip install -r requirements.txt -c constraints.txt
```

### 2. Run Test Suite & Coverage

Verify the security boundaries, backend contracts, and analytical logic across the test suite (**382 tests total with 100% pass rate**):

- **Fast Unit, AST Guardrail & Contract Suite (340 tests)**: In-memory SQLite, mock schemas, AST SQLGuard adversarial syntax, universal AI backend resilience, and UI headless AppTests. Executes in <30 seconds without external dependencies.
- **Live Multi-Database Suite (42 tests)**: Real PostgreSQL 16, MySQL 8.4, and SQLite container tests. Automatically executes when test containers are active, or skips safely when offline.

```bash
# 1. Run fast offline test suite (340 tests):
pytest -v -m "not docker"

# 2. Fast isolated unit suite with coverage:
pytest -v --ignore=tests/test_live_integration.py --cov=schemasense --cov-report=term-missing

# 3. Full live container suite (requires Docker test containers):
docker compose -f docker-compose.test.yml up -d --wait
pytest -v --cov=schemasense --cov-report=term-missing
```

### 3. Supply-Chain & Security Audit Commands

```bash
# 1. Dependency vulnerability audit
pip-audit -r requirements.txt

# 2. Secret scanning against baseline
detect-secrets scan --baseline .secrets.baseline --exclude-files "(\.git|__pycache__|\.venv|venv|\.secrets\.baseline)"

# 3. Generate CycloneDX SBOM
cyclonedx-py requirements constraints.txt -o sbom.cyclonedx.json

# 4. Code quality and formatting checks
python -m ruff check app.py schemasense/ tests/
python -m ruff format --check app.py schemasense/ tests/
```

### 4. Configure Inference Providers

SchemaSense allows selecting your preferred AI gateway directly in the sidebar or via configuration:

#### Option A: Google Gemini (Cloud)
Configure via `.streamlit/secrets.toml` or environment variable:
```toml
GEMINI_API_KEY = ""  # Place your Google Gemini API key here
# Multi-key round-robin rotation:
GEMINI_KEYS = ["", ""]
```

#### Option B: OpenAI / Anthropic / DeepSeek / Groq / Ollama / Gateways
In the sidebar **Inference Engine** section:
1. Select your provider (**OpenAI**, **Anthropic Claude**, **DeepSeek**, **Groq**, **Ollama**, or **Custom Gateway**).
2. Enter your API key (or leave blank for local Ollama).
3. Optionally customize the model name or gateway base URL (e.g. `http://localhost:11434/v1` for Ollama, `https://api.deepseek.com/v1` for DeepSeek).
4. Click **⚡ Ping Provider** to verify credentials and connectivity immediately.

#### Option C: llama.cpp (Local GGUF)
1. Install local dependencies: `pip install -r requirements-local.txt`
2. Select **llama.cpp (Local GGUF)** in the sidebar and enter your local `.gguf` file path.
3. Inference runs in-process with zero network traffic.

### 5. Run Application

```bash
streamlit run app.py
```

---

## Architecture

```
neural-nexus-schemasense/
├── schemasense/                    # Core Python Backend Package
│   ├── __init__.py
│   ├── ai_agent.py                 # Multi-provider AI agent & session-isolated caching
│   ├── runtime/                    # Universal Inference Runtime Subsystem
│   │   ├── backends/               # Base contract, Gemini, OpenAI, Claude, and llama.cpp backends
│   │   │   ├── base.py             # InferenceBackend contract & streaming protocols
│   │   │   ├── gemini.py           # Google Gemini SDK adapter with key rotation
│   │   │   ├── openai_compat.py    # Universal OpenAI-compatible adapter (OpenAI, DeepSeek, Groq, Ollama)
│   │   │   ├── anthropic_backend.py# Anthropic Claude Messages API adapter
│   │   │   └── llama_cpp.py        # Local in-process GGUF adapter
│   │   ├── parsers.py              # Zero-dependency GGUF metadata parser
│   │   ├── registry.py             # Local model discovery and integrity verification
│   │   ├── hardware.py             # Memory and accelerator capability detection
│   │   └── compatibility.py        # Model compatibility and memory estimator
│   ├── connection.py               # Safe URL creation, engine lifecycle, least-privilege inspection, pool disposal
│   ├── sql_guard.py                # AST parser (sqlglot), table allowlists, dialect timeouts & row caps
│   ├── schema_inspector.py         # PKs, FKs, constraints, indexes, data dictionaries & schema drift diffing
│   ├── profiler.py                 # Data quality metrics, outlier detection, scoring formula
│   ├── rules_engine.py             # PDF business-rule ingestion (pypdf) & prompt grounding
│   └── benchmark.py                # Synthetic workload & latency benchmark harnesses
├── tests/                          # 382 Unit, Adversarial, Integration, and AppTest tests
│   ├── conftest.py                 # SQLite test fixtures & mock schemas
│   ├── test_backends_base.py       # Neutral backend contract tests
│   ├── test_backends_gemini.py     # Gemini backend & key rotation tests
│   ├── test_backends_openai.py     # Universal OpenAI / DeepSeek / Groq backend tests
│   ├── test_backends_anthropic.py  # Anthropic Claude backend tests
│   ├── test_backends_llama_cpp.py  # llama.cpp local backend & lazy-loading tests
│   ├── test_backend_selection.py   # Explicit backend selection & multi-provider factory tests
│   ├── test_ai_agent.py            # AI agent structured output & fallback tests
│   ├── test_sql_guard.py           # 50 adversarial SQL, dialect, and AST tests
│   ├── test_connection.py          # 13 connection security, pool, SQLite & concurrency tests
│   ├── test_inspector.py           # Schema inspection, diffing, and export tests
│   ├── test_profiler.py            # Quality metrics and outlier detection tests
│   ├── test_rules_engine.py        # PDF business rule parsing tests
│   ├── test_runtime_parsers.py     # GGUF parser tests
│   ├── test_runtime_registry.py    # Model discovery & SHA256 integrity tests
│   ├── test_runtime_hardware.py    # Hardware detection tests
│   ├── test_runtime_compatibility.py # Runtime compatibility tests
│   ├── test_dependency_hygiene.py  # Dependency hygiene & import boundary tests
│   ├── test_ui_apptest.py          # Streamlit headless AppTest integration tests
│   ├── test_ui_enterprise.py       # Enterprise UI themes, multi-backend selection & SQLite tests
│   └── test_live_integration.py    # Live PostgreSQL 16 & MySQL 8.4 container tests
├── .github/
│   ├── workflows/
│   │   └── ci.yml                  # Automated CI matrix, security audit, and coverage gates
│   └── dependabot.yml              # Dependabot config for pip & GitHub Actions
├── docs/
│   ├── architecture/
│   │   └── target-architecture.md  # Architectural blueprint & module boundaries
│   ├── security/
│   │   ├── threat-model.md         # Threat model & attack mitigations
│   │   ├── database-permissions.md # DB engine permission setup & dialect limitations
│   │   └── supply-chain.md         # Supply-chain security policy, SBOM & triage SLA
│   ├── deployment/
│   │   └── readiness-checklist.md  # Internal pilot verification checklist
│   └── testing/
│       ├── verification-plan.md    # Test strategy, mutation testing evaluation & gates
│       └── master-engineering-checklist.md # Complete software engineering checklist assessment
├── constraints.txt                 # Pinned dependencies for reproducible pilot builds
├── requirements.txt                # Runtime application dependencies
├── requirements-dev.txt            # Development, CI, and audit tooling
├── requirements-local.txt          # Optional local llama.cpp inference engine
├── sbom.cyclonedx.json             # CycloneDX Software Bill of Materials (SBOM)
├── .secrets.baseline               # detect-secrets audited baseline
├── docker-compose.test.yml         # Disposable PostgreSQL 16 & MySQL 8.4 test containers
└── app.py                          # Streamlit UI consuming the schemasense package
```

---

## Security Documentation

- [Complete Software Project Engineering Master Checklist Assessment](docs/testing/master-engineering-checklist.md)
- [Threat Model & Attack Mitigations](docs/security/threat-model.md)
- [Database Permissions & Engine Dialect Limitations](docs/security/database-permissions.md)
- [Supply-Chain Security & Vulnerability Triage](docs/security/supply-chain.md)
- [Internal Pilot Readiness Checklist](docs/deployment/readiness-checklist.md)
- [Verification & Quality Gate Plan](docs/testing/verification-plan.md)

---

## License

MIT — free to use, modify, and distribute.
