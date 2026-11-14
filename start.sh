#!/bin/sh
# Production entrypoint (Railway): apply migrations, ensure roles/settings, optionally load demo data, serve.
set -e
python -m flask --app run.py db upgrade
python -m flask --app run.py seed-roles
if [ "${SEED_DEMO_DATA:-false}" = "true" ]; then
  python -m flask --app run.py seed-demo
fi
exec gunicorn run:app \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --threads 4 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
