# Project intelligence audit — October 4, 2026

## Current pipeline

`scanner.build_snapshot → data/snapshots/<machine>.json → server.digital_view → projects.build → GET /api/state → state.data.projects → dashboardView`.

Digital projects are file snapshots, not database rows. SQLite stores physical builds, digital overrides, task items, analyses, directives, daily plans and settings. Human edits already win over AI. Statistics are derived in `static/js/model.js`; digital example cards are not hard-coded. Fresh databases do seed three example physical builds.

The checked-in Render Blueprint is a free service without a persistent disk. SQLite and snapshots survive ordinary requests but are not durable across redeploys/instance replacement. This is repository evidence, not verification of the live Render account. The public URL could not be fetched during this audit.

Cloud mode deliberately disables local scanning and Claude CLI operations. A hosted process cannot inspect Windows folders. OneDrive sharing only works between local installations. The existing cloud mirror is a manual, whole-database replacement using APP_PASSWORD, also stored in local SQLite settings. It deletes previous snapshots and can replace owner edits and other devices' data. There is no periodic collector, heartbeat or incremental ingestion route.

## Integrations

Real local implementations: workspace discovery, subprocess Git metadata, checked local Claude/Codex JSONL readers, Copilot/VS Code session readers, Claude CLI analysis, browser screenshots, OneDrive snapshot sharing and manual cloud mirroring. VS Code file activity is not proof the editor was open. Existing session readers retain prompts/digests and must not be reused wholesale for cloud collection.

Not implemented: GitHub API repository/issues/PR/actions synchronization; Render API deployments; authenticated multi-device collectors; persistent normalized event store; owner diagnostics. A GitHub link is not a GitHub connector, and a live URL is not a deployment status.

## Existing endpoints

GET: `/health`, `/api/state`, `/api/analysis`, `/api/scan`, `/api/planner`, `/api/planner/history`, `/api/access`, `/api/repo-image`.

POST: `/api/login`, `/api/logout`, `/api/analyze`, `/api/analyze/stop`, `/api/settings`, `/api/scan`, `/api/sync/kit`, `/api/sync/open`, `/api/project/meta`, `/api/project/open`, `/api/items`, `/api/planner/instruction`, `/api/planner/regenerate`, `/api/planner/tasks`, `/api/planner/pick`, `/api/planner/tasks/<id>/<action>`, `/api/previews`, `/api/project/preview-upload`, `/api/physical`, `/api/physical/<id>/updates`, `/api/physical/<id>/milestones`, `/api/access`, `/api/access/code`, `/api/access/revoke`, `/api/cloud/push`, `/api/mirror`.

PATCH/DELETE: items, physical projects, milestones; DELETE updates and planner directives.

## Implementation sequence

Add durable project identities, per-device observations, hashed collector credentials, source health, deduplicated events and ingestion diagnostics. Merge metadata incrementally; never replace the owner database. Adapt central records into the existing canonical UI/planner model. Add a configurable, read-only metadata collector with explicit ignores and heartbeat/sync requests. Verify two devices, retries, unauthorized requests, restart persistence and unavailable sources. Configure a Render persistent disk before claiming production durability. Add remote connectors and opt-in session imports only after this pipeline is verified. PostgreSQL migration remains a separate storage implementation; SQLite-specific statements must not be presented as PostgreSQL support.
