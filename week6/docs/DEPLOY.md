# Deployment, rollback and backup guide (D6)

The procedure is reproducible and needs no hosted service: Docker Compose plus Caddy for HTTPS. It was rehearsed on a laptop; the evidence is in [regression.md](regression.md) (Step 3 HTTPS rehearsal, backup and restore, rollback).

## 1. Deploy

```sh
git clone https://github.com/AmanAtiq/healthprofile.git && cd healthprofile && git checkout v1.0.0 && cd week6
make up                    # first run: creates backend/.env with random secrets (mode 600), builds and starts the stack
ollama pull llama3.2:3b && ollama pull nomic-embed-text   # or: make up OLLAMA=container
make prod SITE_HOST=clinic.example.org TLS_MODE=ops@clinic.example.org   # real domain: Let's Encrypt (email for ACME)
```

- **Local rehearsal:** `make prod` with no arguments serves `https://healthprofile.localhost` with Caddy's internal CA (`TLS_MODE=internal`).
- **Production settings (`config.settings_prod`) refuse to start** with DEBUG on, insecure cookies, no SSL redirect, no TLS proxy, HSTS off, localhost hosts, or non-HTTPS origins. A misconfiguration fails loudly instead of running unsafely.
- **Ready check:** `make prod` waits for `/ready/` (database, broker and model) to return 200.
- **Ports:** only Caddy publishes ports (80 and 443); the backend and frontend are internal.

## 2. Release and roll back

```sh
make tag TAG=v1.0.0        # keep the running images under a release tag
# … deploy a new version with make prod …
make rollback TAG=v1.0.0   # re-tag the old images and restart without building
```

- **Migrations are not reversed by rollback.** Back up first (below). If a release adds a migration, restore the backup taken before it, or ship a forward fix.
- **The model artifact is inside the backend image and SHA-pinned**, so a rollback restores the matching model too.

## 3. Back up and restore

```sh
make backup                                     # pg_dump -Fc → backups/healthprofile-YYYYMMDD-HHMMSS.dump
make restore FILE=backups/healthprofile-….dump  # pg_restore --clean --if-exists
```

- **One backup covers everything:** users, profiles, audit, policy documents, passages and their embeddings, metrics and agent actions all live in PostgreSQL. Redis holds only queued jobs; a lost job stays `queued` and is visible in the ops view.
- **`backups/` is git-ignored.** Copy dumps off the machine and encrypt them: they contain account data.
- **Rehearsed:** a 128 KB dump; restore kept the same 7 users before and after (regression.md, Step 3).

## 4. Secrets and rotation

- **Secrets live only in `backend/.env`:** mode 600, never in git (checked by `test_secret_scan.py`) or images (`.dockerignore`).
- **Rotate the Django secret key:** generate a new one (`python -c "import secrets; print(secrets.token_urlsafe(50))"`), set `DJANGO_SECRET_KEY`, then restart. Sessions are signed out, which is expected.
- **Rotate the database password:** change it in PostgreSQL, update `DATABASE_URL`, then restart the backend and worker.
- **MCP tokens:** revoke and reissue with `manage.py create_mcp_token`; tokens are stored hashed.
- **Seed passwords** are for the demo only: change them, or do not run `seed_demo`, in any shared deployment.

## 5. Before each release

- `make test` and green CI (lint, unit/API, security, RAG regression, model pipeline, frontend build, and the Docker job on the PR).
- `make eval` (about 45 minutes, with the local model): the red-team gate must pass.
- **Dependency audit by hand** (not in CI, because it needs network access to advisory databases): `pip-audit -r backend/requirements.txt` and `npm audit --omit=dev` in `frontend/`. Fix or record anything high.

## 6. Costs

| Item | Cost |
|---|---|
| LLM and embeddings | **$0 per call**: local Ollama. The ops view also shows an *illustrative* hosted-API equivalent from token counts (`assistant/costs.py`: $0.0005 per 1K input and $0.0015 per 1K output tokens, not a quote) |
| Measured token use | Step 9 suite: about 166K tokens for 60 agent runs and 18K for 69 end-to-end answers (`eval_suite/results.json`) |
| Hosting | One small VM (2–4 vCPU, 4–6 GB RAM to fit the 3B model) runs everything; or put Ollama on a separate GPU box. No managed services are required. |
| Storage | Docker images a few GB (keep build cache pruned: `docker builder prune`); database a few MB; models 2.1 GB |
