@echo off
schtasks /Delete /TN "Project Tracker Scan" /F
rmdir /s /q "%LOCALAPPDATA%\ProjectTrackerScanner"
echo Project Tracker scanner removed from this PC. Snapshots already synced are left in place.
pause
