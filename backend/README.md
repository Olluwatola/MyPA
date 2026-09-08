# MyPA backend

FastAPI backend for MyPA — a multitenant, AI-native personal assistant. See
`../dumpbox/PRD-personal-assistant-mvp.md` for the product spec and
`../project-manager/` for the running decisions log and phase tracker.

This slice covers the project skeleton, the `users` and `token_blacklist`
tables, and full auth (register, login, refresh, logout, Google OAuth). It was
adapted in place from
[`igorbenav/fastapi-boilerplate`](https://github.com/igorbenav/fastapi-boilerplate)
pinned at tag `v0.17.0` — the last release before that template's upstream
`main` branch was rewritten into a different architecture (session/CSRF auth,
Taskiq, vertical-slice modules) that no longer matches this machine's FastAPI
conventions. See `../project-manager/decisions-log.md` for the full story.

## Stack

FastAPI · SQLAlchemy 2.0 (async) · PostgreSQL · Alembic · FastCRUD · JWT
(python-jose) · Redis (`redis.asyncio`) · ARQ · structlog.

## Setup

```bash
cd backend
uv sync
cp src/.env.example src/.env   # then fill in real values
docker compose up -d           # local Postgres + Redis only — the app itself runs via uv, not containerized
cd src && alembic upgrade head && cd ..
uv run uvicorn src.app.main:app --reload
```

`/docs` is gated on `ENVIRONMENT` (`local`: open, `staging`: superuser only,
`production`: none) — set in `src/.env`.

## Tests

```bash
uv run pytest tests/
uv run ruff check src tests
uv run mypy src
```

## Structure

```
src/
├── app/
│   ├── main.py               # entry point
│   ├── api/v1/                # register, login, refresh, logout, auth/google/*, users/me, ready
│   ├── core/                  # config, db, security, oauth/google, logger, setup, exceptions
│   ├── models/                # User, TokenBlacklist (SQLAlchemy)
│   ├── schemas/                # Pydantic v2 request/response shapes
│   ├── crud/                   # FastCRUD instances
│   └── middleware/
├── migrations/                 # Alembic (async env)
└── scripts/create_first_superuser.py
tests/
```

## Not yet in this slice

`tasks`, `goals`, Notion sync tables, notification/job state, the vector
store, the ARQ worker (no background job exists yet), and tier-based rate
limiting — deferred to their own slices per `../project-manager/phase-tracker.md`.
