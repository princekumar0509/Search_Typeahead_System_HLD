#!/usr/bin/env bash
# Backend container entrypoint: wait for Postgres, optionally seed, run API.
set -euo pipefail

# --- wait for the database ---------------------------------------------------
echo "Waiting for PostgreSQL at ${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}..."
until python -c "
import os, sys, psycopg2
try:
    psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'postgres'),
        port=os.getenv('POSTGRES_PORT', '5432'),
        user=os.getenv('POSTGRES_USER', 'postgres'),
        password=os.getenv('POSTGRES_PASSWORD', 'postgres'),
        dbname=os.getenv('POSTGRES_DB', 'typeahead'),
    ).close()
except Exception as exc:
    print(exc); sys.exit(1)
" 2>/dev/null; do
  echo "  ...still waiting"
  sleep 2
done
echo "PostgreSQL is up."

# --- optional one-time seeding ----------------------------------------------
# Set SEED_ON_START=true to generate + load the dataset on first boot.
if [ "${SEED_ON_START:-false}" = "true" ]; then
  echo "Seeding database (${SEED_ROWS:-120000} rows)..."
  python -m scripts.seed_database --rows "${SEED_ROWS:-120000}"
fi

# --- run the API -------------------------------------------------------------
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${UVICORN_WORKERS:-1}"
