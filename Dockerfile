FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Remove __pycache__ if present
RUN find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

EXPOSE 8009

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8009/health'); assert r.status_code == 200"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8009"]
