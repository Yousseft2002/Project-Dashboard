# Collector connection audit — October 4, 2026

## Existing collector before this change

The executable was `python collector.py [--config collector.config.json] [--once|--dry-run]`. It read JSON from the working directory, requiring a `server` origin and `workspaces` list. The example targeted `https://project-dashboard-0d02.onrender.com`, but there was no `PROJECT_PLANNER_URL` override or explicit development-mode guard. HTTP loopback was accepted automatically.

Device creation happened only through owner-authenticated `POST /api/integrations/devices`. An owner entered a device ID in the browser and received a random token once. The database stored only its SHA-256 hash. The user had to export that token as `COLLECTOR_TOKEN` in the collector's environment. The collector had no registration handshake, device name/platform/version metadata, setup utility, protected credential storage or live status/read-back command.

On launch it called `POST /api/collector/heartbeat` with Bearer authentication, scanned every configured workspace, then called `POST /api/collector/projects`. Continuous mode checked heartbeat every 30 seconds between scans, with scans every 300 seconds. A scan could delay heartbeat because both ran in one thread. Missing directories produced source errors; missing tokens caused startup failure. Console errors were generic exception names or HTTP codes. Configuration and tokens were not generated automatically.

## Production endpoint probes

Direct HTTPS probes against the live deployment (before this change) returned:

| Request | Actual response |
|---|---|
| GET `/health` | 200 JSON, `status: ok` |
| GET `/api/health` | 401 JSON, browser login required |
| POST `/api/collector/register` | 404 JSON, endpoint not implemented |
| POST `/api/collector/heartbeat`, no token | 401 JSON, invalid/revoked credential |
| POST `/api/collector/projects`, no token | 401 JSON, invalid/revoked credential |
| POST `/api/collector/activity` | 404 JSON, endpoint not implemented |

The signed-in production dashboard visibly showed zero devices and zero projects. It was serving PR #2, commit `5cf3ff5`. Render's Disk/Compute pages confirmed Free compute and no persistent-disk support. The issue was absence of an enrolled/running collector, not a mocked dashboard count.

## New connection flow

`setup_collector.ps1` finds Python/Git, asks for a device name/server, suggests bounded workspace roots for explicit selection, and supports pairing or a pre-issued collector token. Pairing generates the token locally and submits only hashes to the server. Owner approval of the displayed code registers the hash. The server never receives or stores the raw token during pairing. The local token is protected with Windows DPAPI; config/state JSON contain no credentials.

Public `GET /api/health` identifies the service and collector API version. `POST /api/collector/register` is authenticated with the device's collector token; it does not use browser login. Registration stores name/platform/version/installation ID and updates online status before scanning. The collector proves heartbeat by writing it and reading it through its authenticated, device-scoped `GET /api/collector/status`. Only then does it inspect/upload one Git repository and read back its project identity and latest commit. Full workspace uploads remain gated by that successful verification for the same server/device/installation.

Activity/commit records travel atomically with `/api/collector/projects`; there is intentionally no standalone activity endpoint in this phase. Setup does not call that missing endpoint. Continuous mode sends independent 60-second heartbeats while scanning, with 300-second scans. Connection failures have explicit messages and non-secret local state. Server ingestion logs contain device IDs/counts/reasons, never request bodies or tokens. Known revoked credentials can be attributed by their stored hash; arbitrary invalid tokens remain unattributed rather than trusting a supplied name.

## Acceptance boundaries

Automated tests use isolated SQLite/HTTP instances and cover handshake ordering, authenticated read-back, pairing authorization, DPAPI, retries and two-device deduplication. These are not production evidence. Production proof is recorded separately after deployment and real collector execution. A second physical computer cannot be simulated by registering a fake device. Page refresh does not prove restart persistence. Durable storage is required to preserve SQLite and collector credential hashes after Render instance replacement.
