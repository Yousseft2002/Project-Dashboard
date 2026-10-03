# Project Tracker — build plan

Personal dashboard for every project Youssef runs: physical builds (drone, car,
3D printing) and digital apps/sites. Runs locally on the laptop, opens in the
browser at http://127.0.0.1:8765, stores everything in `data/` (SQLite + JSON).
Nothing leaves the machine except the AI-analysis step in Phase 2, which goes
through your own Claude Code login.

Stack: Python 3 standard library only (no venv, no pip installs), vanilla
HTML/CSS/JS front end. Bound to 127.0.0.1 only.

## Phase 1: Foundation (built)
- Local server, SQLite store, desktop shortcut.
- **Physical projects**: create, edit and delete projects; log progress updates
  (% complete, notes, hours, cost); milestone checklist; budget vs spent. The
  drone, car and 3D-printing projects are seeded.
- **Digital scanner** (`tracker/scanner.py`) reads, read-only:
  - project folders in Documents, Desktop, home and `python\` (git history,
    uncommitted changes, languages, lines of code, TODO count, stack, plan docs)
  - Claude Code sessions (`~/.claude/projects`)
  - Codex threads (`~/.codex/sessions`, `session_index.jsonl`)
  - Copilot agent sessions (`~/.copilot/session-state`)
  - VS Code / Copilot Chat sessions (`workspaceStorage/*/chatSessions`)
  It maps every session to its project folder and writes
  `data/snapshots/<COMPUTER>.json`.
- **Digital dashboard**: activity over 30 days broken out by source, git panel,
  AI-tool usage, recent prompts, plus signals that are plain facts (uncommitted
  work, stalled projects). You can rename, hide or merge projects.
- YT Dashboard tab was a placeholder here; see Phase 4.

## Phase 2: AI analysis (built)
- "Analyze" button per project, plus "Analyze all".
- Runs the Claude Code CLI that the VS Code extension bundles, in headless mode
  (`claude -p`), inside the project folder with read-only tools (Read/Glob/Grep).
  It uses your existing Claude login, so no API key is needed.
- Returns structured JSON: production phase (Idea → Prototype → MVP → Beta →
  Launch-ready → Live), health score, what's needed from you, next steps,
  suggested optimizations, risks and performance notes.
- Results are cached with a timestamp and diffed against the last run.
- Implementation: `tracker/analyzer.py` (prompt, schema, CLI call). The server runs one job at a
  time and you can stop it. Runs use `--no-session-persistence`, so they don't count as AI sessions.
  The analyzer is barred from reading secret files (.env, keys, credentials, databases).

## Dashboard redesign (built 2026-10-03)
- One canonical project model (`tracker/projects.py`) that merges scan, AI and owner edits. Stats are
  derived in `static/js/model.js`.
- 7-stage lifecycle: Idea → Planning → Design → Development → Testing → Deployment → Maintenance.
  Older analyses are mapped onto it.
- Portfolio Overview, focus panels, project cards with live previews, grid/list views, filters and sorting.
- Project page with a task board, milestones, blockers and bugs, goals, notes and AI insights.
- Items table: AI tasks are synced, but anything the owner edits or dismisses sticks. Doc checklists are
  shown read-only.
- Previews: headless Edge screenshots from the preview URL, live URL or local index.html, plus uploads.

## Phase 3: Home PC (YTPC)
- Copy `scanner_portable.py` to YTPC. Set it to run on a schedule there (Task
  Scheduler) and write its snapshot to a synced folder (default
  `OneDrive\ProjectTracker\snapshots`).
- The laptop merges every machine's snapshot. Projects that exist on both
  machines are matched by git remote or folder name.

## Phase 4: YT Dashboard (layout built 2026-10-03, no data connected yet)
- Implemented in `static/js/views/yt.js`: daily visitors, visitors per hour, revenue, spend, time on site,
  conversion funnel, reviews and ratings, devices and countries, top pages, traffic sources. Filter by app and
  7/30/90 days; every chart has tooltips and a table view.
- **No demo data.** Anything without real data shows "N/A". The view reads `state.data.yt.apps` (shape documented
  at the top of `yt.js`); the server doesn't provide it yet, so everything is N/A today.
- **Why it's all N/A:** none of the apps are launched yet, so there is no traffic to measure. This is expected, not
  a bug. Numbers will only appear after launch and once a real source is connected.
- Open question: where Deep End's real numbers come from. GitHub's traffic API only reports views of the repo
  page, not visits to the Pages site, so it can't measure players. Real options: App Store Connect / Play
  Console after launch, or privacy-friendly analytics (which Deep End's privacy policy currently rules out).

## Daily Planner (built 2026-10-03)
An AI chief of staff on the dashboard that answers "What should I work on today?".
- **Pipeline:** `tracker/planner.py` scores every open task deterministically first (directives, blocking others,
  deadlines, project and task priority, idle time, impact, effort, readiness, carry-over, your manual nudges). The
  top ~14 candidates go to Claude (headless CLI), which picks 3-7, writes the reasons and the Today's Focus text. If
  the model is unavailable the rules-based plan is used and a warning is shown. The model can never invent tasks.
- **Directives, stored separately** (`directives` table), never rewrite project priorities. Written in plain English
  in the AI context box; kinds: focus, pause, avoid today, deadline, time limit, focus area, blocker, completed,
  note, release. They persist across days until their milestone/date passes or you end them.
- **Tasks:** `plan_days` / `plan_tasks` tables. Controls: start, complete, accept, skip (with reason), move to
  tomorrow, change priority, reorder, add manually, add from the queue, regenerate, "why this?" score breakdown.
  Skips, reorders and priority changes feed back into later scoring (`task_bias`).
- **History:** `#/history`, planned vs completed chart plus a card per day (focus, directives, tasks).
- **QR playbook:** a QR directive on MaterialOS expands to the 10 owner-defined steps (`QR_PLAYBOOK`), added as
  chained project items (`depends_on`) without touching existing tasks.
- **Files:** `tracker/planner.py`, planner routes in `tracker/server.py`, `static/js/views/planner.js`,
  `static/planner.css`.
- **Limits:** physical projects are not planner candidates yet; checklist tasks parsed from docs without an id are
  ignored; Python changes need a server restart.

Each phase stops for your "go" before the next one starts.

## Phone access and security (built 2026-10-03)
- **Off by default.** Settings > Phone access turns on an HTTPS listener on port 8766 (self-signed cert made with
  OpenSSL). The PC's own app stays on http://127.0.0.1:8765 with no login.
- **Login:** a 12-character access code (shown in Settings on the PC), session cookie (HttpOnly, SameSite=Strict,
  Secure), 5 wrong codes per IP locks for 15 min. Only private-network IPs and an allowed Host header are accepted.
- **Hardening:** CSP and security headers, same-origin checks (Origin / Sec-Fetch-Site), 20 MB body cap, static
  file allowlist, PC-only routes (settings, sync, open folder, access), http/https-only URL fields, errors logged
  to `data/server.log` instead of shown.
- **Verified:** login, lockout, 401 for signed-out calls, PC-only routes blocked from the phone, bad Host and
  cross-origin requests rejected, TLS on the LAN port.
- **Known limits / to do later:** phone-width layout not yet checked on a real phone (planner cards and the hero may
  need tuning); the access code is stored in plaintext in `data/access.json` so the PC can show it; the browser will
  warn about the self-signed cert (compare the fingerprint in Settings); Windows may prompt to allow Python on
  Private networks; HEAD requests return 501.
- **Files:** `tracker/security.py`, `tracker/server.py`, `static/login.*`, `static/access.css`.
