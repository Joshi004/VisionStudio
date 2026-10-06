# Phase 2: Global settings and GPU connection test

The executor's first step is to save this plan as `plans/phase-02-settings.md`, following the template in Section 4.6 of `ITERATION_1_PHASES.md`.

## 1. Goal and outcome

When this phase is done, the Settings page at `http://127.0.0.1:5480/settings`:

- lists the 8 global settings from DB Section 6 (all except `api_contract_sources`);
- shows, for each one, its effective value and where it came from: saved, environment or built-in;
- has its own Save and Reset button on each setting, and shows validation errors under the field;
- shows "Will call: ..." for URL settings and "key set: yes or no" for the Bitdeer key;
- has a **Test connection** button that calls the GPU server's `/v1/health` and shows reachable or unreachable, the address called and the response time. The last result is kept in the database, so it survives restarts and Phase 4's banner can read it.

The backend also gets the **shared outbound HTTP helper** that all later phases must use: Docker address mapping, timeouts, size limits, no redirects, an explicit User-Agent, and the Bitdeer key rule.

```mermaid
flowchart LR
    SettingsPage -->|"GET, PUT, DELETE /api/settings"| SettingsApi["api/settings.py"]
    SettingsPage -->|"GET /api/gpu/connection, POST .../test"| GpuApi["api/gpu.py"]
    SettingsApi --> SettingsService["core/settings.py"]
    GpuApi --> GpuStatus["services/gpu_status.py"]
    GpuStatus --> SettingsService
    GpuStatus --> GpuServer["providers/gpu_server.py"]
    GpuServer --> Outbound["core/outbound.py"]
    Outbound -->|"mapped URL, UA, time and size limits"| GpuHealth["GPU server /v1/health"]
    SettingsService --> SettingTable[("setting table")]
```

## 2. Findings (read-only checks, 2026-10-06)

- **Code state.** Phase 1 is built as in its plan and phase log, but **nothing is committed** yet (`main` has no commits). The Settings page is a placeholder. `app/providers/` and `app/jobs/` are empty. `.env` defines only `BITDEEP_API_KEY` (I read the variable names only, never the values). `httpx` is not a dependency yet.
- **Phase 1 conventions in force:** one `app/api/<area>.py` router per area; `SessionDep`; `UTCDateTime` and `utcnow()`; assign a new object to change a JSON column; the Host and Origin middleware stay outermost; TanStack Query only, with no `refetchInterval`; run `npm run gen:api` after every API change.
- **[VERIFY] Health path and response:** `GET http://127.0.0.1:8012/v1/health` from the Mac returned HTTP 200 in 0.39 s with `{"status":"ok","default_partition":"background","job_retention_days":7.0}`. The OpenAPI spec (version 0.3.0) declares `status` as const `"ok"`, documents it as "always ok if the API process is reachable", and lists `/v1/health` as a public path even if auth is turned on.
- **[VERIFY] Reaching it from the container:** not yet checked, because the Docker daemon was not running during planning. This is Step 1 for the executor. `ANALYSIS.md` Section 3.6 recorded success on 2026-10-04.
- **Redirects:** `GET /v1/health/`, with a trailing slash, answers `307` to `/v1/health` on the same host. This gives a real redirect to test the helper against.
- **Size limits:** the guide JSON is 86 KB and `openapi.json` is 115 KB.
- **Cloudflare (Section 3.6):** I sent `GET https://api-inference.bitdeer.ai/v1/models` without a key. User-Agent `VisionPsyStudio/0.1` got 401, meaning it passed Cloudflare and was stopped by auth. `Python-urllib/3.13` got 403 with Cloudflare error 1010.
- **Partition:** the server takes a free-form Slurm partition name. An unknown name silently falls back to the default (`background`).
- **Versions:** `httpx` 0.28.1 is the current stable release on PyPI. Pydantic 2.13.5 is already locked.
- **Free port** for the "unreachable" check: nothing listens on 8099.

## 3. Decisions

- **Last test result (APPROVED, your answer):** stored as one internal row in `setting`, key `gpu_connection_last_test`. The settings API does not list it, and no one can edit it through the API. There is no migration. DATABASE_STRUCTURE.md Section 6 gets a note.
- **Reset (APPROVED, your answer):** `DELETE /api/settings/{key}` removes the saved row, so the environment or built-in value applies again.
- **YOUR APPROVAL: numeric ranges.**
  - `max_parallel_generations`: 1 to 16.
  - `poll_interval_seconds`: 10 to 300. The server's guide recommends polling every 10 to 15 s.
  - `max_parallel_ffmpeg`: 1 to 4.
  - Whole numbers only.
- **YOUR APPROVAL: no redirects are followed at all**, not even to the same host. This is stricter than "no redirects to another host". It is the simplest rule, and the app always calls exact paths. The error message names the redirect target, so you can paste it if you trust it.
- **Environment variables:** only `GPU_API_BASE_URL` (for `gpu_api_base_url`) and `BITDEEP_BASE_URL` (for `llm_base_url`), as in the Section 3.1 table and `.env.example`. The other settings have none.
- **Invalid layers are skipped with a note.** If a saved or environment value fails validation, the next layer applies and the API returns a `note` explaining why.
- **URLs are stored as typed:** trimmed, with trailing slashes removed, and with no query string or fragment allowed. Docker mapping (`localhost` and `127.0.0.1` to `host.docker.internal`) happens at call time and is shown as `will_call`. `::1` is not mapped, because Section 3.7 names only those two.
- **Test connection** tests the *saved* URL. It runs synchronously with a 5 s limit and is not a job, because jobs start in Phase 5. An unreachable server returns HTTP 200 with `reachable: false`.
- **"Reachable"** means HTTP 200 with a JSON object whose `status` is `"ok"`. Anything else is unreachable, with a readable reason.
- **A stored result for a different address** than the current GPU URL is reported as "not tested" (`null`), so a test of an old address never passes for the new one.
- **HTTP client:** one shared `httpx.AsyncClient`, created in the lifespan and closed on shutdown, with:
  - `follow_redirects=False`;
  - `trust_env=False`, so proxy variables and `.netrc` are ignored;
  - default header `User-Agent: VisioStudio/0.1`.
- **Limits:** responses are capped at 5 MB for JSON (`JSON_MAX_BYTES`) and checked while streaming. Each call has a total time limit (default 10 s, 5 s for health). The larger media limit arrives with the download method in the phase that needs it.
- **Key rule:** `Authorization: Bearer <key>` is added only when the scheme is `https`, the host is exactly `api-inference.bitdeer.ai` and the port is 443. The key is read from the environment at call time. It is never kept in `AppConfig`, logged or returned. `request()` takes no caller headers, so no other code can set `Authorization`.
- **Validation patterns:**
  - `gpu_partition`: blank, or `[A-Za-z0-9._-]{1,64}`.
  - `llm_model`: `[A-Za-z0-9._/:-]{1,200}`.
  - URL settings: http or https only; no user name or password (no `@` in the host part); no query or fragment; a valid port; at most 2048 characters; no spaces.
- **Page layout:** each setting row saves on its own, so errors stay with their field. There are no new npm packages; plain Mantine core is enough.

## 4. Changes

### Database
- **No migration.** It uses the existing `setting` table (DB Section 4.6).
- New internal row `gpu_connection_last_test`. Its `value` is `{reachable, called_url, elapsed_ms, http_status, default_partition, error, checked_at}`.
- Update DATABASE_STRUCTURE.md Section 6 with a short note on this row.

### Backend
- **[backend/pyproject.toml](backend/pyproject.toml):** run `uv add httpx` (0.28.1).
- **[backend/app/core/config.py](backend/app/core/config.py):** add `env_value(name: str) -> str | None`, which returns the stripped value, or `None` if the variable is unset or blank.
- **New [backend/app/core/urls.py](backend/app/core/urls.py):**
  - `class UrlError(ValueError)`, carrying a readable message;
  - `validate_base_url(raw: str) -> str`, for settings;
  - `check_request_url(url: str) -> None`, for the helper: http or https, a host, no `@`, query strings allowed;
  - `docker_mapped(url: str) -> str`;
  - `join_url(base: str, path: str) -> str`.
- **New [backend/app/core/settings.py](backend/app/core/settings.py), the registry and the service.**
  - `SettingSpec` is a frozen dataclass with `key`, `group`, `label`, `help`, `value_type` (`"string"` or `"integer"`), `default`, `env_var`, `is_url`, `allow_blank`, `min_value`, `max_value`, `pattern` (a regex and its message) and `blank_falls_back_to`.
  - `REGISTRY` is ordered, in three groups:
    - **GPU server:** `gpu_api_base_url`, `transcription_url` (blank falls back to `gpu_api_base_url`), `gpu_partition`;
    - **Language model:** `llm_base_url`, `llm_model`;
    - **Limits:** `max_parallel_generations`, `poll_interval_seconds`, `max_parallel_ffmpeg`.
  - The defaults are those in DB Section 6 and ANALYSIS Section 3.7.
  - Functions:
    - `validate_value(spec, raw: object) -> str | int`, which raises `SettingValueError`;
    - `get_spec(key)`, which raises `UnknownSettingError`;
    - `async read_setting(session, key) -> EffectiveSetting` and `async read_all(session) -> list[EffectiveSetting]`;
    - `async get_str(session, key) -> str` and `async get_int(session, key) -> int`, the accessors later phases call at the moment of use;
    - `async save_setting(session, key, raw)` and `async reset_setting(session, key)`, both of which commit;
    - `async read_internal(session, key)` and `async write_internal(session, key, value)`, guarded by `INTERNAL_KEYS = {"gpu_connection_last_test"}`.
  - `EffectiveSetting` holds `spec`, `value`, `source` (`saved`, `environment` or `built_in`), `updated_at`, `note` and `will_call`.
  - Writes use the SQLite upsert, `insert(Setting).on_conflict_do_update(...)`.
- **New [backend/app/core/outbound.py](backend/app/core/outbound.py).** It holds `USER_AGENT`, `BITDEER_HOST`, `JSON_MAX_BYTES`, `DEFAULT_TIMEOUT_S`, `start()`, `async close()` and `auth_headers_for(url) -> dict[str, str]`, plus:

```python
class OutboundError(Exception):
    def __init__(self, reason: Literal["url", "connection", "timeout", "redirect", "too_large"],
                 message: str) -> None: ...

@dataclass(frozen=True)
class OutboundResponse:
    url: str            # the URL actually called, after Docker mapping
    status_code: int
    headers: httpx.Headers
    body: bytes
    def json(self) -> Any: ...   # raises ValueError on invalid JSON

async def request(method: str, url: str, *, json: Any = None,
                  params: Mapping[str, str] | None = None,
                  timeout_s: float = DEFAULT_TIMEOUT_S,
                  max_bytes: int = JSON_MAX_BYTES) -> OutboundResponse: ...
```

  `request()` works in this order:
  1. Map the URL, then run `check_request_url`.
  2. Inside `asyncio.timeout(timeout_s)`, send with `stream=True`.
  3. If the response is a redirect, raise `OutboundError("redirect", ...)` naming the `Location`.
  4. Refuse early on an oversized `Content-Length`, then read the body chunk by chunk up to `max_bytes`.
  5. Close the response.
  6. Turn `TimeoutError` and `httpx.TimeoutException` into `"timeout"`, and other `httpx.TransportError`s into `"connection"`.
  7. Log the method, the URL, the status and the milliseconds, and never headers or bodies.

  Non-2xx responses are returned, not raised. Later phases extend this module (uploads in Phase 5, `download_to_file` in Phase 9) and reuse these checks.
- **New [backend/app/providers/gpu_server.py](backend/app/providers/gpu_server.py):**
  - `HEALTH_PATH = "/v1/health"` and `HEALTH_TIMEOUT_S = 5.0`;
  - `HealthResult`, a frozen dataclass with the fields of the internal row, and `to_json()` / `from_json()`, where `from_json` returns `None` on malformed data;
  - `async check_health(base_url: str) -> HealthResult`. It never raises for network problems, and it measures the elapsed time for every outcome.
- **New [backend/app/services/gpu_status.py](backend/app/services/gpu_status.py):**
  - `async run_connection_test(session) -> HealthResult`. It reads the URL, then calls `await session.commit()` to end the read transaction, so no transaction is held across the network call. Then it runs the check and writes the result with `write_internal`.
  - `async last_connection_test(session) -> HealthResult | None`. It returns `None` when the stored `called_url` differs from the URL that would be called now.
- **[backend/app/main.py](backend/app/main.py):** the lifespan calls `outbound.start()`, and on shutdown `await outbound.close()` before `engine.dispose()`.

### API
- **New [backend/app/api/errors.py](backend/app/api/errors.py):** `ErrorResponse(detail: str)`, used to document 404 and 422.
- **New [backend/app/api/settings.py](backend/app/api/settings.py)**, tag `settings`. It imports the core module as `settings_service`.
  - `GET /api/settings` returns `SettingsResponse { settings: SettingItem[], secrets: SecretStatus[] }`.
    - `SettingItem` has `key, group, label, help, value_type, value (int | str), source, default, env_var, allow_blank, min_value, max_value, will_call, note, updated_at`.
    - `secrets` is `[{name: "BITDEEP_API_KEY", label: "Bitdeer API key", is_set: bool}]`.
  - `PUT /api/settings/{key}` takes the body `SettingUpdate { value: StrictInt | StrictStr }` with `extra="forbid"`, and returns `SettingItem`.
    - An unknown key returns 404 `{"detail": "Unknown setting: <key>"}`. That includes `api_contract_sources` until Phase 4.
    - An invalid value returns 422 `{"detail": "<readable message>"}`.
  - `DELETE /api/settings/{key}` returns the new effective `SettingItem`, or 404.
- **New [backend/app/api/gpu.py](backend/app/api/gpu.py)**, tag `gpu`.
  - `GET /api/gpu/connection` returns `{ last_test: ConnectionTest | null }`. It reads the database only and never calls the server.
  - `POST /api/gpu/connection/test` takes no body and returns `ConnectionTest`, always with status 200.
  - `ConnectionTest` has `reachable, called_url, elapsed_ms, http_status, default_partition, error, checked_at`.
- **[backend/app/api/__init__.py](backend/app/api/__init__.py):** include both routers.

### Frontend
- **New [frontend/src/api/errors.ts](frontend/src/api/errors.ts):** `class ApiError extends Error` with a `status`, and `detailMessage(error: unknown, fallback: string): string`, which uses `detail` only when it is a string.
- **New [frontend/src/api/settings.ts](frontend/src/api/settings.ts):** `useSettings()` with key `["settings"]`, and `useSaveSetting()` and `useResetSetting()`. On success, both invalidate `["settings"]` and `["gpu", "connection"]`.
- **New [frontend/src/api/gpu.ts](frontend/src/api/gpu.ts):** `useGpuConnection()` with key `["gpu", "connection"]`, and `useTestGpuConnection()`, which invalidates that key on success.
- **[frontend/src/pages/SettingsPage.tsx](frontend/src/pages/SettingsPage.tsx):**
  - Sections from top to bottom: the GPU connection card, then one section per `group` in registry order, then "Secrets" (the name, "set" or "not set", and "read from .env, never shown").
  - While loading it shows a `Loader`. On error it shows a red `Alert` with the message and "Press Refresh to try again".
- **New [frontend/src/components/settings/SettingRow.tsx](frontend/src/components/settings/SettingRow.tsx):**
  - Inputs: a `TextInput` for strings and a `NumberInput` (with min, max and no decimals) for integers. The help text goes in `description`.
  - A source badge: "Saved", "From <ENV_VAR>" or "Built-in default".
  - A dimmed line "Default: ... · Environment variable: ...". Under it, "Will call: ..." when `will_call` is set, and the `note` in orange.
  - Save is disabled while the draft equals the value or a save is running. Reset is shown only when the source is saved. Mutation errors appear as the input's `error`.
  - The page renders each row with `key={`${key}|${source}|${value}`}`, so the draft resets after a save without a `useEffect`.
- **New [frontend/src/components/settings/GpuConnectionTest.tsx](frontend/src/components/settings/GpuConnectionTest.tsx):**
  - It says "Tests the saved GPU server URL", and has a Test connection button with a loading state.
  - The last result shows as green "Reachable in N ms · default partition X", or red "Unreachable: <error>".
  - Then "Called <url> at <local time>", or "Not tested yet for this address".
  - A failure of the request itself, such as the backend being down, shows separately as "Could not run the test: ...".
- **[frontend/src/api/schema.d.ts](frontend/src/api/schema.d.ts):** regenerate with `npm run gen:api`.

### Configuration
- `.env.example` already has `GPU_API_BASE_URL` and `BITDEEP_BASE_URL`, so it does not change. Compose and nginx do not change either.

## 5. Reading list for the executor

- ITERATION_1_PHASES.md: Section 4 (all), the Phase 2 section, and the Phase 1 log entry.
- ANALYSIS.md: 3.1 ("Configuration has two layers" and the variable table), 3.6 (the Docker mapping and Cloudflare rows), and 3.7 (the table and the rules).
- DATABASE_STRUCTURE.md: Sections 4.6 and 6.

## 6. Steps in order

1. **Preconditions and [VERIFY].**
   - Confirm with the user that Phase 1 is committed (Section 1, step 4).
   - Start Docker Desktop and run `docker compose up -d`. Both services must be healthy.
   - Run `docker compose exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:8012/v1/health', timeout=5).read().decode())"`. It must print `{"status":"ok",...}`.
   - Save this plan as `plans/phase-02-settings.md`.
2. **Dependency.**
   - In `backend/`, run `uv add httpx`.
   - Check: `uv run python -c "import httpx; print(httpx.__version__)"` prints `0.28.1`.
3. **URLs, config and the settings service.**
   - Write `urls.py`, `env_value` and `core/settings.py`.
   - Check: `uv run ruff check . && uv run ruff format --check .`.
   - Check: a `uv run python -c` snippet shows that `validate_base_url("http://localhost:8012/")` gives `http://localhost:8012` and `docker_mapped` of that gives `http://host.docker.internal:8012`.
4. **Outbound helper, GPU health and status.**
   - Write `outbound.py`, `gpu_server.py` and `gpu_status.py`, and wire the lifespan.
   - Check: ruff is clean and `uv run python -c "import app.main"` works.
5. **API.**
   - Write the routers and rebuild with `docker compose up --build -d`.
   - Check: `curl -s http://127.0.0.1:5480/api/settings` lists 8 settings, and `/api/docs` shows the new operations.
6. **Frontend.**
   - Run `npm run gen:api`, then write the hooks, the components and the page, and rebuild.
   - Check: `npm run typecheck && npm run lint && npm run build` pass, and the page works in the browser.
7. **Docs.** Add the DATABASE_STRUCTURE.md Section 6 note about `gpu_connection_last_test`.
8. **Acceptance and phase log.**
   - Run every check below and write the Phase 2 entry in Section 7 of ITERATION_1_PHASES.md.
   - Under "Decisions later phases must follow", list:
     - read settings through `get_str` / `get_int` at the moment of use;
     - all outbound HTTP goes through `outbound.request()`, with no other httpx client;
     - map URLs only through `docker_mapped`, and join them with `join_url`;
     - a new internal `setting` row must be added to `INTERNAL_KEYS`;
     - GPU reachability is read and written through `gpu_status`.
   - Do not commit.

## 7. Acceptance checks

Run these from the repo root, with `B=http://127.0.0.1:5480/api` and `J='Content-Type: application/json'`.

1. **Every setting with its source.**
   - Run `curl -s -X DELETE $B/settings/gpu_api_base_url >/dev/null`, then `curl -s $B/settings | python3 -c "import json,sys; [print(s['key'], s['value'], s['source']) for s in json.load(sys.stdin)['settings']]"`. It prints 8 lines, all `built_in` with the current `.env`, and no `api_contract_sources`.
   - Environment layer, without editing `.env`: `docker compose run --rm --no-deps -e GPU_API_BASE_URL=http://localhost:8012 -e BITDEEP_BASE_URL=ftp://bad backend python -c "<script that prints value, source, note of gpu_api_base_url and llm_base_url via read_setting>"`. It prints `http://localhost:8012 environment`, and `https://api-inference.bitdeer.ai/v1 built_in` with a note that `BITDEEP_BASE_URL` is not valid.
   - The Settings page shows each row with its badge.
2. **Docker mapping and persistence.**
   - `curl -s -X PUT -H "$J" -d '{"value":"http://localhost:8012/"}' $B/settings/gpu_api_base_url` returns `value` `http://localhost:8012`, `source` `saved` and `will_call` `http://host.docker.internal:8012`. The `transcription_url` row (blank) also shows that `will_call`.
   - Run `docker compose restart backend`, wait for healthy, and run GET again: the value is the same. The page shows "Will call: http://host.docker.internal:8012".
3. **Rejections.** Run `curl -s -w ' HTTP %{http_code}\n' -X PUT -H "$J" -d '<body>' $B/settings/<key>` with:
   - `{"value":"ftp://example.com"}` gives 422 "Use an http:// or https:// address.";
   - `{"value":"http://user:pass@example.com"}` gives 422 "Remove the user name and password from the address.";
   - `max_parallel_generations` with `0` gives 422 "Enter a number from 1 to 16.", and with `"4"` gives 422 "Enter a whole number.";
   - `gpu_partition` with `"main; x"` gives 422;
   - `api_contract_sources` gives 404.
   - Afterwards, GET shows nothing changed. In the UI, saving `ftp://...` shows the message under the field.
4. **Test connection.**
   - Server up: `curl -s -X POST $B/gpu/connection/test` returns `reachable: true`, `called_url` `http://host.docker.internal:8012/v1/health`, `elapsed_ms` and `default_partition` `background`. The UI shows it in green.
   - Server unreachable:
     - Confirm `lsof -nP -iTCP:8099 -sTCP:LISTEN` prints nothing, then save `http://localhost:8099` and test. The answer is HTTP 200 with `reachable: false` and a readable `error`, and the page shows red text, not an error page.
     - While the URL points at 8099, `curl -s -o /dev/null -w '%{time_total}\n'` for `$B/settings` and for `$B/gpu/connection` stays under 0.2 s.
   - Stored result:
     - After `docker compose restart backend`, `GET $B/gpu/connection` still returns the 8099 result.
     - After saving `http://localhost:8012` again, it returns `last_test: null`. Test again and it is reachable.
     - Finally, `DELETE` returns `gpu_api_base_url` to `built_in`.
5. **The key never leaves the backend.** Run:
   - `KEY="$(grep '^BITDEEP_API_KEY=' .env | cut -d= -f2-)"; [ -n "$KEY" ] || echo "key empty"`;
   - then `curl -s <url> | grep -cF -- "$KEY"` for `$B/settings`, `$B/gpu/connection`, `$B/openapi.json` and `$B/health`, and for `curl -s -X POST $B/gpu/connection/test`;
   - then `docker compose logs backend 2>&1 | grep -cF -- "$KEY"`;
   - then `unset KEY`.

   Every count is 0, and the key is never printed. `secrets` shows `is_set: true`.
6. **Outbound helper.** Run a `docker compose exec backend python -c` script that calls `outbound.start()` and then:
   - `auth_headers_for(...)` for `https://api-inference.bitdeer.ai/v1/models`, `http://api-inference.bitdeer.ai/v1/models`, `https://api-inference.bitdeer.ai.example.com/v1` and `http://host.docker.internal:8012/v1/health`. It prints booleans only: True, False, False, False.
   - `request("GET", "http://localhost:8012/v1/health/")` raises `redirect`, naming `http://host.docker.internal:8012/v1/health`. This also shows the localhost mapping works.
   - `request("GET", "http://localhost:8012/openapi.json", max_bytes=1000)` raises `too_large`.
   - A **free** Bitdeer call (the model list, no tokens): `request("GET", "https://api-inference.bitdeer.ai/v1/models")`, printing only the status and the model count. Expected `200 8`. This shows the User-Agent passes Cloudflare from inside the container and the key is attached.
7. **No polling, and no GPU calls on page load.** Open the Settings page and leave it idle for a minute: no requests appear in the network panel. Refresh sends `GET /api/settings`, `/api/gpu/connection` and `/api/health`, and `docker compose logs --since 1m backend | grep outbound` shows nothing for them.
8. **Security and regressions.**
   - A cross-origin PUT (`-H 'Origin: https://evil.example'`) gets 403.
   - A PUT with `Content-Type: text/plain` gets 422.
   - The Phase 1 checks 2 to 4 (health, app shell, Host and Origin) still pass.
   - Running `npm run gen:api` twice gives the same `shasum`.
   - ruff, `tsc` and ESLint are clean.

## 8. Out of scope

- `api_contract_sources`, the contract check, the API list and banners (Phase 4).
- Testing the transcription URL or the LLM (Phases 5 and 6). There is no Test button for them.
- Using the partition, the limits or the poll interval. They are only stored and validated here (Phases 5, 9 and 10).
- Multipart uploads, `download_to_file`, caller headers and a media size limit in the helper. The phase that needs them adds them.
- Write-only secret fields, and any secret in the database.
- Project settings (Phase 3), a header status indicator for the GPU, new npm packages, automated tests and mock servers.

## 9. Risks

**Stop and ask**
- The backend container cannot reach `host.docker.internal:8012` in Step 1.
- The free Bitdeer model list returns 403 (Cloudflare 1010) from inside the container. Do not try other User-Agents without asking; Phase 6 depends on this.
- `uv add httpx` resolves to something other than 0.28.x (for example a 1.x release with API changes).
- The GPU server is down while building. Finish the build and the "unreachable" checks, then ask the user to bring it up for the "reachable" ones.

**Adjust and carry on**
- If FastAPI's custom 422 documentation produces awkward generated types, keep the backend as planned and handle it in `detailMessage`.
- If Mantine's `NumberInput` gives `""` for an empty field, send it anyway; the backend rejects it with "Enter a whole number.".
