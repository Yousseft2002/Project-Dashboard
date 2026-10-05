# Project Dashboard Agent: Windows MVP

The first milestone replaces repeated folder uploads with approved-repository Git metadata. It is an MVP, not a production-ready release. Hosting remains on Render Free at the owner's request; PostgreSQL is not configured and hosted SQLite data can disappear on redeploy/restart. The local queue survives agent restarts, but acknowledged history is not a cloud backup.

## Install

Update this repository, then run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_collector.ps1 -Agent
```

Choose a friendly device name and exact repository directories. Approve the pairing code in the signed-in production dashboard. Setup shows selected paths and requires confirmation before collecting. The agent then prints a local metadata preview and requires explicit approval before upload and startup installation. Python 3.11+ and Git are required in this milestone.

For an already paired/configured computer:

```powershell
python -m agent preview
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_agent.ps1
python -m agent diagnostics
```

The installer starts a hidden process now and at Windows sign-in, under the same Windows user. It does not run before sign-in. Remove startup with `install_agent.ps1 -Uninstall`; credentials and the queue remain. Re-pair with `collector.py pair` if the server rejects the saved credential, then restart the scheduled task.

## Collection and delivery

Only explicitly configured Git roots are inspected. No workspace discovery occurs in the background. Git is checked every 30 seconds; changed snapshots upload automatically, heartbeat runs every 120 seconds, and reconciliation runs every 15 minutes. Local collection continues during network failure. Delivery retries with exponential backoff up to 15 minutes.

Snapshots contain repository identity, branch, latest 100 commit SHAs/times/redacted subjects, tracked file count, language inferred from extensions, working-tree counts and ahead/behind counts. File contents, patches, environment values, chat bodies and credentials are not uploaded. Names of individual modified files are not uploaded. Commit subjects and workspace paths are metadata that may themselves be sensitive: inspect the preview.

The SQLite WAL queue encrypts snapshot/event payloads using Windows user DPAPI. Stable commit IDs and explicit server acknowledgements handle retries without duplicate activity. Snapshots coalesce to the latest state. A queue limit of 100,000 pending events stops collection with a diagnostic instead of silently discarding events. Diagnostics are in `data/agent/diagnostics.json`; queue data is in `data/agent/queue.sqlite`.

API `/api/agent/v1/` supports registration, heartbeat, project snapshots, Git event batches and device-scoped status. Existing pairing remains compatible. New device IDs and agent IDs are random UUIDs; old paired device IDs remain valid. Dashboard telemetry refreshes every 20 seconds while visible and defers rendering during form edits, open dialogs and selected imports.

## Remaining acceptance work

- Verify actual physical YT-Laptop and YT-Desktop separately; naming this installation YT-Laptop does not prove a second physical device.
- Configure PostgreSQL/durable cloud storage before claiming restart persistence. Free deployment is not that guarantee.
- Validate unattended sign-in/shutdown and long-running delivery on real Windows devices.
- File watchers, VS Code, Claude and Codex adapters are disabled pending the basic Git milestone. AI session stores are excluded as workspaces.
- Tray controls, packaged Python-free EXE installer, signed builds/updates, diagnostic export and hardened local permissions are later milestones.
- Local planner tasks/data use the separate owner import workflow; this agent synchronizes telemetry, not an entire local database.
