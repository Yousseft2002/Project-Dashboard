# Vercel cloud HTTP adapter

`tracker.server:Handler` is a BaseHTTPRequestHandler class for the existing long-running socket server. It is not an ASGI application. The Vercel entrypoint is `tracker.vercel_app:app`, explicitly declared in root `pyproject.toml`.

The FastAPI adapter calls shared device authentication/validation in `cloud_http`, `agent_api` and `CentralStore`. Existing owner route functions implement dashboard, project/task/planner, saved import/export and physical-build operations. The adapter invokes those functions with request-bound cloud resources; it never constructs a Handler, binds a port or calls serve_forever/start_lan. Module imports do not start workers or open a SQLite database. Local server startup still starts its analysis/preview workers.

## Environment variables

Set these for Production (and Preview only if intentionally connecting that deployment to a separate test database):

- `DATABASE_URL`: Neon's PostgreSQL URL, preferably pooled, including `sslmode=require` or stricter. Missing/invalid values fail closed. Vercel never falls back to SQLite.
- `APP_PASSWORD`: dashboard owner password, at least 16 characters. Never a device token. Configure it privately in Vercel, not Git or chat.
- `PUBLIC_HOSTNAME`: optional explicit stable production domain, without scheme/path. Vercel's supplied `VERCEL_PROJECT_PRODUCTION_URL` and `VERCEL_URL` are also allowed hosts. Do not configure wildcards. Custom domains require PUBLIC_HOSTNAME.

Vercel supplies `VERCEL` and its URL variables automatically. `PORT`, `APP_ENV`, `TRACKER_DATA_DIR`, LAN credentials and Windows collector tokens are not required. Do not configure an HTTP server start command. Vercel's build uses `python build_vercel.py`; dashboard JS/CSS/images are copied to `public/` and served by the CDN. HTML is served through authenticated ASGI routes, preserving `#/integrations` and `#/debug`.

## Persistence and security

PostgreSQL implements the existing store's parameterized connection contract, generated IDs, schema metadata and owned SQL dialect differences. Database migration transactions use a PostgreSQL advisory lock; existing owner/device records are retained. Sessions contain hashed tokens and expire after 30 days. Rate counters persist across function instances: 25 login attempts per 10 minutes globally, 60 pairing operations per minute globally and 60 authenticated requests per device per minute. Global login limiting avoids trusting spoofable forwarded client-IP headers.

The adapter checks exact configured Host and same-origin Origin/Fetch-Site, uses Secure/HttpOnly/SameSite=Strict cookies, enforces bounded streamed bodies, validates authenticated device identities and acknowledgements, and retains the frontend's security headers. Vercel's request ceiling limits owner transfer requests to 4 MB here; unusually large local exports need a future chunked transfer flow. Imported PNG previews remain in PostgreSQL. No source files or collector secrets are published as CDN assets.

## Local-only capabilities

Filesystem discovery/scans, LAN listener, opening PC projects/folders, local Claude/Codex access, AI CLI planner instructions, analysis workers and headless preview capture are unavailable on Vercel. Deterministic planner generation, saved tasks, owner imports and agent telemetry remain request-driven. The Windows agent continues collecting approved metadata locally.

## Agent target migration

Use the stable production origin, not a disposable preview URL. Update the checkout, then run `setup_collector.ps1 -Agent -ServerUrl https://YOUR-PRODUCTION-DOMAIN`. Review workspace choices and approve pairing on that same deployment. Setup saves the explicitly approved origin and binds its DPAPI credential to it. Existing Render credentials are not sent to a different origin; new pairing is required. Keep the same installation/agent identity and approved workspaces. Stop the existing scheduled task while changing its config, then restart it after pairing.

## Verification

Run `python -c "import tracker.vercel_app; assert tracker.vercel_app.app"` and `python -m unittest discover -s tests` with FastAPI, psycopg and the test dependency httpx installed. Set `TEST_DATABASE_URL` only to an isolated Neon test database to run the real reconnect/auth persistence integration test. The ordinary suite uses an explicitly injected temporary SQLite fixture and does not assert Neon persistence.

Deployment acceptance additionally requires actual production `/api/health` with `database=postgresql`, owner login, device pairing, a real YT-Laptop heartbeat/project/event upload and credential continuity after a new function instance/deployment. Do not substitute simulated local tests for those live results.
