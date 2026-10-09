# Visio Studio

A two-container app: `frontend` (nginx serving a built React app) and
`backend` (FastAPI with SQLite on a named volume). This is the Phase 1
foundation — the app shell, the full database schema, and the security
baseline. There are no features yet.

## Start

```bash
cp .env.example .env
# edit .env and fill in the values you have
docker compose up --build -d
```

Check both services came up healthy:

```bash
docker compose ps
```

Then open http://127.0.0.1:5480 (or `http://127.0.0.1:<APP_PORT>` if you set
`APP_PORT` in `.env`).

## Stop

```bash
docker compose down
```

This stops and removes the containers but keeps the `data` volume, so your
database and media are not touched.

**Never run `docker compose down -v`.** The `-v` flag deletes the named
volume, which permanently deletes the SQLite database and all media.

## Rebuild

After changing backend or frontend code:

```bash
docker compose up --build -d
```

## Logs

```bash
docker compose logs -f backend
docker compose logs -f frontend
```

## Regenerating API types

Whenever the backend's API changes, regenerate the typed client from the
running backend's OpenAPI schema:

```bash
cd frontend
npm run gen:api
```

This writes `frontend/src/api/schema.d.ts`, which is committed to the repo.

## Linting

```bash
cd backend && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run lint && npm run typecheck
```

## Where the data lives

Everything is stored on the named volume `visio-studio_data`:

- `/data/app.db` (plus its `-wal` and `-shm` files) — the SQLite database.
- `/data/media/` — uploaded and generated media files.

## Secrets

`.env` holds secrets (API keys, etc.) and is never committed — it's
excluded by `.gitignore` and by both services' `.dockerignore`. Only the
backend container reads it, through `env_file: .env` in
`docker-compose.yml`.

**Never run `docker compose config` or `docker inspect` on a running
container and share the output.** Both print resolved environment values,
including the secrets from `.env`.








