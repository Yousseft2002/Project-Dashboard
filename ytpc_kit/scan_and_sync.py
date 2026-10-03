"""Project Tracker scanner for a second PC (e.g. YTPC).

Scans this PC's project folders and AI-tool history (read-only) and writes a snapshot into the synced
folder that the main Project Tracker reads. Installed by install.py; run every 30 minutes by Task Scheduler.
"""
import json
import socket
import sys
import traceback
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import scanner  # noqa: E402  (copied next to this file by the installer)


def main() -> int:
    cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    sync_dir = Path(cfg["sync_dir"])
    sync_dir.mkdir(parents=True, exist_ok=True)
    roots = scanner.default_roots() + [Path(r) for r in cfg.get("extra_roots", [])]
    snap = scanner.build_snapshot(roots=roots, cache_path=HERE / "scan_cache.json",
                                  machine=cfg.get("machine") or socket.gethostname(), include_digest=True)
    out = sync_dir / f"{snap['machine']}.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snap), encoding="utf-8")
    tmp.replace(out)
    log(f"wrote {out} ({len(snap['projects'])} projects, {snap['scan_seconds']}s)")
    return 0


def log(msg: str):
    with open(HERE / "scan.log", "a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log("FAILED\n" + traceback.format_exc())
        sys.exit(1)
