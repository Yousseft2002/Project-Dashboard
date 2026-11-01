# GitHub-first Project Tracker

The default `python run.py` and ASGI `tracker.github_dashboard:app` now run the GitHub-only application. No legacy scanner, collector, AI CLI, preview capture, phone listener, or local workspace module is imported. Old implementations remain for migration and regression tests; do not run their entry points for this mode. Repository source inspection during development is distinct from application data collection.

## Connect securely

1. Create a GitHub OAuth App. Set homepage to your `APP_ORIGIN` and callback to `APP_ORIGIN/auth/callback`. Sign-in requests no extra OAuth scopes; it uses public identity only. Set `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, and `GITHUB_OWNER_ID` (your immutable numeric account ID) in the server environment. Other GitHub users are rejected.
2. Create an expiring **fine-grained personal access token**, selecting only repositories you want to track. Grant **Contents: read**, **Issues: read**, **Pull requests: read**, and the required Metadata read permission. Never grant writes. Configure it as `GITHUB_READ_TOKEN` on the server. OAuth identity tokens are discarded after verifying the owner; this separate repository token never reaches the browser.
3. Set `GITHUB_REPOSITORIES` to comma-separated `owner/name` values, up to 30. This is the application allowlist; the token selection is an independent access boundary. Missing issue/PR permissions produce explicit warnings. No repository discovery outside this list occurs.
4. Set environment variables from `.env.example`; the application deliberately does **not** automatically load `.env`. Run `python run.py --no-browser` with Python 3.12+. The GitHub-only server needs no third-party packages. Open the exact `APP_ORIGIN`. If changing ports, update both `PORT` and `APP_ORIGIN` and the OAuth callback.
5. For hosting, set `APP_ENV=production`, an HTTPS `APP_ORIGIN`, and `TRACKER_DATA_DIR` on private durable storage. Render's default ephemeral disk and Vercel's serverless filesystem are **not supported for durable sessions/work signals**. No database service is needed for a single instance with a private disk. Scale to one process/instance; horizontally distributed deployments need a shared store first. Configure the reverse proxy to preserve the configured Host. Do not enable query-string access logs on `/auth/callback`.

Use your hosting secret manager. Never paste tokens into chat, GitHub issues, browser storage, repository metadata, or frontend configuration. Rotate/revoke the read token in GitHub on exposure or expiry. Sessions last 12 hours; sign-out revokes the current session. Removing the SQLite sessions table contents revokes all sessions. Protect the data directory with owner-only OS access and encrypted disk/backups.

## Data and UI

Project descriptions, names, visibility and language come from repository metadata. Milestones and next steps come from GitHub milestones and open issues/PRs. Recent history fetches 30 default-branch commits per repo, 30 issues/PRs, 30 milestones, and 100 branch names. Commit detail fetches the first changed-files page and reports that boundary. Counts and “today” are explicitly bounded to fetched history; today uses `APP_TIMEZONE` (default America/New_York). Health is a transparent recency heuristic, never an invented completion percentage. Repository snapshots are cached in process for five minutes; refresh reuses a fresh cache. Errors are per repository; unavailable repositories do not disappear silently.

No raw patches, repository source files, or tokens are returned to the client. Private commit messages and filenames necessarily appear for the authenticated owner. Browser rendering escapes GitHub text; AI output uses textContent. No remote fonts, trackers, screenshots, analytics, third-party scripts, or automatic AI requests.

## Reminders

“I worked on this today” records only a timestamp and selected repository ID in the application's SQLite store. It is auxiliary reminder state, never project progress data. After one hour without a newer fetched default-branch commit, the notification center shows a nudge with the evidence and branch limitation. Snooze lasts 24 hours. Signals expire after 24 hours; a newer commit suppresses the nudge. Work signals do not claim knowledge of local files. No commit is made by this application; the link opens GitHub for the owner to review their normal workflow.

Checks happen on load and every five minutes while the app is visible. There is no background scheduler, push, email, or closed-browser notification delivery. This is deliberate for a private single-process app without paid infrastructure. Optional unattended delivery would require a separately authenticated scheduler and an explicit notification destination; it is not silently configured.

## Optional AI briefings

Default: disabled. Set `AI_SUMMARIES_ENABLED=true` and `OPENAI_API_KEY` to enable an owner-triggered briefing. This can incur API charges. The confirmation text beside the button discloses that the latest five commit messages and up to 50 changed-file names/counts per commit are sent to OpenAI. No patches are sent. The model is configurable (`OPENAI_MODEL`). AI receives no tools and is instructed to treat GitHub content as untrusted, cite commit SHAs, and separate inference from facts. Output remains advisory and never writes project metadata. Leave disabled for zero AI infrastructure cost.

## Verification

Run `python -m unittest discover -s tests -p test_github_dashboard.py` and `node tests/check_github_views.mjs`. Existing legacy tests remain intact and may need their original optional dependencies. The dedicated 15-test server suite covers auth boundaries, PKCE/state replay, owner rejection and success, logout, CSRF/Host checks, token and patch non-disclosure, legacy route isolation, allowlists, malformed input, partial upstream failures, empty repos, production storage requirements, reminders, AI opt-in and ASGI authentication. Actual GitHub login and private-repo sync require your server credentials and should be smoke-tested before hosting. See VERIFICATION_GITHUB.md for environment limits and the retained-suite results.

References: [GitHub OAuth flow and PKCE](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps), [fine-grained token permissions](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens).
