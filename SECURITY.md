# Security Policy

## Supported Versions

SchemaSense actively maintains and provides security updates for the following versions:

| Version | Supported          | Security Maintenance Level |
| ------- | ------------------ | --------------------------- |
| 1.0.x   | :white_check_mark: | Full Active Security Support |
| < 1.0   | :x:                | Deprecated                  |

---

## Reporting a Vulnerability

The SchemaSense maintainers take security and data confidentiality seriously. If you discover or suspect a security vulnerability in SchemaSense, please report it responsibly.

### Disclosure Channels

- **Primary Contact**: Email [koushikkatkam@gmail.com](mailto:koushikkatkam@gmail.com) with the subject `[SECURITY] SchemaSense Vulnerability Report`.
- **GitHub Security Advisory**: You may also submit a confidential report directly via GitHub Security Advisories if repository advisories are enabled.

> **DO NOT** disclose security vulnerabilities publicly on GitHub Issues, pull requests, discussions, or social media before a patch is published and coordinated.

---

## What to Include in Your Report

To help us triage and remediate the issue rapidly, please provide:
1. **Description**: Clear description of the vulnerability and its potential impact.
2. **Component Affected**: Specific module (e.g., `SQLGuard`, OAuth gate, database pool manager, native Rust core).
3. **Reproduction Steps**: Minimal proof-of-concept (PoC) script, query, or configuration to reproduce the issue safely.
4. **Environment**: Python version, OS, database dialect (PostgreSQL, MySQL, SQLite), and whether native Rust acceleration was active.
5. **Impact Assessment**: Privileges obtained, data leaked, or guardrails bypassed.

---

## Response & Disclosure Process

- **Acknowledgment**: We acknowledge receipt of vulnerability reports within **24 hours**.
- **Initial Triage**: Maintainers will confirm reproducibility and determine severity within **72 hours**.
- **Remediation**: A security patch will be developed, validated against automated regression suites, and tagged.
- **Coordination**: We coordinate a mutual disclosure date with the reporter.
- **Public Credit**: We are glad to credit security researchers in our release notes and security advisories (unless you prefer anonymity).

---

## Core Security Architecture & Safeguards

SchemaSense is designed around defense-in-depth security principles:

1. **Fail-Closed SQLGuard AST Validator**:
   - Analyzes SQL at the Abstract Syntax Tree (AST) level using both `sqlglot` (Python) and `sqlparser-rs` (Rust).
   - Strictly enforces read-only `SELECT` queries (disallowing `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`, `GRANT`, `REVOKE`).
   - Resolves Common Table Expression (CTE) and subquery alias scopes to prevent physical table spoofing.
   - Restricts queries to an explicit table allowlist.
   - Enforces database-level read-only session privileges (`PRAGMA query_only = ON` for SQLite, `SET TRANSACTION READ ONLY` for PostgreSQL/MySQL).
   - Enforces strict query timeouts (5,000ms max) and hard row limits (1,000 rows max).

2. **Supply-Chain Hardening**:
   - Continuous dependency vulnerability auditing via `pip-audit`.
   - Secret scanning via `detect-secrets`.
   - Cryptographically reproducible dependency locking via `constraints.txt`.
   - CycloneDX Software Bill of Materials (SBOM) published on every build.

3. **Memory Safety**:
   - The native Rust acceleration crate (`crates/schemasense_core`) enforces `#![deny(unsafe_code)]`.
   - Bounded allocations and explicit size limits (16MB container cap, 1k KV cap, 64KB string cap) on binary model metadata parsers to prevent memory bombs and denial of service.
