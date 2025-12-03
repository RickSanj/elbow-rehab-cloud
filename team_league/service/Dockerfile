FROM python:3.11-slim

ENV PYTHONUNBUFFERED=True
ENV APP_HOME=/app
ENV PORT=8080

WORKDIR $APP_HOME

COPY team_league/service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY team_league $APP_HOME/team_league

EXPOSE 8080


CMD uvicorn team_league.service.main:app --host 0.0.0.0 --port $PORT
