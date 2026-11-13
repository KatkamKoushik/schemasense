# SchemaSense 2.0 — AI-Native Database Intelligence & Security Platform

> **Polyglot Database Intelligence Platform** | **FastAPI Application Gateway** | **12-State LangGraph Agent** | **Celery + Redis Workloads** | **PyO3 Native Core** | **SQLAlchemy** | **Streamlit**

[![SchemaSense CI](https://github.com/KatkamKoushik/schemasense/actions/workflows/ci.yml/badge.svg)](https://github.com/KatkamKoushik/schemasense/actions/workflows/ci.yml)
[![Python Versions](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.39%2B-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-12--State%20Lifecycle-blueviolet)](https://github.com/langchain-ai/langgraph)
[![Security: SQLGuard Double-Lock](https://img.shields.io/badge/Security-SQLGuard%20Double--Lock-10B981?logo=shield)](docs/security/threat-model.md)
[![Tests: Pytest](https://img.shields.io/badge/Tests-Verified%20Passing-brightgreen?logo=pytest)](tests/)
[![Supply Chain: CycloneDX](https://img.shields.io/badge/SBOM-CycloneDX%20v1.5-blue?logo=owasp)](sbom.cyclonedx.json)
[![Secrets: Scanned](https://img.shields.io/badge/Secret%20Scan-detect--secrets-success)](.secrets.baseline)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An enterprise AI-native data steward, schema intelligence platform, and database governance agent that connects to relational and cloud databases (**PostgreSQL**, **MySQL**, **SQLite**, **AWS RDS/Aurora**, **Azure Database for PostgreSQL/MySQL**, **Google Cloud SQL**, **Supabase**, **Neon**) to **orchestrate multi-state autonomous analytical agents, stream sequenced Server-Sent Events (SSE), queue background schema profiling, enforce AST-based SQL guardrails with native Rust acceleration, audit data quality, and execute structured AI inference with any cloud or local model**.

---

## Dual-Mode Architecture Contract

SchemaSense 2.0 enforces a strict dual-mode operational contract separating lightweight developer usage from distributed enterprise deployments:

| Dimension | Simple Mode (Default / Developer / Streamlit Cloud) | Advanced Mode (Enterprise Platform / Production) |
|---|---|---|
| **Target Audience** | Individual developers, data analysts, quick local triage | Enterprise teams, multi-tenant SaaS, high-throughput agents |
| **Dependencies** | Python 3.10+ & Streamlit (`requirements.txt`). Zero external daemons. | Optional extra: `pip install -e .[platform]` (`FastAPI`, `Celery`, `Redis`, `PostgreSQL`) |
| **Application Gateway** | Direct Streamlit interactive console | `FastAPI` (REST, sequenced SSE streaming, OIDC/JWT auth) |
| **Agent Execution** | Synchronous, in-process execution with `InMemorySaver` / `SqliteSaver` | Asynchronous 12-state `LangGraph` with `AsyncPostgresSaver` |
| **Background Workloads**| In-process synchronous execution (strictly restricted to Simple Mode) | `Celery` workers with `Redis` broker, at-least-once leasing, and fail-fast outages |
| **State & Checkpoints** | In-memory session state or local SQLite | Durable `PostgreSQL` platform database with version-controlled `Alembic` migrations |
| **Native Core** | Optional Rust acceleration (`schemasense-core`); 100% pure-Python fallback | Rust acceleration + Python SQLGuard conjunction double-lock |

---

## 12-State Agent Execution Lifecycle

SchemaSense 2.0 implements a deterministic, gated execution state machine powered by **LangGraph**:

```
RECEIVE ──> UNDERSTAND ──> PLAN ──> SELECT_TOOLS ──> CHECK_PERMISSIONS ──> VALIDATE_PRECONDITIONS
                                                                                  │
┌─────────────────────────────── HUMAN_APPROVAL <── (Gated / Low Confidence) <────┴── SCORE_CONFIDENCE
│                                      │                                                    │
│ (Approved)                           │ (Rejected / Expired / Cancelled)                   │ (Auto-Approved)
▼                                      ▼                                                    ▼
EXECUTE ───────────────────────────> REJECTED ──────────────────────────────────────────> EXECUTE
  │                                    │                                                    │
  ▼                                    │                                                    ▼
VERIFY ──> DELIVER ──> AUDIT_AND_LEARN <────────────────────────────────────────────────────┘
```

- **Mandatory Pre-Execution Approval Gate**: Gated, destructive, or high-risk tools strictly require human reviewer authorization (`approve`, `reject`, `cancel`, `expire`) **before** execution starts.
- **Zero Raw Secret Leakage**: State machines and SSE frames only consume opaque server-side registered `connection_id` references—never raw database connection URIs or credentials.
- **Deterministic Conjunction Double-Lock**: Python AST validation combined with native Rust core validation ensures queries fail closed if either validator detects risk.

---

## Highlights

- **Universal Multi-Cloud & Local AI Architecture**: Connect any model, any provider, and any custom gateway. Natively supports **Google Gemini**, **OpenAI** (GPT-4o, o1, o3-mini), **Microsoft Azure OpenAI Service**, **AWS Bedrock**, **Cloudflare Workers AI**, **Anthropic Claude**, **DeepSeek**, **Groq**, **OpenRouter**, **Mistral AI**, **Ollama**, **Custom OpenAI-compatible gateways**, and **llama.cpp** (local in-process GGUF).
- **Production Observability & Gateway Security**: Standard Prometheus `/metrics` exposition, OpenTelemetry-compatible distributed tracing with correlation headers (`X-Trace-ID`, `X-Response-Time-Seconds`), sliding-window rate limiting with `HTTP 429` and `Retry-After`, and strict privacy-preserving telemetry forbidding raw SQL and secrets in metrics (**Mandatory Correction 18**).
- **FastAPI Application Gateway & Sequenced SSE Streaming**: W3C compliant Server-Sent Events with monotonically increasing sequential IDs (`id: <int>`), ring buffer retention, and reconnection replay via standard `Last-Event-ID`.
- **Distributed Asynchronous Workloads**: Celery background tasks with at-least-once leasing (`task_acks_late=True`, `task_reject_on_worker_lost=True`), bounded exponential backoff retries, and strict fail-fast error handling during queue outages.
- **Versioned Platform Database Migrations**: Explicit Alembic migration management (`python -m schemasense.db.migrate upgrade head`, `check`, `downgrade -1`) ensuring zero unvetted migrations during web gateway boot.
- **Automated PII & Sensitive Entity Classification**: Pattern recognition auditing tables for sensitive entities (email addresses, phone numbers, credit card numbers, Social Security Numbers, IP addresses) with risk severity badges.
- **AST-Based SQLGuard with Conjunction Double-Lock**: Enforces single read-only `SELECT` statements, validates tables against allowlists, resolves CTE aliases by AST scope, prevents schema spoofing, blocks destructive DDL/DML, and enforces statement timeouts (5,000ms) and row caps.
- **Multi-Palette Theme Engine**: Hand-crafted, high-contrast accessible visual designs including **Clean Light**, **Pure White (Minimal)**, **Obsidian Dark**, **Midnight Charcoal (OLED)**, **Steel Gray**, **Nordic Slate**, and **Deep Ocean Navy**.
- **Enterprise Access Gate**: Identity gateway supporting federated **Google OAuth 2.0** and **GitHub OAuth 2.0** SSO, trusted reverse-proxy headers (`X-Forwarded-User`, Cloudflare Access OIDC, AWS ALB), and cryptographically safe token gating.
- **Disaster Recovery Runbooks**: Documented Point-in-Time Recovery (PITR), database backups, Alembic schema rollbacks, and zero-downtime secret rotation.

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

### Option A: Advanced Mode (Docker Compose — One-Command Production Platform)

Launch the complete SchemaSense 2.0 platform (PostgreSQL 16 platform DB, Redis 7 broker, versioned migration runner, FastAPI Gateway, Celery worker, and Streamlit console):

```bash
git clone https://github.com/KatkamKoushik/schemasense.git
cd schemasense

# Launch entire platform in background:
docker compose up -d

# Open Streamlit Console: http://localhost:8501
# Open FastAPI OpenAPI Documentation: http://localhost:8000/docs
# Check Gateway Readiness Probe: curl http://localhost:8000/health/ready
# Check Prometheus Platform Metrics: curl http://localhost:8000/metrics
# Open Prometheus Metrics Explorer: http://localhost:9090
# Open Grafana Dashboards: http://localhost:3000 (admin / schemasense)
```

### Option B: Simple Mode (Standalone Python + Streamlit — Zero External Daemons)

Run SchemaSense directly on your local machine with in-memory execution and zero background services required:

```bash
git clone https://github.com/KatkamKoushik/schemasense.git
cd schemasense

# 1. Standard installation:
pip install -r requirements.txt -r requirements-dev.txt

# 2. Launch Streamlit console in Simple Mode:
streamlit run app.py
```

### Option C: Advanced Mode Manual Launch (FastAPI + Celery + Redis + Postgres)

```bash
# 1. Install platform dependencies:
pip install -e ".[platform]"

# 2. Run explicit version-controlled platform migrations:
python -m schemasense.db.migrate upgrade head

# 3. Start distributed Celery worker:
celery -A schemasense.tasks.celery_app worker -l info

# 4. Start FastAPI Application Gateway:
uvicorn schemasense.api.app:app --host 0.0.0.0 --port 8000

# 5. Start Streamlit Console:
streamlit run app.py
```

---

## Testing & Quality Verification

SchemaSense 2.0 enforces a multi-tier test matrix verified continuously across GitHub Actions:

- **Unit & Contract Suite**: SQLite in-memory, AST SQLGuard adversarial syntax, universal AI backend resilience, and UI headless AppTests.
- **Agent Lifecycle & SSE Suite**: 12-state journey, pre-execution approval gating, monotonic integer SSE event streaming, and `Last-Event-ID` reconnection replay.
- **Live Database Integration Suite**: Real PostgreSQL 16 and MySQL 8.4 container integration and Playwright browser smoke tests.

```bash
# 1. Run full fast unit, agent, and API platform test suite:
pytest -v -m "not integration and not playwright"

# 2. Run live container integration tests (requires Docker containers):
docker compose -f docker-compose.test.yml up -d --wait
pytest -v tests/test_live_integration.py

# 3. Code formatting and quality gates:
python -m ruff check schemasense/ tests/ app.py
python -m ruff format --check schemasense/ tests/ app.py
python -m mypy schemasense --ignore-missing-imports
```

---

## Architecture

```
schemasense/
├── schemasense/                    # Core Python Backend & Platform Engine
│   ├── __init__.py
│   ├── config.py                   # Platform configuration, secure connection registry & trusted CORS
│   ├── ai_agent.py                 # Multi-provider AI agent & session-isolated caching
│   ├── agent/                      # SchemaSense 2.0 LangGraph 12-State Agent Lifecycle
│   │   ├── lifecycle.py            # 12-state enum & approval action/status definitions
│   │   ├── state.py                # Zero-secret AgentState container with opaque connection IDs
│   │   ├── tools.py                # Typed tools (inspect_schema, validate_sql, execute_query, scan_pii)
│   │   ├── checkpointer.py         # Pluggable checkpointer (MemorySaver, SqliteSaver, AsyncPostgresSaver)
│   │   ├── graph.py                # Compiled LangGraph with pre-execution human approval gating
│   │   └── runner.py               # Lifecycle initiation and interrupt resume manager
│   ├── api/                        # FastAPI Application Gateway
│   │   ├── app.py                  # Gateway application factory & security headers
│   │   ├── auth.py                 # Cryptographic JWT & reverse-proxy identity derivation
│   │   ├── events.py               # W3C SSE streamer with monotonic IDs & Last-Event-ID replay
│   │   ├── schemas.py              # Strict Pydantic V2 request & response schemas
│   │   └── routes/                 # Endpoint routers (/health/live, /health/ready, /agent/runs)
│   ├── tasks/                      # Distributed Asynchronous Background Tasks
│   │   ├── celery_app.py           # Celery application factory with at-least-once acks
│   │   ├── dispatcher.py           # Dual-mode dispatcher (Simple in-process, Advanced fail-fast)
│   │   └── tasks.py                # Celery worker tasks with bounded exponential retries
│   ├── db/                         # PostgreSQL Platform State & Alembic Migrations
│   │   ├── base.py                 # SQLAlchemy declarative base with tenant isolation mixins
│   │   ├── models.py               # Tenant, User, ApiKey, ConnectionReference, AgentRunRecord, AuditEventRecord
│   │   ├── session.py              # Thread-safe scoped session and connection pooling
│   │   └── migrate.py              # Explicit migration CLI (upgrade, downgrade, check)
│   ├── runtime/                    # Universal Inference Runtime Subsystem
│   │   ├── backends/               # Base contract, Gemini, OpenAI/Azure/Bedrock, Claude, llama.cpp
│   │   ├── parsers.py              # Zero-dependency GGUF metadata parser
│   │   ├── registry.py             # Local model discovery and integrity verification
│   │   ├── hardware.py             # Memory and accelerator capability detection
│   │   └── compatibility.py        # Model compatibility and memory estimator
│   ├── connection.py               # Safe URL creation, engine lifecycle, cloud SSL, least-privilege inspection
│   ├── sql_guard.py                # AST parser (sqlglot), CTE scope resolution, conjunction double-lock
│   ├── schema_inspector.py         # PKs, FKs, constraints, indexes, data dictionaries, DBML/DDL exports & diffing
│   ├── profiler.py                 # Data quality metrics, automated PII entity scanner, outlier detection
│   ├── rules_engine.py             # PDF business-rule ingestion (pypdf) & prompt grounding
│   ├── benchmark.py                # Synthetic workload & latency benchmark harnesses
│   └── auth.py                     # Enterprise OAuth 2.0 (Google & GitHub SSO), IAP headers, token gateway
├── crates/                         # Native Rust Core (PyO3 ABI3 Extension)
│   └── schemasense_core/           # Native AST SQL validator, graph engine & Rayon numerical profiler
├── tests/                          # 450+ Automated Unit, Lifecycle, Adversarial, Integration & E2E tests
│   ├── test_agent_lifecycle.py     # 12-state LangGraph agent execution and approval gate tests
│   ├── test_api_foundation.py      # FastAPI gateway, liveness/readiness, and CORS tests
│   ├── test_async_sse_celery.py    # W3C SSE streaming, reconnection replay, and Celery queue tests
│   ├── test_platform_e2e_resilience.py # Multi-tenant isolation, DR runbooks, and double-lock stress tests
│   ├── test_db_models.py           # Platform database models and Alembic migration tests
│   ├── test_sql_guard.py           # Adversarial SQL, dialect, and AST injection tests
│   ├── test_connection.py          # Connection security, pool, cloud SSL & concurrency tests
│   ├── test_live_integration.py    # Live PostgreSQL 16 & MySQL 8.4 container tests
│   └── test_ui_apptest.py          # Streamlit headless AppTest integration tests
├── docs/
│   ├── deployment/
│   │   ├── disaster-recovery.md    # Production DR runbook, PITR backup/restore & Alembic rollbacks
│   │   └── readiness-checklist.md  # Internal pilot verification checklist
│   ├── security/
│   │   ├── access-control.md       # Zero-Trust Authentication Architecture
│   │   ├── threat-model.md         # Threat model & attack mitigations
│   │   ├── database-permissions.md # DB engine permission setup & dialect limitations
│   │   └── supply-chain.md         # Supply-chain security policy, SBOM & triage SLA
│   └── testing/
│       ├── verification-plan.md    # Test strategy, mutation testing evaluation & gates
│       └── master-engineering-checklist.md # Complete software engineering checklist assessment
├── Dockerfile                      # Multi-stage, rootless, hardened container image
├── docker-compose.yml              # Production platform orchestration (API, Worker, DB, Redis, UI)
├── alembic.ini                     # Platform database migration configuration
├── constraints.txt                 # Pinned dependencies for reproducible builds
├── requirements.txt                # Runtime application dependencies
├── requirements-dev.txt            # Development, CI, and audit tooling
├── sbom.cyclonedx.json             # CycloneDX Software Bill of Materials (SBOM)
├── .secrets.baseline               # detect-secrets audited baseline
├── LICENSE                         # MIT License
└── app.py                          # Streamlit UI consuming the schemasense package
```

---

## Operational & Disaster Recovery Documentation

- [Disaster Recovery Runbook, Backups & Alembic Rollbacks](docs/deployment/disaster-recovery.md)
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
