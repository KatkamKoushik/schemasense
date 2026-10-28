# SchemaSense AI — Intelligent Data Dictionary & Enterprise Data Agent

> **Built for Enterprise Relational Databases** | Universal Multi-Cloud & Local AI Inference Engines (**Google Gemini**, **OpenAI**, **Microsoft Azure OpenAI**, **AWS Bedrock**, **Cloudflare Workers AI**, **Anthropic Claude**, **DeepSeek**, **Groq**, **OpenRouter**, **Mistral**, **Ollama**, **Custom Gateways**, **llama.cpp**) | **SQLAlchemy** | **Streamlit**

[![SchemaSense CI](https://github.com/KatkamKoushik/schemasense/actions/workflows/ci.yml/badge.svg)](https://github.com/KatkamKoushik/schemasense/actions/workflows/ci.yml)
[![Python Versions](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.39%2B-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![Security: SQLGuard AST](https://img.shields.io/badge/Security-SQLGuard%20AST-10B981?logo=shield)](docs/security/threat-model.md)
[![Tests: Pytest](https://img.shields.io/badge/Tests-400%20Total%20%7C%20100%25%20Passing-brightgreen?logo=pytest)](tests/)
[![Coverage](https://img.shields.io/badge/Coverage-91%25-brightgreen)](tests/)
[![Supply Chain: CycloneDX](https://img.shields.io/badge/SBOM-CycloneDX%20v1.5-blue?logo=owasp)](sbom.cyclonedx.json)
[![Secrets: Scanned](https://img.shields.io/badge/Secret%20Scan-detect--secrets-success)](.secrets.baseline)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An enterprise AI Data Steward and Schema Intelligence Agent that connects to relational and cloud databases (**PostgreSQL**, **MySQL**, **SQLite**, **AWS RDS/Aurora**, **Azure Database for PostgreSQL/MySQL**, **Google Cloud SQL**, **Supabase**, **Neon**) to **generate interactive data dictionaries, classify sensitive PII entities, export DBML/DDL schemas, enforce AST-based SQL guardrails, audit data quality, track schema evolution & drift, bound database concurrency, ground queries in business rules, and execute structured AI inference with any cloud or local model**.

---

## Highlights

- **Universal Multi-Cloud & Local AI Architecture**: Connect any model, any provider, and any custom gateway. Natively supports **Google Gemini**, **OpenAI** (GPT-4o, o1, o3-mini), **Microsoft Azure OpenAI Service** (with automated `api-key` header routing and deployment URLs), **AWS Bedrock** (via LiteLLM / gateway), **Cloudflare Workers AI**, **Anthropic Claude** (Claude 3.5 Sonnet, Haiku), **DeepSeek** (V3, R1), **Groq** (Llama 3.3 70B, Mixtral), **OpenRouter** (200+ models), **Mistral AI**, **Ollama** (local HTTP/self-hosted), **Custom OpenAI-compatible gateways**, and **llama.cpp** (local in-process GGUF inference with lazy weight allocation and zero cloud fallback).
- **Interactive Multi-Palette Theme Engine**: Hand-crafted, high-contrast accessible visual designs including **Clean Light**, **Pure White (Minimal)**, **Obsidian Dark**, **Midnight Charcoal (OLED)**, **Steel Gray**, **Nordic Slate**, and **Deep Ocean Navy**. Dynamically injects theme variables and enforces WCAG-compliant contrast across all text, cards, inputs, and metric chips without page reloads.
- **Automated PII & Sensitive Entity Classification**: Built-in pattern recognition engine in the column profiler that audits tables for sensitive information (email addresses, phone numbers, credit card numbers, Social Security Numbers, IP addresses) and displays clear severity risk badges in the Data Dictionary and Column Profiler.
- **Enterprise Zero-Trust Access Gate**: Built-in identity gateway supporting federated **Google OAuth 2.0** and **GitHub OAuth 2.0** SSO, trusted reverse-proxy headers (`X-Forwarded-User`, Cloudflare Access OIDC, AWS ALB, `X-Remote-User`), and cryptographically safe token gating (`SCHEMASENSE_ACCESS_KEY`), keeping unauthorized operators locked out of internal database consoles.
- **Schema Architecture & DBML/DDL Dual-Format Export**: Deep introspection capturing primary keys, unique constraints, foreign keys (including composite relationships), and indexes. Includes one-click exports for **DBML** (`.dbml` for dbdiagram.io / dbdocs.io), standard **SQL DDL** (`.sql`), **JSON**, and **Markdown**.
- **Cloud Database SSL/TLS Security**: Native encryption modes (`prefer`, `require`, `verify-ca`, `verify-full`) allowing instant, secure connections to managed cloud database instances on AWS RDS, AWS Aurora, Azure Database Flexible Server, Google Cloud SQL, Supabase, and Neon.
- **AST-Based SQLGuard**: Dialect-aware parser powered by `sqlglot`. Strictly enforces single read-only `SELECT` statements, validates tables against an active allowlist, resolves CTE aliases by AST scope, prevents schema spoofing, blocks destructive DDL/DML, and enforces database-level statement timeouts (5,000ms) and row caps (1,000 rows).
- **Least-Privilege Enforcement**: Active runtime catalog inspection identifying superuser or administrative credentials without relying on naive username heuristics. Includes interactive UI policy toggles to reject privileged connections.
- **Deep Schema Evolution Diffing**: Capture live schema snapshots and perform deterministic schema drift diffing (detecting added/removed tables, column additions, and type modifications).
- **Data Quality & Statistical Profiling**: Calculates null percentages, distinct counts, candidate primary keys, duplicate row rates, numeric outlier detection (IQR), and computes a composite Data Quality Score (0–100%).
- **Bounded Concurrency & Pool Management**: Bounded SQLAlchemy `QueuePool` with session timeouts, client-side concurrency semaphores, and safe pool disposal on disconnect.
- **Supply-Chain Security Gates**: Continuous vulnerability auditing (`pip-audit`), secret scanning (`detect-secrets`), reproducible builds (`constraints.txt`), and CycloneDX SBOM release artifacts.

---

## Supported Environments

| Component | Supported Versions | Notes |
|---|---|---|
| **Python** | 3.10, 3.11, 3.12 | Verified across automated GitHub Actions matrix. |
| **PostgreSQL** | 14, 15, 16 | Tested against `postgres:16-alpine`. Uses `psycopg2-binary`. Supports AWS RDS, Aurora, Azure PostgreSQL, Cloud SQL, Supabase, Neon. |
| **MySQL** | 8.0, 8.4 LTS | Tested against `mysql:8.4`. Uses `pymysql` with `utf8mb4`. Supports AWS RDS MySQL, Azure Database for MySQL, Cloud SQL. |
| **SQLite** | 3.x | In-memory (`:memory:`) and local file testing with zero driver install. |
| **Cloud AI Providers** | Google Gemini, OpenAI, Azure OpenAI, AWS Bedrock, Cloudflare Workers AI, Anthropic Claude, DeepSeek, Groq, OpenRouter, Mistral | Direct API integration with streaming, rate-limit retry, and structured Pydantic decoding. |
| **Local / Custom AI** | Ollama, OpenAI-compatible Gateways, llama.cpp (GGUF) | Flexible local and on-premise execution with zero cloud egress. |

---

## Quick Start

### 1. Clone & Install Dependencies

```bash
git clone https://github.com/KatkamKoushik/schemasense.git
cd schemasense

# Standard installation (cloud AI providers + database drivers):
pip install -r requirements.txt -r requirements-dev.txt

# Optional: Add local GGUF inference engine:
pip install -r requirements-local.txt

# For reproducible, constraint-locked deployment:
pip install -r requirements.txt -c constraints.txt
```

### 2. Run Test Suite & Coverage

Verify the security boundaries, backend contracts, and analytical logic across the test suite (**400 tests total with 100% pass rate**):

- **Fast Unit, AST Guardrail & Contract Suite (358 tests)**: In-memory SQLite, mock schemas, AST SQLGuard adversarial syntax, universal AI backend resilience, OAuth 2.0 flows, and UI headless AppTests. Executes in <26 seconds without external dependencies.
- **Live Multi-Database Suite (42 tests)**: Real PostgreSQL 16, MySQL 8.4, and SQLite container tests. Automatically executes when test containers are active, or skips safely when offline.

```bash
# 1. Run fast offline test suite (358 tests):
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

#### Option B: Microsoft Azure OpenAI Service
In the sidebar **Inference Backend** section:
1. Select **Microsoft Azure OpenAI**.
2. Enter your **Azure Endpoint URL** (e.g. `https://<resource>.openai.azure.com/openai/deployments/<model>`).
3. Enter your **Deployment Name** (e.g. `gpt-4o`) and **Azure API Key**.
4. Authentication header `api-key` is forwarded automatically.

#### Option C: AWS Bedrock / Cloudflare Workers AI / OpenAI / Anthropic / DeepSeek / Groq / OpenRouter
1. Select your provider from the dropdown (**AWS Bedrock**, **Cloudflare Workers AI**, **OpenAI**, **Anthropic Claude**, **DeepSeek**, **Groq**, **OpenRouter**, or **Mistral AI**).
2. Enter your API key / token (or gateway URL).
3. Click **⚡ Test Provider Ping** to verify connectivity immediately.

#### Option D: llama.cpp (Local GGUF)
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
schemasense/
├── schemasense/                    # Core Python Backend Package
│   ├── __init__.py
│   ├── ai_agent.py                 # Multi-provider AI agent & session-isolated caching
│   ├── runtime/                    # Universal Inference Runtime Subsystem
│   │   ├── backends/               # Base contract, Gemini, OpenAI/Azure/Bedrock, Claude, llama.cpp
│   │   │   ├── base.py             # InferenceBackend contract & streaming protocols
│   │   │   ├── gemini.py           # Google Gemini SDK adapter with key rotation
│   │   │   ├── openai_compat.py    # Universal adapter (OpenAI, Azure, Bedrock, Cloudflare, DeepSeek, Groq, Ollama)
│   │   │   ├── anthropic_backend.py# Anthropic Claude Messages API adapter
│   │   │   └── llama_cpp.py        # Local in-process GGUF adapter
│   │   ├── parsers.py              # Zero-dependency GGUF metadata parser
│   │   ├── registry.py             # Local model discovery and integrity verification
│   │   ├── hardware.py             # Memory and accelerator capability detection
│   │   └── compatibility.py        # Model compatibility and memory estimator
│   ├── connection.py               # Safe URL creation, engine lifecycle, cloud SSL, least-privilege inspection, pool disposal
│   ├── sql_guard.py                # AST parser (sqlglot), CTE scope resolution, table allowlists, dialect timeouts & row caps
│   ├── schema_inspector.py         # PKs, FKs, constraints, indexes, data dictionaries, DBML/DDL exports & schema drift diffing
│   ├── profiler.py                 # Data quality metrics, automated PII entity scanner, outlier detection, scoring formula
│   ├── rules_engine.py             # PDF business-rule ingestion (pypdf) & prompt grounding
│   ├── benchmark.py                # Synthetic workload & latency benchmark harnesses
│   └── auth.py                     # Enterprise OAuth 2.0 (Google & GitHub SSO), IAP headers, token gateway
├── tests/                          # 400 Unit, Adversarial, Integration, and AppTest tests
│   ├── conftest.py                 # SQLite test fixtures & mock schemas
│   ├── test_auth.py                # 10 Google & GitHub OAuth 2.0 and identity gateway tests
│   ├── test_backends_base.py       # Neutral backend contract tests
│   ├── test_backends_gemini.py     # Gemini backend & key rotation tests
│   ├── test_backends_openai.py     # Universal OpenAI / Azure / Bedrock / Cloudflare backend tests
│   ├── test_backends_anthropic.py  # Anthropic Claude backend tests
│   ├── test_backends_llama_cpp.py  # llama.cpp local backend & lazy-loading tests
│   ├── test_backend_selection.py   # Explicit backend selection & multi-provider factory tests
│   ├── test_ai_agent.py            # AI agent structured output & fallback tests
│   ├── test_sql_guard.py           # 54 adversarial SQL, dialect, and AST tests
│   ├── test_connection.py          # 14 connection security, pool, cloud SSL, SQLite & concurrency tests
│   ├── test_inspector.py           # 8 schema inspection, DBML/DDL exports, diffing, and composite FK tests
│   ├── test_profiler.py            # 4 quality metrics, PII detection, and outlier tests
│   ├── test_rules_engine.py        # PDF business rule parsing tests
│   ├── test_runtime_parsers.py     # GGUF parser tests
│   ├── test_runtime_registry.py    # Model discovery & SHA256 integrity tests
│   ├── test_runtime_hardware.py    # Hardware detection tests
│   ├── test_runtime_compatibility.py # Runtime compatibility tests
│   ├── test_dependency_hygiene.py  # Dependency hygiene & import boundary tests
│   ├── test_ui_apptest.py          # Streamlit headless AppTest integration tests
│   ├── test_ui_enterprise.py       # Enterprise UI themes, multi-backend selection, cloud SSL & SQLite tests
│   └── test_live_integration.py    # Live PostgreSQL 16 & MySQL 8.4 container tests
├── .github/
│   ├── workflows/
│   │   └── ci.yml                  # Automated CI matrix, security audit, and coverage gates
│   └── dependabot.yml              # Dependabot config for pip & GitHub Actions
├── docs/
│   ├── architecture/
│   │   └── target-architecture.md  # Architectural blueprint & module boundaries
│   ├── security/
│   │   ├── access-control.md       # Enterprise Access Control & Zero-Trust Authentication Architecture
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
├── LICENSE                         # MIT License
└── app.py                          # Streamlit UI consuming the schemasense package
```

---

## Security Documentation

- [Enterprise Access Control & Authentication Architecture](docs/security/access-control.md)
- [Complete Software Project Engineering Master Checklist Assessment](docs/testing/master-engineering-checklist.md)
- [Threat Model & Attack Mitigations](docs/security/threat-model.md)
- [Database Permissions & Engine Dialect Limitations](docs/security/database-permissions.md)
- [Supply-Chain Security & Vulnerability Triage](docs/security/supply-chain.md)
- [Internal Pilot Readiness Checklist](docs/deployment/readiness-checklist.md)
- [Verification & Quality Gate Plan](docs/testing/verification-plan.md)

---

## License

[MIT License](LICENSE) — free to use, modify, and distribute.
