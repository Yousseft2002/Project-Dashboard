# Verification record

Checks run November 1, 2026:

- New server suite: 15 tests passed (`python -m unittest discover -s tests -p test_github_dashboard.py`). GitHub, OAuth, AI responses and ASGI thread dispatch are mocked; no personal repositories or credentials are used by tests. The adapter test checks its authentication boundary without opening a Windows event loop or network sockets.
- New frontend: `node --check github_static/dashboard.js` passed. `node tests/check_github_views.mjs` passed for unauthenticated/configuration state, empty repository selection, populated dashboard, escaped untrusted text, filtering, project details, timeline and notification empty state. These are rendering checks, not a real browser end-to-end test.
- Full retained Python suite with workspace temporary directory: 44 tests ran, 1 failure and 8 errors. Errors involve blocked loopback socket operations, Windows credential protection, and missing optional FastAPI. The workspace-suggestions test also fails because its temporary fake workspace lives inside this Git checkout and discovers the enclosing repository. Legacy implementations/tests were not changed to mask those results.
- The local server starts on 127.0.0.1:8775. HTTP/browser preview requests time out in this environment despite the listener starting; visual layout and live HTTP behavior remain unverified. An already-running older tracker occupies 8765 and was left untouched.
- Live OAuth callback, real selected-repository sync and AI generation require server-side credentials and remain unverified. No credentials were created or stored, no paid service was enabled, and no deployment/push was performed.

Before deployment: configure the OAuth callback and owner ID, select a read-only fine-grained token, verify allowed/denied sign-ins, inspect one real commit, mark a manual work signal, confirm snooze and commit suppression, and check responsive layout in a reachable browser. Production requires HTTPS and private durable storage; existing ephemeral hosting settings alone are insufficient.
