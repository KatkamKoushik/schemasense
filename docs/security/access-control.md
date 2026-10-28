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

When no access key is configured and no reverse proxy headers are present:
- SchemaSense runs in **Evaluation Mode (Local)**.
- Telemetry indicators prominently display `Operator: Local Operator (Evaluation Mode)`.
- No database credentials or schemas can leave the host unless an external database connection is explicitly configured by the local user.

---

## 3. Defense-in-Depth Summary

| Boundary | Layer | Enforcement Mechanism |
|---|---|---|
| **Console Access** | Ingress / App | OIDC Identity-Aware Proxy or `SCHEMASENSE_ACCESS_KEY` Token Gate |
| **Database Network** | Ingress / Driver | SSRF-checked host connection; dedicated non-root database users |
| **Database Permissions** | Engine Catalogs | Least-privilege role inspection (`pg_roles`, `mysql.user`); admin rejection |
| **SQL Guardrails** | Application AST | `sqlglot` AST parsing, single-statement restriction, CTE scope-awareness |
| **Resource Limits** | Engine & Pool | 5,000ms statement timeouts, 1,000 row caps, bounded semaphore concurrency |

