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

# ---- Week 6 Step 3: production rehearsal, rollback, backup ----
PROD = $(COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml
SITE_HOST ?= healthprofile.localhost
export SITE_HOST

.PHONY: prod prod-down tag rollback backup restore

prod: backend/.env
	$(PROD) up -d --build
	@for i in $$(seq 1 120); do curl -kfsS -o /dev/null https://$(SITE_HOST)/ready/ 2>/dev/null && break; sleep 2; done
	@curl -kfsS https://$(SITE_HOST)/ready/ && echo && echo "Ready: https://$(SITE_HOST)"

prod-down:
	$(PROD) down

tag:  # keep the current images under a release tag, for rollback: make tag TAG=v1.0.0
	docker tag healthprofile-backend:week6 healthprofile-backend:$(TAG)
	docker tag healthprofile-frontend:week6 healthprofile-frontend:$(TAG)

rollback:  # make rollback TAG=v1.0.0 : run the tagged images (database migrations are not reversed)
	docker tag healthprofile-backend:$(TAG) healthprofile-backend:week6
	docker tag healthprofile-frontend:$(TAG) healthprofile-frontend:week6
	$(PROD) up -d --no-build

backup:
	@mkdir -p backups
	$(COMPOSE) exec -T db pg_dump -U healthprofile -Fc healthprofile > backups/healthprofile-$$(date +%Y%m%d-%H%M%S).dump
	@ls -1t backups | head -1

restore:  # make restore FILE=backups/healthprofile-....dump
	$(COMPOSE) exec -T db pg_restore -U healthprofile -d healthprofile --clean --if-exists < $(FILE)
