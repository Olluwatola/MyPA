# MyPA

MyPA is a multitenant, AI-native personal assistant. This repo is a
monorepo for the full product: backend API today, a frontend app to follow.

## Structure

```
backend/          FastAPI backend (see backend/README.md)
dumpbox/           Product specs (PRDs) — local-only, not committed
project-manager/   Running decisions log, phase tracker, open items — local-only, not committed
```

`dumpbox/` and `project-manager/` are gitignored on purpose: they're this
machine's working docs (product spec + project-management office) rather than
product code, so they aren't part of the repo history.

## Backend

See [backend/README.md](backend/README.md) for stack, setup, and structure.

```bash
cd backend
uv sync
cp src/.env.example src/.env
docker compose up -d
cd src && alembic upgrade head && cd ..
uv run uvicorn src.app.main:app --reload
```

## Frontend

Not started yet.
