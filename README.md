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

Requirements: Python 3.11 or newer, and Edge or Chrome for previews. No
packages to install.
