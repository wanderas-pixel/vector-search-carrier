FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    APP_HOME=/app

WORKDIR $APP_HOME

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application source code
COPY carrier-agent/ carrier-agent/
COPY backend/ backend/

# Install carrier-agent in editable or path mode
ENV PYTHONPATH="/app/carrier-agent:/app"

# Non-root service user for production container security
RUN useradd -u 8888 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Production Gunicorn with Uvicorn workers for high concurrency SSE streaming
CMD ["gunicorn", "backend.server:app", "--workers", "2", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "120"]
