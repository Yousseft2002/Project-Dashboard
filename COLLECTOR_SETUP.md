# Connect a Windows computer to production

From an up-to-date clone of this repository, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_collector.ps1
```

The wizard finds Python 3.11+ and Git, asks for the device name, defaults to `https://project-dashboard-0d02.onrender.com`, suggests existing development folders, and lets you select/remove/add roots. It does not scan the entire C: drive. Suggestions include common folders, VS Code recent-workspace metadata, and bounded recorded working directories; session activity is not collected.

Choose **P** for browser pairing. Open the signed-in production dashboard → Settings → Integrations and approve the exact 12-character code displayed on that computer. No browser password or collector token needs to be pasted into a terminal or chat. The token is generated on the computer; only its hash reaches the server during pairing. The approval expires after ten minutes. Alternatively, choose **T** and enter a device-specific token issued by the owner dashboard through a secure prompt.

The wizard then:

1. Checks the JSON health/API version, registers the collector, writes a heartbeat and reads it back from the production database.
2. Stops for you to verify the device is online on the dashboard.
3. Asks for one real Git repository with at least one commit; uploads it and reads back its latest commit SHA.
4. Stops for you to verify the project and commit are visible after page refresh.
5. Syncs the approved workspace folders and runs continuously in that window. Ctrl+C stops it. Use `-NoRun` to finish after setup/first sync.

Repeat independently on the laptop and desktop. Never copy a token/protected-token file or installation ID from one computer to another. Repository remote identities merge clones into one project with separate device observations.

## Configuration and credentials

Non-secret settings are in `collector.config.json` beside the script; diagnostics are in `collector.config.state.json`. Tokens are encrypted with Windows DPAPI in `collector.token.dpapi`, readable only by the same Windows user on that computer. These files are ignored by Git. Tokens are never printed by the collector. `COLLECTOR_TOKEN` remains available for environment-based configuration and overrides the protected file. DPAPI operations require a normal loaded Windows user profile; impersonated/sandbox service profiles can fail.

`PROJECT_PLANNER_URL` overrides the configured server. Production requires HTTPS and rejects localhost, private/unspecified addresses and ports 8765/8766. Local testing requires **both** a loopback URL and `--local-development` (`-LocalDevelopment` for the wizard). TLS certificate checks remain enabled; redirects never forward credentials.

Heartbeats run independently every 60 seconds, including during scans. Workspace scans run every 300 seconds. Server-side Sync now requests are picked up on the next heartbeat. Keep the collector window running; unattended startup/Task Scheduler installation is not part of setup.

## Commands

```powershell
python collector.py test --heartbeat-only
python collector.py test --project "C:\path\to\one\git-repository"
python collector.py status
python collector.py --once
python collector.py
```

`--test` is an alias for `test`; `--config` supports a different non-secret JSON configuration. Full workspace ingestion is blocked until one-project verification succeeds for the current server/device/installation. `status` reads live device-scoped API data and non-secret local diagnostics. A returned HTML/login webpage, missing API, rejected token or failed database read-back is an error, never a successful connection.

Commit/activity metadata travels in the project batch. No `/api/collector/activity` call is made. The public health endpoint is `/api/health` (also `/health`); collector endpoints are `/api/collector/register`, `/api/collector/heartbeat`, `/api/collector/projects`, `/api/collector/status`, and pairing start/claim. Owner authentication is separate and required for pairing approval and owner debug/dashboard access.

Only metadata leaves the computer: project names/paths, sanitized remote identities, branches, commit SHAs/timestamps, counts and file-modification timestamps. Source bodies, prompts, README content, commit messages, credentials and environment values are not uploaded. Default ignores exclude sensitive/dependency/build/cache/system directories. Add custom `ignore` patterns. Claude/Codex/editor session collection is paused until basic device syncing passes acceptance.

## Production persistence

The currently observed Render Free service has no persistent disk. Page-refresh persistence can be verified, but SQLite and registered token hashes are not durable across instance replacement/redeploy. To meet restart persistence, attach a persistent disk on paid compute and set `TRACKER_DATA_DIR` to its mount directory (for example `/var/data/project-tracker`). Relocating the path without attaching durable storage does not solve persistence. Keep the environment password and hostname settings. An existing external database requires a separate storage implementation; PostgreSQL is not implemented here.

Settings → Integrations shows heartbeats, last sync, last attempt and server-observed errors. Client-side network/DNS failures cannot reach the server; `collector.py status` and the local state file show these errors. Unknown invalid tokens are unattributed. Known revoked tokens can be attributed by their hash.

See [the collector audit](COLLECTOR_AUDIT.md) for original behavior and actual production probe results. Production acceptance evidence is tracked in `PRODUCTION_SYNC_PROOF.md`; automated tests or simulated devices do not establish that the laptop connected or that Render storage survived a restart.
