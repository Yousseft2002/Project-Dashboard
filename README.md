# Project Tracker

Personal command center for every project Youssef is building, digital and physical.

**Open it:** double-click **Project Tracker** on the desktop. If it's already
running, the shortcut just opens the browser tab at http://127.0.0.1:8765.

## The dashboard

1. **Portfolio Overview**: overall completion ring, clickable stat tiles
   (active, in development, almost done, blocked, completed, open, done and
   high-priority tasks), project-status donut, lifecycle-stage columns, task
   completion per project, and project types.
2. **Focus panels**: *Work on next* (ranked by project priority, in-progress
   work and nearness to done), *Needs attention* (blockers, things only you
   can do, repo risks), *Almost finished* and *Upcoming milestones*.
3. **Digital projects**: a card per project with a live preview, progress
   ring, lifecycle stepper, task count, health, priority and status. Search,
   filter by status or type, sort, and switch between grid and list view.
4. **Activity, recent work and physical builds.**

Click a card for the **project page**: preview, links (GitHub, live site,
Open in VS Code, folder), dates, lifecycle, description, goals, notes, a task
board (in progress / up next / completed), milestones, blockers and bugs, AI
insights, activity and code stats. **Edit details** sets type, priority,
status, stage, progress, target date, description and URLs. Leave a field on
"Auto" to use the AI or scan value.

The lifecycle is **Idea → Planning → Design → Development → Testing →
Deployment → Maintenance**.

## Where the data comes from

| Source | What it gives |
|---|---|
| Scan (Rescan, top right) | Project folders, git, lines of code, docs, `- [ ]` checklists in plan docs, Claude Code / Codex / Copilot / VS Code sessions |
| AI analysis (button on the dashboard or a project) | Type, stage, progress, priority, health, description, goals, tasks, milestones, blockers, bugs, needs from you, next steps, optimizations, risks, launch checklist |
| You | Anything on the project page. Your values always win. Tasks you edit or delete stay that way when the AI re-analyzes. |
| Previews | A screenshot from the project's live URL, its preview URL (e.g. `http://localhost:3000` while a dev server runs), or a local `index.html`, taken with headless Edge. You can also upload an image. |

## Project data model

Every project is normalized by `tracker/projects.py` into one shape, so the UI
never depends on where a field came from:

`id, name, oneLiner, description, type, status, phase, phaseProgress, progress,
priority, health, previewImage, previewDevice, liveUrl, previewUrl, githubUrl,
technologies, goals, notes, tasks[], milestones[], blockers[], bugs[],
taskCounts, createdAt, updatedAt, targetDate, sources{field: you|ai|estimate|scan},
ai{…}, facts{…}`

All dashboard statistics are computed from this list in `static/js/model.js`.

## Files

- `tracker/`: `server.py` (API and background jobs), `scanner.py`,
  `analyzer.py` (Claude headless), `previews.py` (screenshots), `projects.py`
  (data model) and `db.py` (SQLite).
- `static/js/`: `app.js` (routing and actions), `model.js` (derived stats),
  `components.js`, `charts.js`, `icons.js` and `views/`.
- `data/`: your database, scan snapshots and preview images. Everything stays
  on this PC.

Requirements: Python 3.11 or newer, and Edge or Chrome for previews. The app
uses only the Python standard library; no packages to install.

## Render deployment (public testing)

The optional `render.yaml` Blueprint config deploys the Python web service from
the `main` branch. It uses `pip install -r requirements.txt` and `python
run.py`; Render's `PORT` is used automatically, and the service binds to
`0.0.0.0`. The frontend and API remain same-origin. Render terminates HTTPS;
the self-signed LAN listener is not started in production.

Before exposing the service, set `APP_PASSWORD` in the Render service's
environment variables to a unique, randomly generated secret of at least 16
characters. It is deliberately not stored in this repository or Blueprint.
`APP_ENV=production` enables the password login, secure session cookie,
request host validation against Render's `RENDER_EXTERNAL_HOSTNAME`, HTTPS
security header, and restrictions on local-only operations. Do not use real
confidential, employee, patient, manufacturing, or GMP records for this test
deployment.

### Local files and cloud limitations

The app stores SQLite data, scan snapshots, previews, login sessions, and logs
in `data/`. Render's default filesystem is ephemeral: these records can
disappear after a restart, redeploy, or instance replacement. No persistent
disk or external database is configured. Treat this deployment as disposable
testing; export/backup anything you intentionally want to keep, and do not
assume an export/backup flow covers every internal record.

The cloud instance cannot scan your computer's folders, use your local Claude
Code CLI or its login, capture local browser previews, open VS Code/folders,
or use OneDrive sync. Project folder scanning and AI plan/analyze operations
are disabled where possible; the normal browser UI, same-origin API, physical
builds, and manually entered project/task data remain available after login.
Data entered in the Render instance belongs to its temporary SQLite database
and should be considered disposable.

### Deploy from GitHub

1. Push/merge this configuration to the `main` branch in GitHub.
2. In Render, choose **New → Blueprint**, connect `Yousseft2002/Project-Dashboard`,
   select `main`, and apply `render.yaml` (or use **New → Web Service** and set
   the same build/start commands and `/health` health check).
3. Set `APP_PASSWORD` in the service's Environment page. Use a password
   manager to generate it; do not put the value in `render.yaml`, GitHub, or
   chat. Keep `APP_ENV=production`.
4. Deploy. Render creates the public `https://<service-name>.onrender.com/`
   URL and automatically redeploys when new commits arrive on `main`.

The public URL is assigned by Render when the service is created; this
repository change does not itself create a Render service or know that URL.
