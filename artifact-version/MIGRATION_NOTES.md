# Project Tracker Artifact migration notes

## Architecture assessment

The existing product is a dependency-free Python 3.11+ application with a custom `ThreadingHTTPServer` backend and a vanilla HTML/CSS/JavaScript frontend. `run.py` starts the server on port 8765; it serves the frontend and JSON API from the same origin. A second, opt-in HTTPS listener on port 8766 serves same-origin frontend and API requests to other devices after login.

The frontend entry point is `static/index.html`, which loads three stylesheets and the ES-module application shell in `static/js/app.js`. That shell loads dashboard, project, physical-build, daily-planner, analytics, settings, chart, component, state, and model modules. The dashboard's portfolio calculations (counts, ranking, filters, sorting, milestones, activity summaries) already run in JavaScript in `static/js/model.js`; charts are rendered as SVG.

The Python API normalizes scanner snapshots, SQLite overrides and items, analysis results, and physical-build records into the view model returned by `GET /api/state`. SQLite (`data/tracker.db`) stores physical projects, progress logs, milestones, project metadata overrides, settings, task/issue items, AI analysis results, and daily planner history/directives. JSON snapshots and previews live under `data/`; the access-code/session state and generated TLS certificate/key are also stored there. The repository checkout inspected for this migration contains no populated `data/` directory to copy; the Artifact uses clearly synthetic examples instead.

The scanner reads local project folders and selected AI-coding-tool session files, and invokes Git to collect repository facts. Analysis and planner language generation invoke the locally installed Claude Code CLI with the user's existing CLI login; analysis is read-only and excludes secret-like files. Preview generation uses a local Edge/Chrome headless browser. The source does not configure a hosted API key or external API endpoint. Windows/OneDrive-related paths are derived from environment variables such as `OneDrive`, `APPDATA`, `LOCALAPPDATA`, and `ProgramFiles`.

Phone access is intentionally a separate security boundary: an opt-in HTTPS listener binds to `0.0.0.0:8766`, limits clients to private-network addresses, checks the Host and request origin, uses a login code with brute-force throttling and an HttpOnly session cookie, and blocks PC-only routes. The unauthenticated original app stays bound to `127.0.0.1:8765`. The Artifact does not reproduce or weaken this authentication; use Claude's sharing/access controls and do not put confidential data into a published Artifact.

## Backend endpoint inventory and migration

`GET /api/state` assembles the canonical project list, planner payload, scans, physical builds, machine/settings metadata, job state, and access context. `GET /api/analysis`, `POST /api/analyze`, and `POST /api/analyze/stop` expose asynchronous analysis/preview/planner jobs. `POST /api/settings`, `/api/sync/kit`, and `/api/sync/open` manage local preferences and machine-to-machine setup. `GET/POST /api/scan` report/start file-system scanning. `/api/project/meta`, `/api/project/open`, `/api/items`, `/api/items/{id}`, `/api/previews`, and `/api/project/preview-upload` edit local projects and their media. `/api/planner`, `/api/planner/history`, `/api/planner/instruction`, `/api/planner/regenerate`, `/api/planner/tasks`, `/api/planner/pick`, `/api/planner/tasks/{id}/{action}`, and `/api/planner/directives/{id}` manage planning. `/api/physical`, `/api/physical/{id}`, `/api/physical/{id}/updates`, `/api/updates/{id}`, `/api/physical/{id}/milestones`, and `/api/milestones/{id}` manage physical builds. `/api/access`, `/api/access/code`, `/api/access/revoke`, `/api/login`, and `/api/logout` manage the opt-in phone listener's access control.

| Existing capability | Classification | Artifact behavior |
|---|---|---|
| Portfolio statistics, filters, sorting, ranking, dates, status/progress summaries, chart calculations | **ARTIFACT NATIVE** | Deterministic browser-side calculations over the in-memory project model. |
| View and edit digital project details, notes, goals, tasks, milestones, blockers, and bugs | **ARTIFACT NATIVE** | Browser-side editing with synthetic starter data; user changes can be exported as JSON. |
| Physical builds, progress logs, costs, hours, milestones, and charts | **ARTIFACT NATIVE** | Browser-side records and derived totals; portable JSON instead of SQLite. |
| Daily task list, status changes, manual task entry, and priority ordering | **ARTIFACT SUBSTITUTE** | Local rules-based shortlist and task tracking; no server-side history or LLM-generated plan. |
| YT dashboard metrics and charts | **ARTIFACT SUBSTITUTE** | N/A until the user imports data; no analytics provider connection or claims of real usage. |
| Preferences, theme, browser persistence, backup/restore | **ARTIFACT SUBSTITUTE** | Best-effort Artifact/browser storage plus explicit JSON export/import; no shared central database. |
| Scan local folders, Git repositories, checklists, and coding-agent sessions | **BACKEND REQUIRED** | The Artifact cannot inspect the host device. User may enter or import summarized project data. |
| Claude Code CLI analysis and AI-generated daily-plan language | **BACKEND REQUIRED** (exact behavior) / **ARTIFACT SUBSTITUTE** | The CLI, its login, file access, and queued jobs are unavailable. Users can ask Claude conversationally to analyze imported information without embedding credentials in the Artifact. |
| Headless screenshots, reading local preview files, image persistence | **BACKEND REQUIRED** (capture) / **ARTIFACT SUBSTITUTE** (display) | No host browser or file server; image URLs can be stored as user data or previews can be omitted. |
| SQLite persistence, multi-PC snapshot synchronization, OneDrive setup kit | **BACKEND REQUIRED** | A published Artifact has no shared app-owned database or filesystem. Portable JSON is the safe replacement. |
| Open a project folder/VS Code, read/write host files, OS integration | **BACKEND REQUIRED** | Not exposed by the Artifact sandbox. |
| Login code, sessions, LAN HTTPS listener, private-address/Host checks | **BACKEND REQUIRED** | These protect the original server. Artifact visibility/access is controlled by Claude's platform sharing settings; app-level server authentication is not copied. |

### Files, data, and deterministic logic

- `tracker/db.py` creates `data/tracker.db` and seeds three physical-build examples on first run. All user edits and planner/analysis history are persisted there.
- `tracker/server.py`, `tracker/scanner.py`, `tracker/analyzer.py`, `tracker/planner.py`, `tracker/previews.py`, and `tracker/security.py` read/write local files, invoke local processes, or host the API and HTTPS access service. These are not bundled into the Artifact.
- `static/js/model.js` already calculates portfolio summaries and ranking in pure JavaScript; those formulas are reproduced for the Artifact's sample/imported dataset rather than calling the Python API.
- `static/js/views/yt.js` defines deterministic aggregation and charting over an optional `yt.apps` payload. No analytics provider or real YT data source is present in the inspected checkout.
- The standalone Artifact contains no host addresses, server calls, credentials, production database, or personal project snapshots. Browser storage is local to the Artifact/browser context; import/export JSON is the portable persistence mechanism.
