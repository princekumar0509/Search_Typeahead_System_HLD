# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Avoid .pyc files and force unbuffered stdout for clean container logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# System deps for psycopg2 + a tiny healthcheck client.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# The entrypoint waits for Postgres, optionally seeds, then starts uvicorn.
RUN chmod +x ./entrypoint.sh
CMD ["./entrypoint.sh"]
