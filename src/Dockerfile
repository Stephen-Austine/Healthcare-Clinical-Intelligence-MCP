FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# PYTHONPATH must include /app/src so flat imports resolve correctly
ENV PYTHONPATH=/app/src

# Health check verifies Python + core deps import cleanly
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from models.clinical_models import TriagePriority; import sys; sys.exit(0)"

# MCP communicates via stdio — run server directly from src/
WORKDIR /app/src
CMD ["python", "server.py"]