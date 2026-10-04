# Project Tracker Artifact

This is an additional, self-contained browser prototype. It does not change or replace the original `python run.py` application.

## Give it to Claude

1. Open `CLAUDE_ARTIFACT_PROMPT.txt` and copy its full contents into a new Claude conversation.
2. Attach `artifact-code.html` to that conversation (or paste the entire file after the prompt).
3. Ask Claude to render the result as an interactive Artifact. The source is plain HTML, CSS, and JavaScript with no packages or external assets; it is not a Python server project.
4. Try the dashboard, project cards, task and milestone controls, Physical builds, theme toggle, and JSON export/import. The four digital projects and three builds included in the source are explicitly synthetic examples.
5. To work with your own records, use **Data & settings → Export JSON** for a backup and **Import JSON** to load a file. Treat that file as sensitive if you put personal or business information in it.

The source file can also be opened directly in a modern browser as a standalone prototype; it needs no local web server. For the Claude version, give Claude the source and prompt above and use the rendered Artifact.

## Saving and sharing data

Edits are kept in browser storage when the Artifact environment permits it. That storage is not a shared database and is not guaranteed to follow you to another device or another viewer. Export your data to JSON and import it on the other device; do not expect edits to synchronize between viewers. Share only with people allowed to see the data, and use Claude's Artifact visibility controls deliberately.

## Scope

See `MIGRATION_NOTES.md` for the source-app audit and the feature-by-feature **ARTIFACT NATIVE / ARTIFACT SUBSTITUTE / BACKEND REQUIRED** classification. The Artifact has no network calls, local-address dependencies, API keys, backend, or production dataset. Its analytics page remains N/A unless adapted with data you are authorized to use.
