# Azure Discovery Scanner — per-CSP Docker image
# Build context: REPO ROOT (docker build -f engines/discoveries/providers/azure/Dockerfile .)
#
# 3-stage build:
#   base      — system deps + core Python packages (no CSP SDKs)
#   azure-sdk — azure-mgmt-* packages on top of base
#   final     — app code + non-root user

# ── Stage 1: base ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

COPY engines/discoveries/requirements-base.txt ./requirements-base.txt
RUN pip install --no-cache-dir -r requirements-base.txt

# ── Stage 2: azure-sdk ────────────────────────────────────────────────────────
FROM base AS azure-sdk

COPY engines/discoveries/providers/azure/requirements.txt ./requirements-azure.txt
RUN pip install --no-cache-dir -r requirements-azure.txt

# ── Stage 3: final ────────────────────────────────────────────────────────────
FROM azure-sdk AS final

# App code: discovery engine + all providers + shared utilities
COPY engines/discoveries/providers/ ./providers/
COPY engines/discoveries/common/    ./common/
COPY engines/discoveries/utils/     ./utils/
COPY engines/discoveries/run_scan.py ./run_scan.py

# Shared utilities (import path: engine_common.*)
COPY shared/common/ ./engine_common/

# Shared database (import path: consolidated_services.*)
COPY shared/database/ ./consolidated_services/

# Onboarding storage — credential resolution
COPY engines/onboarding/storage/    ./engine_onboarding/storage/
COPY engines/onboarding/__init__.py ./engine_onboarding/
COPY engines/onboarding/config.py   ./engine_onboarding/

# Azure service catalog
COPY catalog/azure/ ./catalog/azure/

# Non-root runtime user
RUN adduser --disabled-password --gecos '' appuser \
    && chown -R appuser /app
USER appuser

ENV PYTHONPATH=/app
ENV PORT=8001

EXPOSE ${PORT}

CMD ["sh", "-c", "uvicorn common.api_server:app --host 0.0.0.0 --port ${PORT:-8001} --timeout-keep-alive 75"]
