# Stage 1: Build Frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python Backend Runtime
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python backend dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application directories
COPY backend/ backend/
COPY carrier-agent/ carrier-agent/
COPY ingestion/ ingestion/

# Copy built frontend from Stage 1 into frontend/dist
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Set Python path to find carrier-agent packages
ENV PYTHONPATH="/app/carrier-agent:/app"

# Non-root service user for production container security
RUN useradd -u 8888 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

CMD ["sh", "-c", "gunicorn backend.server:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --timeout 120"]
