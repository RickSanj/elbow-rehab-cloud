FROM python:3.11-slim

ENV PYTHONUNBUFFERED=True
ENV APP_HOME=/app
ENV PORT=8080

WORKDIR $APP_HOME

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Runtime dependencies only (dev/test tools are in requirements-dev.txt).
COPY ./requirements.txt .
RUN pip install --no-cache-dir "setuptools<70.0.0" && \
    pip install --no-cache-dir -r requirements.txt

# Secrets, local data and tests are excluded by .dockerignore.
COPY . .

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser $APP_HOME
USER appuser

EXPOSE 8080

# 2 workers: each loads numpy/scipy/pandas and may run session processing.
# --timeout 1800: the internal processing route (Cloud Tasks) may run up to
# the 30 min dispatch deadline. Cloud Run ignores HEALTHCHECK, so none is set.
CMD ["gunicorn", \
     "--workers=2", \
     "--worker-class=uvicorn.workers.UvicornWorker", \
     "--bind=0.0.0.0:8080", \
     "--timeout=1800", \
     "--graceful-timeout=30", \
     "--access-logfile=-", \
     "--error-logfile=-", \
     "src.main:app"]
