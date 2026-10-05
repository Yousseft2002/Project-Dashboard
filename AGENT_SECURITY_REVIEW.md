# MVP security review

Scope: Windows Git telemetry and versioned server API. This is an implementation review with automated adversarial checks, not an independent audit or a production-ready certification.

## Boundaries and checks

- Credentials: existing user DPAPI token storage; queue payloads also user DPAPI. Tokens are excluded from diagnostics and owner exports. Rotation/revocation and rejected credentials have integration tests. Bearer credentials remain replayable until revoked; TLS and local protection reduce exposure, not that inherent property.
- Paths: exact approved repository allowlist, traversal/absolute path rejection, containment checks, excluded secret/session/dependency paths, symlink/junction rejection. Git worktrees with external `.git` files are unsupported. Config includes and linked Git config/HEAD/refs are rejected.
- Execution: Git has fixed argument arrays, no shell, hooks/fsmonitor disabled, global/system configuration disabled, optional locks disabled and a timeout. No download, updater, remote command or local IPC interface exists. A hostile repository can still consume resources; limits on Git output and full adversarial object-store analysis remain release hardening work.
- Server trust: fixed approved HTTPS production origin, TLS verification, no credential-forwarding redirects, service/version checks and strict device/write/acknowledgement validation. Tests reject HTML responses and foreign acknowledgements. No certificate pinning.
- API: per-device authentication, identity validation, parameterized SQL, atomic batch validation, max 100 events, 2 MB request ceiling and 60 authenticated requests/minute per process. Device tokens cannot import owner data or execute commands. Rate limiting is not distributed and unauthenticated/pairing abuse needs further hardening.
- Metadata: schema restricts MVP events to Git commits with a SHA, timestamp and redacted short subject. Source bodies and arbitrary event metadata are rejected. Control-character injection is removed, dashboard rendering escapes data. Redaction is best effort, so preview remains important.
- Queue: durable transactions, encrypted payloads, explicit acknowledgements, stable identities, replay deduplication, and concurrent snapshot changes remain dirty. Tests cover offline restart, lost acknowledgement, forged acknowledgement, ciphertext and retry.

## Evidence and release gates

30 tests pass under the normal Windows profile, including real Git fixtures, real local HTTP ingestion, service execution, DPAPI, authorization and transactional validation. Python/JavaScript/PowerShell syntax and whitespace checks are part of release validation. Simulated two-device tests do not establish physical two-device live acceptance.

Unmet production gates: PostgreSQL/durable hosted storage, real two-device live evidence, Windows lifecycle soak testing, installer signing, explicit private-directory ACL hardening, resource bounds for malicious Git output, robust anonymous endpoint rate limiting and an independent review. Do not describe this MVP as production-ready.
