# GBF Dashboard — production Docker image
# Serves FastAPI backend + SvelteKit static build in one container.

FROM python:3.11-slim AS backend-deps
WORKDIR /app
RUN pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.0 \
    duckdb==1.0.0 \
    polars==1.0.0

# ── Frontend build (Node 20) ──────────────────────────────────────────────────
FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json ./
RUN npm install --frozen-lockfile 2>/dev/null || npm install
COPY frontend/ .
RUN npm run build          # outputs to /frontend/build/

# ── Final image ───────────────────────────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

# Copy Python deps
COPY --from=backend-deps /usr/local/lib/python3.11/site-packages \
     /usr/local/lib/python3.11/site-packages
COPY --from=backend-deps /usr/local/bin/uvicorn /usr/local/bin/uvicorn

# Copy frontend static build
COPY --from=frontend-build /frontend/build /app/static

# Copy backend source
COPY backend/ /app/backend/

# Data directory is mounted at runtime (read-only)
# docker run -v /path/to/data:/app/data:ro ...

ENV DATA_DIR=/app/data \
    DB_PATH=/app/data/gbf.duckdb \
    STATIC_DIR=/app/static

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--log-level", "warning"]
