# Visio Studio

A two-container app: `frontend` (nginx serving a built React app) and
`backend` (FastAPI with SQLite on a named volume).

What it does today:

- **Projects**: create a project (name, orientation, video size and frame
  rate) and open it. A project page is the story workspace: paste the story,
  and see its word count and estimated length (with a warning above the
  length limit) and the stages of the story pipeline. The **Story Bible**
  stage works: press Run to have the language model write the story's title,
  genre, tone, visual style and rules, and Re-run for a new version (older
  versions stay readable). Once the Story Bible is up to date, the **Characters**
  and **Environments** stages list the story's characters and places (an id, a
  name and one line each), and the **Scenes** stage divides the story into its
  scenes (a title and one line each, plus the exact slice of the story the scene
  owns, so the slices of all the scenes together are the whole story). The
  three can run at the same time, and each shows "Out of date" when the story or
  the Story Bible changes. The other stages are placeholders ("Not available
  yet") until later phases build them.
- **Labs**: the Image lab, the Voice lab and the Video lab try the GPU
  server's models by hand, and the Character lab makes characters, looks and
  takes. The Activity page lists their background jobs.
- **Settings**: the GPU server address, the language-model roles (the story
  stages use the "Story provider" and "Story model"; set the provider to the
  GPU server's Qwen3.8 to try them while Bitdeer is not available), the image
  mode, the shot-duration limits, the story length estimate (speaking pace and
  longest story) and the parallel-job limits.

The earlier voiceover-driven narration pipeline (transcription, scenes, clips,
render, cast, automatic run) was retired in PHASE-046. Its code is kept at the
git tag `narration-final`, for example
`git show narration-final:backend/app/services/scenes.py`.

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

The backend container runs `alembic upgrade head` every time it starts, so a
rebuild applies any new migration to the database on the `data` volume.
Migration `0022` (PHASE-046) **permanently deletes** the narration data: the
scenes, transcripts, cast and every narration job. It cannot be undone, and it
has no downgrade. Before the first start after pulling it, copy the database
to a folder outside Docker (stop the backend first, so no write is in
flight):

```bash
docker compose stop backend
mkdir -p ~/visio-studio-backup
docker compose run --rm --no-deps -v "$HOME/visio-studio-backup:/backup" \
  --entrypoint sh backend -c 'cp /data/app.db* /backup/'
ls ~/visio-studio-backup   # app.db must be there before you go on
docker compose up --build -d
```

`app.db*` also copies the `-wal` and `-shm` files when they exist. Media files
are not touched by the migration, so they are not part of this copy.

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








