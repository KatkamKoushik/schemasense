# SchemaSense Enterprise Access Control & Authentication Architecture

## 1. Overview

SchemaSense AI is designed for enterprise environments where database credentials, schema intelligence, and query execution are protected by layered security boundaries.

In accordance with enterprise security principles, access control to the SchemaSense console operates via two complementary architectures:
1. **External Trusted Access Layer (Identity-Aware Proxy / Zero Trust OIDC)**: Fronts the console with corporate SSO (e.g. Okta, Azure AD, Google Workspace via AWS ALB, Cloudflare Zero Trust, Pomerium, or OAuth2-Proxy).
2. **Built-in Session Gate (Enterprise Security Key / Token)**: Enforces an access token barrier at the application layer when deployed as an internal standalone service.

---

## 2. Architecture Models

### Model A: Identity-Aware Proxy (Recommended for Enterprise)

When deployed in production Kubernetes clusters, cloud VPCs, or internal networks, SchemaSense relies on an ingress proxy to perform mutual TLS and OIDC authentication.

```
[Corporate User]
       │
       ▼ (HTTPS with OIDC / SSO Session)
[Enterprise Identity-Aware Proxy] (Cloudflare Access, AWS ALB, Pomerium)
       │
       ▼ (Passes Authenticated Identity Headers)
[SchemaSense Console (app.py)]
       ├── Validates X-Forwarded-User / CF-Access-Authenticated-User-Email
       └── Displays Authenticated Operator Badge (e.g. user@enterprise.com)
```

#### Supported Trusted Proxy Headers
SchemaSense automatically inspects incoming request headers in `st.context.headers`:
- `CF-Access-Authenticated-User-Email`: Injected by Cloudflare Zero Trust Access.
- `X-Forwarded-User`: Standard reverse proxy identity header (AWS ALB, NGINX).
- `X-Auth-Request-Email`: Injected by OAuth2-Proxy / Ingress-NGINX.
- `X-Remote-User`: Injected by Pomerium / Apache mod_auth_openidc.

When detected, the console displays the authenticated corporate user in the telemetry header and audit logs.

---

### Model B: Built-In Enterprise Token Gate

For standalone deployments, staging environments, or internal team instances without a dedicated reverse proxy:

#### 1. Configuration via Environment Variable
```bash
export SCHEMASENSE_ACCESS_KEY="your-secure-enterprise-token-here"
streamlit run app.py
```

#### 2. Configuration via `.streamlit/secrets.toml`
```toml
[auth]
access_token = "your-secure-enterprise-token-here"
```

#### Behavior
- When `SCHEMASENSE_ACCESS_KEY` or `[auth].access_token` is set, the application renders a security lock screen blocking all database connections, schema tools, and chat interfaces.
- The operator must supply the valid access token to unlock the console for their session.
- Operators can lock the session at any time using **Lock Console Session** in the sidebar.

---

### Model C: Local Evaluation / Development Sandbox

For local development and evaluation without federated SSO or access tokens:
- **Explicit Opt-In Required**: Local evaluation requires `SCHEMASENSE_ENABLE_LOCAL_EVALUATION=true` (or `1`/`yes`). It defaults to disabled (fail-closed).
- **Production Guard**: If `SCHEMASENSE_ENV` or `ENVIRONMENT` indicates production, local evaluation is strictly blocked and cannot be enabled by opt-in.
- **Access Key Guard**: If `SCHEMASENSE_ACCESS_KEY` is configured, the evaluation bypass is disabled; key authentication must be provided.
- **Identity & Indicators**: When permitted and active, telemetry and the Operator Identity card prominently display `Local Operator` with gateway `Evaluation Mode (Local)`.
- **Locking & Revocation**: Clicking **Lock Console / Open Login Gate** immediately revokes the session and clears all cached operator state.

---

### Model D: Federated Single Sign-On (Google & GitHub OAuth 2.0)

SchemaSense provides first-class support for OAuth 2.0 federation, allowing operators to authenticate with corporate Google Workspace accounts or GitHub developer identities.

#### 1. Google OAuth 2.0 Configuration
In Google Cloud Console (**APIs & Services > Credentials > OAuth 2.0 Client IDs > Web application**):
- **Authorized JavaScript origins**:
  - `http://localhost:8501`
  - `https://neural-nexus-schemasense-n9aixu78zu8ebbbahcvvhc.streamlit.app`
- **Authorized redirect URIs**:
  - `http://localhost:8501`
  - `https://neural-nexus-schemasense-n9aixu78zu8ebbbahcvvhc.streamlit.app`
  - `http://localhost:8501/oauth2callback` (for native Streamlit OIDC)
  - `https://neural-nexus-schemasense-n9aixu78zu8ebbbahcvvhc.streamlit.app/oauth2callback` (for native Streamlit OIDC)

#### 2. GitHub OAuth Application Configuration
In GitHub Settings (**Developer Settings > OAuth Apps > Register a new application**):
- **Application name**: SchemaSense Enterprise Console
- **Homepage URL**: `https://neural-nexus-schemasense-n9aixu78zu8ebbbahcvvhc.streamlit.app`
- **Authorization callback URL**:
  - For Streamlit Cloud deployment: `https://neural-nexus-schemasense-n9aixu78zu8ebbbahcvvhc.streamlit.app`
  - For local development: `http://localhost:8501`

#### 3. Configuration in `.streamlit/secrets.toml`
```toml
# Streamlit Community Cloud (App Settings -> Secrets) or local .streamlit/secrets.toml
[auth.google]
client_id = "YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com"
client_secret = "YOUR_GOOGLE_CLIENT_SECRET"
redirect_uri = "http://localhost:8501"  # Or https://neural-nexus-schemasense-n9aixu78zu8ebbbahcvvhc.streamlit.app

[auth.github]
client_id = "YOUR_GITHUB_CLIENT_ID"
client_secret = "YOUR_GITHUB_CLIENT_SECRET"
redirect_uri = "http://localhost:8501"  # Or https://neural-nexus-schemasense-n9aixu78zu8ebbbahcvvhc.streamlit.app
```

#### 4. Mandatory Enforcement
To require all incoming operators to authenticate via OAuth or security key before accessing the console, set `require_auth = true` in `.streamlit/secrets.toml` or export `SCHEMASENSE_REQUIRE_AUTH=true`:
```toml
[auth]
require_auth = true
```

---

## 3. Defense-in-Depth Summary

| Boundary | Layer | Enforcement Mechanism |
|---|---|---|
| **Console Access** | Ingress / App | Google & GitHub OAuth 2.0, Reverse Proxy IAP, or `SCHEMASENSE_ACCESS_KEY` |
| **Database Network** | Ingress / Driver | SSRF-checked host connection; dedicated non-root database users |
| **Database Permissions** | Engine Catalogs | Least-privilege role inspection (`pg_roles`, `mysql.user`); admin rejection |
| **SQL Guardrails** | Application AST | `sqlglot` AST parsing, single-statement restriction, CTE scope-awareness |
| **Resource Limits** | Engine & Pool | 5,000ms statement timeouts, 1,000 row caps, bounded semaphore concurrency |

