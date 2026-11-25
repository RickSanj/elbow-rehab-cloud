FROM python:3.11-slim

ENV PYTHONUNBUFFERED=True
ENV APP_HOME=/app
ENV PORT=8080

WORKDIR $APP_HOME

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install requirements
COPY ./requirements.txt .
RUN pip install --no-cache-dir "setuptools<70.0.0" && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn==21.2.0

COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser $APP_HOME
USER appuser

EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# Production: Use Gunicorn with Uvicorn workers
CMD ["gunicorn", \
     "--workers=4", \
     "--worker-class=uvicorn.workers.UvicornWorker", \
     "--bind=0.0.0.0:8080", \
     "--timeout=120", \
     "--access-logfile=-", \
     "--error-logfile=-", \
     "src.main:app"]
