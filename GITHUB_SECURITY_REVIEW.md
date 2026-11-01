# GitHub-only security review

## Before changes

The repository's main entry point imported `tracker.server`, with local scanners, editor/session integrations, subprocess-based analysis, collectors, file/folder operations and preview capture. The older ASGI entry point exposed collector and pairing operations and required PostgreSQL. Those capabilities conflict with the requested GitHub-only trust boundary even when some routes are cloud-disabled.

## Implemented boundaries

- Default local and configured ASGI entry points use a separate module without legacy imports. Its explicit routes expose no filesystem browsing, scanning, pairing, collector ingestion or subprocess execution. Only fixed application assets and its own SQLite state file are read locally.
- GitHub sign-in uses random state, browser-bound HttpOnly cookie, PKCE S256, ten-minute expiry and transactional single-use consumption. Immutable owner ID checked before session issuance. OAuth tokens are discarded. Repository data uses a server environment read token and a fixed repository allowlist.
- Random sessions are hashed at rest, expire after twelve hours, and are revocable. Production cookies require HTTPS. Mutations require an exact Origin; all requests require exact configured Host. No CORS grants. Global fixed-window request limits constrain OAuth and authenticated operations.
- GitHub and AI destinations are fixed HTTPS endpoints. Redirects are refused, response sizes and durations bounded, SHAs and repository names validated. Client routes cannot supply arbitrary upstream URLs.
- Frontend uses escaped text and textContent, restrictive CSP, no framing, no remote scripts, no-store responses. API errors and audit events omit messages, tokens, diffs and callback queries. Default HTTP access logging is disabled.
- GitHub summaries require server opt-in and an owner action. Patches are neither sent to AI nor rendered. Prompt injection cannot invoke tools or write application state.
- SQLite contains only hashed sessions, temporary OAuth verifiers, rate buckets and explicit work/snooze timestamps. Production requires an explicit durable data directory. OS access controls and proxy log redaction remain deployment responsibilities.

## Limits and deployment review

Not an external penetration test. Host process/environment compromise exposes the read token. Use expiring fine-grained credentials and least privilege in GitHub itself; application code cannot reduce an overprivileged token. Read tokens require periodic manual rotation. Repo snapshots cache private messages in process. Existing legacy modules/installers remain on disk for preservation, but are not part of the new application; running them independently restores their old behavior. Existing Vercel deployment instructions are historical and do not satisfy the new durable-storage requirement. One process/instance is supported. Upstream endpoint responses are bounded and pagination is disclosed; staleness and reminder inference do not inspect branch contents or local uncommitted work. OAuth callback URL query logging must also be disabled at the hosting proxy.
