# syntax=docker/dockerfile:1.4
# ==============================================================================
# Stage 1: Build Native Rust Core (schemasense-core PyO3 ABI3 Wheel)
# ==============================================================================
FROM rust:1.80-slim-bullseye AS rust-builder
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir "maturin>=1.5,<2.0"

COPY Cargo.toml Cargo.lock* ./
COPY crates ./crates

RUN maturin build --release --manifest-path crates/schemasense_core/Cargo.toml --out dist

# ==============================================================================
# Stage 2: Production Hardened Multi-Role Runtime Container
# ==============================================================================
FROM python:3.12-slim-bookworm AS runtime

LABEL maintainer="Katkam Koushik <koushikkatkam@gmail.com>" \
      org.opencontainers.image.title="SchemaSense 2.0" \
      org.opencontainers.image.description="AI-native database intelligence and schema governance platform" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app" \
    PATH="/home/schemasense/.local/bin:${PATH}" \
    SCHEMASENSE_MODE="advanced"

# Install minimal runtime libraries (curl for container health probes, libpq for PostgreSQL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged system user and group (UID/GID 10001) for container security hardening
RUN groupadd -g 10001 schemasense && \
    useradd -u 10001 -g schemasense -m -s /bin/bash schemasense

WORKDIR /app

# Copy dependency constraints and wheel artifacts from builder stage
COPY requirements.txt requirements-dev.txt constraints.txt pyproject.toml ./
COPY --from=rust-builder /build/dist/*.whl /tmp/wheels/

# Install dependencies locked against constraints.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -c constraints.txt /tmp/wheels/*.whl && \
    pip install --no-cache-dir -c constraints.txt -e ".[platform]" && \
    rm -rf /tmp/wheels

# Copy application source code and configurations
COPY --chown=schemasense:schemasense . .

# Switch to unprivileged runtime user
USER schemasense

# Expose FastAPI Gateway (8000) and Streamlit Console (8501)
EXPOSE 8000 8501

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || curl -f http://localhost:8501/_stcore/health || exit 1

# Default entrypoint runs the FastAPI Gateway
CMD ["uvicorn", "schemasense.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
