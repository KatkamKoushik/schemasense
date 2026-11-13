# Contributing to SchemaSense

Thank you for your interest in contributing to SchemaSense! We welcome contributions from developers, security researchers, and data engineers of all experience levels.

SchemaSense is an enterprise-grade AI Data Steward and Schema Intelligence Agent built with a **production hybrid Python + Rust architecture**.

---

## Code of Conduct

All contributors and participants are expected to adhere to our [Code of Conduct](CODE_OF_CONDUCT.md). Please report any violations to [koushikkatkam@gmail.com](mailto:koushikkatkam@gmail.com).

---

## How to Contribute

- **Report Bugs**: Check existing issues first. If you discover a new bug, please file an issue using the [Bug Report template](.github/ISSUE_TEMPLATE/bug_report.md).
- **Suggest Features**: Open an issue using the [Feature Request template](.github/ISSUE_TEMPLATE/feature_request.md).
- **Submit Pull Requests**: Ensure all tests, linters, and type checks pass cleanly before submitting.

---

## Local Development Setup

### Prerequisites

- **Python**: 3.10, 3.11, or 3.12
- **Rust Toolchain**: Stable `rustc` and `cargo` (1.78+)
- **Git**

### 1. Clone the Repository

```bash
git clone https://github.com/KatkamKoushik/schemasense.git
cd schemasense
```

### 2. Set Up Python Virtual Environment

```bash
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate

# On Windows:
.venv\Scripts\activate

# Install dependencies with strict constraints
pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt -c constraints.txt
```

### 3. Build the Native Rust Core (schemasense-core)

SchemaSense includes an optional, high-performance native Rust core in `crates/schemasense_core`. To build and install it locally in development mode:

```bash
pip install maturin
maturin develop --manifest-path crates/schemasense_core/Cargo.toml
```

> **Note**: SchemaSense remains fully functional in pure-Python environments. If the native core is absent or disabled via `SCHEMASENSE_DISABLE_NATIVE_CORE=1`, all operations gracefully fall back to pure-Python implementations.

---

## Quality Gates & Verification

Every pull request must pass the automated GitHub Actions quality gates:

### 1. Python Linting & Formatting

```bash
# Check code style with Ruff
ruff check schemasense/ tests/

# Check formatting with Ruff
ruff format --check schemasense/ tests/ app.py

# Format code automatically
ruff format schemasense/ tests/ app.py
```

### 2. Static Type Checking

```bash
mypy schemasense --ignore-missing-imports
```

### 3. Rust Formatting, Clippy, and Native Tests

```bash
# Check Rust formatting
cargo fmt --all -- --check

# Run Clippy with zero warnings
cargo clippy --workspace --all-targets -- -D warnings

# Run Rust unit and property tests
cargo test --workspace
```

### 4. Python Test Suite & Coverage

```bash
# Fast unit tests with isolated SQLite
pytest -v --ignore=tests/test_live_integration.py --cov=schemasense --cov-fail-under=70

# Verify pure-Python fallback path
SCHEMASENSE_DISABLE_NATIVE_CORE=1 pytest -v tests/test_native_foundation.py tests/test_native_acceleration.py tests/test_sql_guard_hypothesis.py
```

### 5. Security & Secret Audit

```bash
# Dependency vulnerability check
python scripts/security_audit.py

# Detect secrets scan
detect-secrets scan --baseline .secrets.baseline --exclude-files "(\.git|__pycache__|\.venv|venv|\.secrets\.baseline)"
```

---

## Development Principles

1. **Security-First Architecture**: SchemaSense operates directly against user database connections. Never bypass the AST-based `SQLGuard` validator, never bypass table allowlists, and never execute non-SELECT statements.
2. **Deterministic Parity**: Any acceleration added to the Rust core (`schemasense_core`) must maintain identical behavioral and structural parity with the pure-Python fallback.
3. **No Unsafe Code**: The Rust core enforces `#![deny(unsafe_code)]`. All memory operations must remain strictly safe and bounds-checked.
4. **Never Commit Secrets**: Never commit real database credentials, API keys, tokens, or private endpoints. Use environment variables or mock test fixtures.

---

## Pull Request Guidelines

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. Commit your changes using [Conventional Commits](https://www.conventionalcommits.org/):
   - `feat(...)`: New feature or capability
   - `fix(...)`: Bug fix
   - `perf(...)`: Performance improvement
   - `docs(...)`: Documentation updates
   - `test(...)`: Adding or updating tests
   - `refactor(...)`: Code change that neither fixes a bug nor adds a feature
3. Ensure all local tests and linter commands pass.
4. Open a Pull Request referencing any related issues. Complete the [Pull Request Template](.github/pull_request_template.md).
