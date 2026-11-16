# Visio Studio

A three-container app: `frontend` (nginx serving a built React app),
`backend` (FastAPI with SQLite on a named volume) and `motion` (the Graphics
lab's renderer: Remotion and headless Chrome, with no internet, no volume and
no secrets; only the backend can reach it). `motion` needs at least 4 GB of
memory in Docker and takes a few minutes to build the first time, because the
image downloads the browser.

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

Check all three services came up healthy:

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
docker compose logs -f motion
```

The motion service is only needed to make Graphics lab videos. If a render
fails with a message that names the motion service, check `docker compose ps`
and start it with `docker compose up -d motion`. The **Motion service test
card** on the Graphics tab renders a test video to show that it works.

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

The database is always on the named volume `visio-studio_data`:

- `/data/app.db` (plus its `-wal` and `-shm` files) — the SQLite database.

By default the volume also holds the files:

- `/data/media/` — uploaded and generated media files.
- `/data/tmp/` — working files, cleared when the backend starts.

### Keeping the files in a folder on the Mac

Media and working files can live in a folder you can open in Finder, while the
database stays in the volume. Create the folder once, with its `media/` folder
and an empty marker file (the app never creates the marker itself, so a mistyped path or an
unplugged disk is not mistaken for the right folder):

```bash
mkdir -p ~/VisioStudioData/media && touch ~/VisioStudioData/.visio-studio-files
```

Then add two lines to `.env` (an absolute path, not `~`) and restart:

```text
COMPOSE_FILE=docker-compose.yml:docker-compose.files.yml
VISIO_FILES_DIR=/Users/<you>/VisioStudioData
```

```bash
docker compose up -d
```

New files then go to
`<folder>/media/` and `<folder>/tmp/`. The `frontend` container sees only
`media/`, read-only. If the folder is missing, Docker refuses to start the
backend. If the marker is missing or the folder cannot be written, the backend
health check reports "files folder" as degraded and nothing is stored.

This does not copy the media already in the volume: until that is done on
purpose (STOR-002), set it up only on a fresh install or to try it. To switch
back, remove the two lines and restart.

**Do not rename, move or delete files in that folder from Finder.** The
database stores each file's exact name, so the app breaks when a file changes.
Opening, playing and copying files is fine. The warning about
`docker compose down -v` still applies, because the database is in the volume.

### Database snapshots

With the files folder set, the app keeps a copy of the database in
`<folder>/db-snapshots/`, named like `app-2026-11-16_1530Z.db` (UTC). A snapshot
is made by SQLite's `VACUUM INTO`, never by copying the live file, and is
checked with `PRAGMA integrity_check` before it replaces the old one. The app
keeps working while it is made.

- When: automatically once the newest snapshot is a day old (checked hourly,
  the first check five minutes after the backend starts), and with **Make a
  snapshot now** in Settings, Backups.
- How many: **one**. A snapshot is about 1.5 GB, and room for two at once is
  needed while a new one is made. Because only the newest is kept, a mistake in
  the live data is carried into the snapshot within a day. Copy the file
  elsewhere first if you want to keep a particular state.
- Age: Settings, Backups shows the last snapshot, and the header warns when it
  is over three days old or none exists. A failed snapshot never replaces a good
  one. Files ending in `.partial` are unfinished and are removed at the next start.
- Without the files folder, snapshots are off: a copy inside the volume would not
  survive losing the volume.

**Restoring** is a manual step, not a button. Stop the app, move the live
database aside (do not delete it), then copy the snapshot in:

```bash
docker compose stop backend frontend    # never `down -v`
docker run --rm --network none --user root --entrypoint sh \
  -v visio-studio_data:/data \
  -v "$HOME/VisioStudioData/db-snapshots":/snap:ro \
  visio-studio-backend -c '
    set -e
    stamp=$(date +%Y%m%d-%H%M%S)
    for f in app.db app.db-wal app.db-shm; do
      [ -e /data/$f ] && mv /data/$f /data/$f.before-restore-$stamp
    done
    cp /snap/app-YYYY-MM-DD_HHMMZ.db /data/app.db   # the snapshot file to restore
    chown 10001:10001 /data/app.db
  '
docker compose up -d
```

Then check `/api/health`. Moving the `-wal` and `-shm` files aside matters: a
leftover `-wal` from the old database would be applied to the restored one.
The `*.before-restore-*` files stay in the volume until you remove them yourself.

## Secrets

`.env` holds secrets (API keys, etc.) and is never committed — it's
excluded by `.gitignore` and by both services' `.dockerignore`. Only the
backend container reads it, through `env_file: .env` in
`docker-compose.yml`.

**Never run `docker compose config` or `docker inspect` on a running
container and share the output.** Both print resolved environment values,
including the secrets from `.env`.

The `YOUTUBE_*` values (client id, client secret, redirect address and the
token key) are secrets too. Connected channels' tokens are stored encrypted in
the database with `YOUTUBE_TOKEN_KEY` and are never shown or logged.








