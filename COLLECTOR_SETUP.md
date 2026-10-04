# Connect your Windows computers

This implementation establishes the incremental collector pipeline and local Claude/Codex timestamp adapters. It does not deploy itself or install a background service on your computers.

## Server deployment

Deploy this repository revision to your Render service. Keep `APP_ENV=production`, `APP_PASSWORD` and the expected public hostname configured. The checked-in free Blueprint still has ephemeral storage. For durable SQLite, attach a Render persistent disk and set `TRACKER_DATA_DIR` to its mount path (for example `/var/data/project-tracker`). This setting relocates the database, scan snapshots, previews, session state and logs together. Merely setting the variable without attaching persistent storage does **not** make storage durable. Back up the old database before changing its location. A PostgreSQL backend is not implemented in this phase.

Log in at your site, open **Settings → Integrations** from the dashboard, and register `YousseF-Desktop`. Copy the token shown once. Register the laptop with a separate ID. Tokens are stored hashed in the database, can be rotated by registering the same ID again, and can be revoked. Collector tokens authorize only heartbeat and metadata ingestion; they cannot read dashboard/debug data or change owner settings.

## On each computer

Install Python 3.11 or newer and Git. Copy this repository to the computer. Copy `collector.config.example.json` to `collector.config.json`, set `workspaces` to the folders you actually use, and keep the deployed HTTPS origin as `server`. Workspaces are scanned up to `max_depth`; nested packages inside an already recognized project are not separate cards. Missing configured folders are reported as source errors.

Use PowerShell to set `COLLECTOR_TOKEN` without typing it into shell history:

```powershell
$collectorSecret = Read-Host 'Collector token' -AsSecureString
$env:COLLECTOR_TOKEN = [System.Net.NetworkCredential]::new('', $collectorSecret).Password
python collector.py --config collector.config.json --dry-run
python collector.py --config collector.config.json --once
python collector.py --config collector.config.json
```

If `python` is not on PATH on this desktop, use the installed executable at `C:\Users\Dell Desktop\AppData\Local\Python\pythoncore-3.14-64\python.exe` with PowerShell's `&` invocation operator.

Dry run discovers metadata but prints only project counts, source statuses and warnings. It sends nothing. `--once` sends a heartbeat and one metadata batch. Continuous mode sends a heartbeat every 30 seconds between scans and scans every five minutes by default. **Sync now** queues a request; the next collector heartbeat triggers a scan. The UI distinguishes requests pending on offline devices from completed ingestion. Previously ingested projects stay visible when devices disappear. Keep the collector process running; Task Scheduler/service installation is a separate step.

## Data and privacy

The payload allowlist consists of project/device paths and names, sanitized remote identity, branch, change/file/TODO counts, language, activity timestamps, commit SHAs/timestamps and hashed session IDs/timestamps. No source-file bodies, README bodies, commit messages, prompts, tool calls, environment values, credential stores or session contents are transmitted. Paths identify projects and can reveal folder names. Default ignores cover credentials, `.env*`, dependencies, build/cache directories and system/browser folders. Add your own `ignore` patterns. Symlink/junction directories are skipped.

Local session adapters first check that `.claude/projects` and `.codex/sessions` actually exist. This desktop has both locations and usable JSONL metadata records. Their formats are best effort, not a guaranteed API. Match by recorded working directory against recognized workspace paths. Only the source, hashed ID and most recent valid timestamp leave the machine. Missing roots are unavailable, not zero sessions. Set `ai_metadata` to `false` to disable, or configure `session_roots` with explicit `claude`/`codex` paths. Processing is capped at 500 files per tool, 20 MB per file and 100 matched sessions per project; this is recent metadata, not a complete historical archive. Task summaries, outcomes, file edits and session duration remain unavailable.

VS Code activity is inferred from file modifications; the collector does not claim the editor was open. GitHub API and Render deployment connectors remain **not configured/not implemented**, rather than claiming connection based on a URL. The next phase should add environment-configured remote adapters with independent error isolation.

## Troubleshooting

Open **Owner diagnostics** or `/api/debug` after logging in. Check last heartbeats, source status, ingestion acceptance/rejection and pending sync requests. HTTP 401 usually means a revoked/incorrect collector token; 400 means schema/timestamp validation failed; a collector network failure means no request reached the server. Check the configured HTTPS origin and workspace roots. Detailed rejection logs intentionally omit raw request values and credentials.

Existing whole-database cloud mirroring is refused once collectors are registered so a push cannot wipe central records. Existing owner tasks/analyses are carried from repository-matched snapshots into the central project key. The server persists accepted batches atomically and does not delete missing projects.

## Validation

`python -m unittest discover -s tests -v` covers repository identity normalization, two devices, retry deduplication, DB reopening, source-body exclusion, authentication rotation, identity upgrades, authenticated HTTP ingestion, owner-only diagnostics and queued synchronization. The first **production** device connection remains pending deployment, persistent storage configuration and a token generated on that server. Do not claim the public dashboard is updated until those steps are verified.
