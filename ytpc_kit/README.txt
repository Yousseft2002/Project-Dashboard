PROJECT TRACKER - SECOND PC SETUP (e.g. YTPC)
=============================================

This folder arrives on your other PC through OneDrive.

1. On the other PC, open OneDrive > ProjectTracker > ytpc-kit
   (wait for OneDrive to finish syncing the folder).
2. Double-click "Install on this PC.cmd".
   It needs Python 3. If Python is missing, the window tells you how to install it.
3. That's it. Every 30 minutes the PC scans its project folders and AI-tool
   history (Claude Code, Codex, Copilot, VS Code) and saves a snapshot to
   OneDrive > ProjectTracker > snapshots. The Project Tracker on your laptop
   picks it up automatically.

What it reads: project folders in Documents, Desktop, your home folder and
python\, git history, and AI chat history. It only reads files and never
changes your projects. Secret files (.env, keys, credentials) are skipped.
Each snapshot includes a short digest of your README and plan docs and the
file list, so the laptop's AI analysis can review projects that only exist
on this PC.

Extra folders: edit %LOCALAPPDATA%\ProjectTrackerScanner\config.json and add
paths to "extra_roots", e.g. ["D:\\Projects"].

Remove: double-click "Uninstall.cmd".
