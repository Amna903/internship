# Week 6: one-command local stack. Run from week6/.  `make up` | `make up OLLAMA=container`
COMPOSE = docker compose
OLLAMA ?= host
ifeq ($(OLLAMA),container)
  PROFILE = --profile ollama
  export OLLAMA_URL = http://ollama:11434
endif

.PHONY: up down logs seed test ps clean models

up: backend/.env
	@df -k . | awk 'NR==2 && $$4 < 5242880 {print "Less than 5 GB free disk; free some space first."; exit 1}'
	$(COMPOSE) $(PROFILE) up -d --build
	@echo "Waiting for the backend to be ready..."
	@for i in $$(seq 1 120); do curl -fsS -o /dev/null http://127.0.0.1:8000/ready/ 2>/dev/null && curl -fsS -o /dev/null http://127.0.0.1:3000/ 2>/dev/null && break; sleep 2; done
	@curl -fsS http://127.0.0.1:8000/ready/ || (echo "Backend not ready; see 'make logs'"; exit 1)
	@echo
	@echo "Ready: http://localhost:3000  (admin sign-in: http://localhost:3000/admin/login)"
	@echo "Demo passwords are in backend/.env (SEED_ADMIN_PASSWORD, SEED_USER_PASSWORD)."

backend/.env:
	python3 backend/scripts/init_env.py

models:  # only for OLLAMA=container: pull the two models into the container
	$(COMPOSE) --profile ollama exec ollama ollama pull llama3.2:3b
	$(COMPOSE) --profile ollama exec ollama ollama pull nomic-embed-text

seed:
	$(COMPOSE) exec backend python manage.py seed_demo
	$(COMPOSE) exec backend sh -c 'python manage.py load_policies --admin "$${SEED_ADMIN_EMAIL:-admin@example.test}"'

down:
	$(COMPOSE) --profile ollama down

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

test:
	$(COMPOSE) exec -e DJANGO_SETTINGS_MODULE=config.settings_test -e DATABASE_URL= backend sh -c 'pip install --user -q -r requirements-dev.txt && python -m pytest -q'

clean:
	@read -p "Delete the database and model volumes? [y/N] " a && [ "$$a" = y ] && $(COMPOSE) --profile ollama down -v
