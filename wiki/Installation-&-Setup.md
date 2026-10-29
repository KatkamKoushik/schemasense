# Installation & Setup Guide

This guide details setting up SchemaSense for local development, enterprise evaluation, and production deployment.

---

## 1. System Prerequisites

| Requirement | Supported Versions | Notes |
|---|---|---|
| **Python** | 3.10, 3.11, 3.12 | Verified across GitHub Actions multi-platform matrix |
| **Operating System** | Linux (Ubuntu 20.04+), macOS (Apple Silicon / Intel), Windows 10/11 | OS-agnostic path and multiprocessing support |
| **Memory (RAM)** | 2 GB minimum (Cloud AI), 8 GB+ recommended (Local GGUF models) | Local GGUF memory managed via lazy dynamic allocation |
| **Docker Engine** | Optional (24.0+) | Required only for spinning up live PostgreSQL and MySQL test containers |

---

## 2. Step-by-Step Installation

### Step 1: Clone the Repository
```bash
git clone https://github.com/KatkamKoushik/schemasense.git
cd schemasense
```

### Step 2: Create a Virtual Environment
```bash
# On Linux / macOS:
python3 -m venv .venv
source .venv/bin/activate

# On Windows (PowerShell):
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### Step 3: Install Project Dependencies
SchemaSense provides modular requirement sets:

```bash
# 1. Base requirements (Cloud AI providers + database drivers + Streamlit):
pip install -r requirements.txt

# 2. Development & Testing requirements (Pytest, Ruff, Mypy, Playwright, Hypothesis):
pip install -r requirements-dev.txt

# 3. (Optional) Local GGUF model execution (llama.cpp):
pip install -r requirements-local.txt

# 4. (Production) Constraint-locked reproducible build:
pip install -r requirements.txt -c constraints.txt
```

### Step 4: Install Browser Binaries (for Playwright E2E UI Tests)
```bash
playwright install chromium
```

---

## 3. Configuration & Environment Variables

Create a `.env` file in the project root or provide secrets via Streamlit `.streamlit/secrets.toml`:

```bash
# ==========================================
# RUNTIME ENVIRONMENT & GATE SECURITY
# ==========================================
# Options: development | staging | production
SCHEMASENSE_ENV=development

# Shared Enterprise Security Key (protects console in locked mode)
SCHEMASENSE_ACCESS_KEY=your-secure-enterprise-key

# SSRF Sandbox Policy (set to 0 in production to block private network IPs)
SCHEMASENSE_ALLOW_LOCAL_CONNECTIONS=1

# ==========================================
# OAUTH 2.0 FEDERATED SSO (OPTIONAL)
# ==========================================
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret

GITHUB_CLIENT_ID=your-github-client-id
GITHUB_CLIENT_SECRET=your-github-client-secret

# Public base URL where SchemaSense is hosted
SCHEMASENSE_BASE_URL=http://localhost:8501

# ==========================================
# AI INFERENCE PROVIDER API KEYS (OPTIONAL)
# ==========================================
# Enter keys for whichever backends you plan to use:
GEMINI_API_KEY=AIzaSy...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
DEEPSEEK_API_KEY=sk-...
GROQ_API_KEY=gsk_...
```

---

## 4. Launching the Application

### Local Development Mode
```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501`.

### Production Deployment Mode
In production, run Streamlit with headless flags and CORS protections:
```bash
streamlit run app.py \
  --server.port 8501 \
  --server.address 0.0.0.0 \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection true
```

---

## 5. Dockerized Deployment

SchemaSense includes a production-ready `Dockerfile` and a multi-container `docker-compose.test.yml` for isolated database testing:

### Build and Run Standalone Container
```bash
# Build Docker image
docker build -t schemasense:latest .

# Run container
docker run -d \
  -p 8501:8501 \
  -e SCHEMASENSE_ENV=production \
  -e SCHEMASENSE_ACCESS_KEY=super-secret \
  --name schemasense-app \
  schemasense:latest
```

### Spin Up Disposable PostgreSQL & MySQL Test Databases
```bash
docker compose -f docker-compose.test.yml up -d
```
This provisions:
- **PostgreSQL 16** on `localhost:5433` (user: `test_admin`, readonly: `schemasense_readonly`)
- **MySQL 8.4 LTS** on `localhost:3307` (user: `test_admin`, readonly: `schemasense_readonly`)
