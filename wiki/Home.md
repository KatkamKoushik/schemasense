# Welcome to the SchemaSense Wiki

> **Universal Database Intelligence, Enterprise Schema Governance & Multi-Model SQL Agent**

Welcome to the official technical documentation and engineering wiki for **SchemaSense**. This wiki covers architectural blueprints, enterprise security controls, multi-provider LLM integrations, live database configurations, and operational deployment guides.

---

## Quick Navigation

| Section | Description |
|---|---|
| [[Architecture Overview]] | System blueprint, AST pipeline, state management, and component boundaries |
| [[Installation & Setup]] | Environment setup, virtualenvs, local GGUF weights, and initial launch |
| [[Security Model & Access Control]] | AST SQLGuard, SSRF defense, OAuth 2.0 gateway, and least-privilege enforcement |
| [[Supported Databases & SSL]] | PostgreSQL, MySQL, SQLite, and cloud managed SSL/TLS configuration |
| [[Multi-Model Inference Engines]] | Cloud AI (Gemini, OpenAI, Claude, DeepSeek) & local private models (llama.cpp, Ollama) |
| [[Testing & CI-CD Pipeline]] | 420-test multi-tier test suite, Playwright browser tests, Hypothesis fuzzing, and CI |
| [[Deployment & Operations Guide]] | Production readiness checklist, Docker containerization, reverse proxying, and monitoring |

---

## System Architecture at a Glance

```mermaid
flowchart TD
    User([Enterprise Data Operator]) -->|Browser / HTTPS| ReverseProxy[Reverse Proxy / Cloudflare Access]
    ReverseProxy -->|Forwarded Headers / WebSockets| StreamlitUI[Streamlit Enterprise UI & Theme Engine]
    
    subgraph Identity & Access Gate
        StreamlitUI --> Gate{Authenticated?}
        Gate -->|No| LoginGate[OAuth 2.0 / Access Key Gate]
        LoginGate -->|Google / GitHub SSO| AuthEngine[schemasense.auth]
        Gate -->|Yes| MainApp[Console Workspace]
    end

    subgraph Core Execution Engine
        MainApp --> Inspector[Live Schema Inspector]
        MainApp --> Profiler[Column & PII Profiler]
        MainApp --> Agent[SQL Data Steward Agent]
        MainApp --> Diff[Schema Evolution Diff]
    end

    subgraph Security Sandbox
        Agent --> SQLGuard[AST SQLGuard Parser & Validator]
        SQLGuard --> DialectRules{Read-Only SELECT?}
        DialectRules -->|Blocked| Violation[Security Violation Log]
        DialectRules -->|Allowed| ConnPool[Bounded QueuePool]
    end

    subgraph Database Layer
        ConnPool -->|SSL/TLS Encrypted| LiveDB[(PostgreSQL / MySQL / SQLite)]
    end

    subgraph Inference Layer
        Agent --> Router[Runtime Backend Router]
        Router --> CloudLLM[Cloud Providers: Gemini / OpenAI / Claude / DeepSeek / Groq]
        Router --> LocalLLM[Private Local: llama.cpp GGUF / Ollama]
    end
```

---

## Core Capabilities

1. **Deterministic AST SQL Guardrails**: Powered by `sqlglot`, blocking destructive DDL/DML, rejecting comment evasion attacks, preventing schema spoofing, resolving CTE scopes, and enforcing statement timeouts (5,000ms) and row caps (1,000 rows).
2. **Universal Multi-Cloud & Local AI Routing**: Seamless hot-switching between 12+ cloud inference providers and private, offline, in-process quantized GGUF models via `llama.cpp` with zero cloud egress.
3. **SSRF & Network Defense**: Defense-in-depth socket validation preventing server-side request forgery to AWS/GCP/Azure instance metadata services (`169.254.169.254`), loopbacks, and link-local ranges.
4. **Least-Privilege Enforcement**: Active database catalog inspection auditing connected account permissions and blocking superuser or admin credentials from production consoles.
5. **PII & Data Quality Profiling**: Automated detection and risk badging of sensitive entities (credit cards, SSNs, emails, phone numbers, IP addresses) alongside IQR outlier detection and completeness scoring.

---

## Contributing & Development

For local development workflows, branch naming conventions, and pre-commit verification steps, refer to [[Testing & CI-CD Pipeline]].
