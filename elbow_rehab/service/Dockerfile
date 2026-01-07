FROM python:3.11-slim

ENV PYTHONUNBUFFERED=True
ENV APP_HOME=/app
ENV PORT=8080

WORKDIR $APP_HOME

COPY elbow_rehab/service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY elbow_rehab $APP_HOME/elbow_rehab

EXPOSE 8080


CMD uvicorn elbow_rehab.service.main:app --host 0.0.0.0 --port $PORT
