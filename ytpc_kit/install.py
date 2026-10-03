"""Install the Project Tracker scanner on this PC.

Copies the scanner to %LOCALAPPDATA%\\ProjectTrackerScanner, points it at the synced snapshots folder
next to this kit, registers a Task Scheduler job (every 30 minutes) and runs a first scan.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
TARGET = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ProjectTrackerScanner"
TASK = "Project Tracker Scan"


def main():
    print("Project Tracker scanner setup\n")
    sync_dir = KIT.parent / "snapshots"   # the kit lives in <OneDrive>\ProjectTracker\ytpc-kit
    TARGET.mkdir(parents=True, exist_ok=True)
    for name in ("scanner.py", "scan_and_sync.py"):
        shutil.copy2(KIT / name, TARGET / name)
    cfg_path = TARGET / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    cfg.update(sync_dir=str(sync_dir), machine=cfg.get("machine") or socket.gethostname())
    cfg.setdefault("extra_roots", [])
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"Installed to   {TARGET}")
    print(f"Snapshots go   {sync_dir}")
    print(f"This PC is     {cfg['machine']}")

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else Path(sys.executable)
    cmd = f'"{runner}" "{TARGET / "scan_and_sync.py"}"'
    r = subprocess.run(["schtasks", "/Create", "/TN", TASK, "/SC", "MINUTE", "/MO", "30", "/TR", cmd, "/F"],
                       capture_output=True, text=True)
    print("Scheduled scan  every 30 minutes" if r.returncode == 0 else f"Could not create the scheduled task:\n{r.stderr}")

    print("\nRunning the first scan...")
    r = subprocess.run([sys.executable, str(TARGET / "scan_and_sync.py")])
    log = TARGET / "scan.log"
    if log.exists():
        print(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    print("\nDone." if r.returncode == 0 else "\nThe first scan failed; see scan.log in the install folder.")
    print("To scan extra folders (e.g. D:\\Projects), add them to \"extra_roots\" in", cfg_path)


if __name__ == "__main__":
    main()
