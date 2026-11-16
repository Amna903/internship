#!/bin/sh
# Week 6 Step 1. "api": migrate, seed synthetic data, load the frozen policies (non-fatal if Ollama is not
# reachable yet; `make seed` retries), then serve with gunicorn. "worker": the Celery worker.
set -e
case "$1" in
  api)
    python manage.py migrate --noinput
    python manage.py seed_demo
    python manage.py load_policies --admin "${SEED_ADMIN_EMAIL:-admin@example.test}" \
      || echo "WARNING: policies not loaded (is Ollama reachable at ${OLLAMA_URL}?). Run 'make seed' later."
    exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers "${GUNICORN_WORKERS:-3}" \
      --timeout 120 --access-logfile - --error-logfile -
    ;;
  worker)
    exec celery -A config worker -l info --concurrency "${CELERY_CONCURRENCY:-2}"
    ;;
  *)
    exec "$@"
    ;;
esac
