# Transfer the saved local dashboard to production

Collector synchronization sends repository metadata. It does not migrate owner tasks, saved analyses, planner history, or physical builds. Use the separate owner-authorized dashboard transfer to bring these saved records across.

1. Open the updated local dashboard at `http://127.0.0.1:8765/#/integrations`.
2. Choose **Download dashboard export** under **Transfer saved dashboard data**.
3. Sign in at `https://project-dashboard-0d02.onrender.com/#/integrations`.
4. Select the exported JSON file and choose **Import saved dashboard**.
5. Refresh Dashboard and compare project/task counts and today's plan.

Transfer includes saved project metadata, tasks, goals, milestones, blockers, bugs, owner overrides, saved analyses, instructions, daily plans/history, physical builds and existing PNG preview screenshots. It does not scan folders, run an AI analysis, read AI session storage, or export settings, passwords, collector credentials, or chat bodies.

The import matches existing collector projects by repository identity, or an exact folder path for a repository without a remote. It remaps item and planner references in one database transaction. Reimporting the same source skips records already imported and preserves subsequent owner edits. Existing production owner overrides and daily plans remain authoritative; an empty automatically created plan can receive the imported plan.

On Render Free, SQLite storage remains ephemeral. Export files provide a recoverable copy of the saved dashboard state, but this feature does not provide persistent hosting storage. A service restart or deployment can still require reimporting data and pairing collectors again.

Validation on October 4, 2026: an isolated cloud instance with an existing collector imported the current saved local state and reproduced 9 visible projects, 84 open tasks, 3 physical builds, 5 tasks for today and 4 preview screenshots. The existing collector credential remained valid; repeating the import added no duplicate records. Automated tests cover ID collisions, dependency remapping, owner authorization, excluded secrets/session data, and rollback on malformed references.
