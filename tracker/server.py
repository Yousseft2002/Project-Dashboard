"""HTTP server: JSON API + static front end.

Two listeners share one Handler: 127.0.0.1 (the PC, no login) and, only when switched on, an HTTPS listener on the
LAN for a phone (login code + session cookie required). See tracker/security.py."""
from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import mimetypes
import sqlite3
import re
import shutil
import socket
import threading
import traceback
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from collections import deque

from . import analyzer, planner, previews, projects, scanner, security
from .db import DB
from .central import CentralStore

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
DATA = Path(os.environ.get("TRACKER_DATA_DIR", str(ROOT / "data")))
SNAPSHOTS = DATA / "snapshots"

db = DB(DATA / "tracker.db")
central = CentralStore(db)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
_ctx = threading.local()


def is_remote() -> bool:
    """True while handling a request that arrived on the phone (LAN) listener."""
    return getattr(_ctx, "remote", False)


def is_cloud() -> bool:
    return getattr(_ctx, "cloud", False)


LOCAL_MACHINE = socket.gethostname()
KIT_SRC = ROOT / "ytpc_kit"


def default_sync_dir() -> str:
    one = os.environ.get("OneDrive") or str(Path.home() / "OneDrive")
    return str(Path(one) / "ProjectTracker") if Path(one).is_dir() else ""


def sync_dir() -> Path | None:
    d = db.get_setting("sync_dir", None)
    d = default_sync_dir() if d is None else d
    return Path(d) if d else None
scan_state = {"running": False, "message": "", "error": None, "finished_at": None}
scan_lock = threading.Lock()


# ---------------------------------------------------------------- scanning

def run_scan():
    def progress(msg):
        scan_state["message"] = msg
    try:
        snap = scanner.build_snapshot(cache_path=DATA / "scan_cache.json", progress=progress)
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        tmp = SNAPSHOTS / f"{snap['machine']}.json.tmp"
        tmp.write_text(json.dumps(snap), encoding="utf-8")
        tmp.replace(SNAPSHOTS / f"{snap['machine']}.json")
        scan_state.update(error=None, message=f"Scanned {len(snap['projects'])} projects in {snap['scan_seconds']}s")
        enqueue_previews(missing_only=True)
    except Exception as e:  # surface the failure in the UI instead of dying silently
        traceback.print_exc()
        scan_state.update(error=str(e), message="Scan failed")
    finally:
        scan_state.update(running=False, finished_at=datetime.now(timezone.utc).isoformat())


def start_scan() -> bool:
    with scan_lock:
        if scan_state["running"]:
            return False
        scan_state.update(running=True, message="Starting scan", error=None)
    threading.Thread(target=run_scan, daemon=True).start()
    return True


# ---------------------------------------------------------------- AI analysis queue

jobs: dict[str, dict] = {}          # project key -> {status, message, queued_at, started_at, error}
queue: deque[str] = deque()
queue_cv = threading.Condition()
current = {"key": None, "proc": None, "stopped": False}


def enqueue(keys: list[str]) -> int:
    added = 0
    with queue_cv:
        for k in keys:
            if k in queue or current["key"] == k:
                continue
            queue.append(k)
            jobs[k] = {"status": "queued", "message": "Waiting", "queued_at": datetime.now(timezone.utc).isoformat()}
            added += 1
        queue_cv.notify()
    return added


def stop_analysis():
    with queue_cv:
        for k in queue:
            jobs.pop(k, None)
        queue.clear()
        proc = current.get("proc")
        current["stopped"] = True
    if proc and proc.poll() is None:
        proc.kill()


def analysis_worker():
    while True:
        with queue_cv:
            while not queue:
                queue_cv.wait()
            key = queue.popleft()
            current["key"] = key
            current["stopped"] = False
        job = jobs.setdefault(key, {})
        job.update(status="running", message="Preparing", started_at=datetime.now(timezone.utc).isoformat(), error=None)
        try:
            view = digital_view()
            p = next((x for x in view["projects"] if x["key"] == key), None)
            if p is None:
                raise RuntimeError("Project not found (hidden or merged)")
            model = db.get_setting("model", "sonnet")
            extra = [m["path"] for m in p.get("merged_from", []) if m.get("path")]
            out = analyzer.analyze(p, model, on_progress=lambda m: job.update(message=m),
                                   on_proc=lambda pr: current.update(proc=pr), extra_dirs=extra)
            db.save_analysis(key, out["result"], out["meta"])
            jobs.pop(key, None)
        except Exception as e:  # keep the worker alive; show the error on the card
            if current["stopped"]:
                jobs.pop(key, None)  # the user pressed Stop; not an error
            else:
                traceback.print_exc()
                job.update(status="error", message="Failed", error=str(e)[:400])
                if re.search(r"(session|usage|rate) limit", str(e), re.I):
                    # Out of Claude quota: don't burn through the rest of the queue; show why instead.
                    with queue_cv:
                        for k in queue:
                            jobs[k] = {"status": "error", "message": "Skipped", "error": "Skipped: " + str(e)[:300]}
                        queue.clear()
        finally:
            current.update(key=None, proc=None)


threading.Thread(target=analysis_worker, daemon=True).start()


# ---------------------------------------------------------------- preview screenshots

preview_jobs: dict[str, dict] = {}   # key -> {status: queued|running|error, error}
preview_queue: deque[str] = deque()
preview_cv = threading.Condition()
preview_failed: set[str] = set()     # keys whose sources failed; skipped by automatic runs


def _raw_projects() -> dict[str, dict]:
    return {p["key"]: p for p in digital_view()["projects"]}


def enqueue_previews(keys: list[str] | None = None, missing_only: bool = False) -> int:
    raws = _raw_projects()
    overrides = db.overrides()
    if keys is None:
        keys = []
        for k, raw in raws.items():
            o = overrides.get(k, {})
            has_source = raw.get("preview_sources") or o.get("live_url") or o.get("preview_url")
            if not has_source or o.get("preview_image"):
                continue
            if missing_only and (previews.preview_path(k).exists() or k in preview_failed):
                continue
            keys.append(k)
    added = 0
    with preview_cv:
        for k in keys:
            if k in preview_queue or preview_jobs.get(k, {}).get("status") == "running":
                continue
            preview_queue.append(k)
            preview_jobs[k] = {"status": "queued", "error": None}
            added += 1
        preview_cv.notify()
    return added


def preview_worker():
    while True:
        with preview_cv:
            while not preview_queue:
                preview_cv.wait()
            key = preview_queue.popleft()
        job = preview_jobs.setdefault(key, {})
        job.update(status="running", error=None)
        try:
            raw = _raw_projects().get(key)
            if raw is None:
                raise RuntimeError("Project not found")
            o = db.overrides().get(key, {})
            built = projects.build(raw, o, [])
            previews.capture(key, preview_url=o.get("preview_url"), live_url=o.get("live_url"),
                             local_sources=raw.get("preview_sources") or [], phone=built["previewDevice"] == "phone")
            preview_jobs.pop(key, None)
            preview_failed.discard(key)
        except Exception as e:
            preview_failed.add(key)
            job.update(status="error", error=str(e)[:300])


threading.Thread(target=preview_worker, daemon=True).start()


# ---------------------------------------------------------------- daily planner job

planner_job = {"status": "idle", "message": "", "error": None, "reply": None, "warning": None, "what": None}
planner_lock = threading.Lock()


def _planner_projects() -> list[dict]:
    return project_list(digital_view())


def run_planner_job(what: str, text: str = ""):
    """Background job: [parse the instruction and apply it] then regenerate today's plan with the AI."""
    model = db.get_setting("model", "sonnet")
    try:
        projs = _planner_projects()
        reply = None
        if what == "instruction":
            planner_job.update(message="Reading your instruction")
            parsed = planner.parse_directive(db, projs, text, model)
            res = planner.apply_directives(db, projs, text, parsed)
            reply = res["reply"] or "Got it."
            if res["unmatched"]:
                reply += " I couldn't find a project called " + ", ".join(res["unmatched"]) + " in the tracker, so I saved that as a general note."
            if res["tasks_added"]:
                n = res["tasks_added"]
                reply += f" Added {n} step{'s' if n != 1 else ''} to the project; your existing tasks are untouched."
            projs = _planner_projects()
        out = planner.generate(db, projs, planner.today(), model, use_llm=True,
                               progress=lambda m: planner_job.update(message=m))
        planner_job.update(status="idle", message="", error=None, reply=reply, warning=out.get("warning"))
    except Exception as e:
        traceback.print_exc()
        planner_job.update(status="error", message="Failed", error=str(e)[:400])
    finally:
        if planner_job["status"] == "running":
            planner_job["status"] = "idle"


def start_planner_job(what: str, text: str = "") -> bool:
    with planner_lock:
        if planner_job["status"] == "running":
            return False
        planner_job.update(status="running", message="Starting", error=None, reply=None, warning=None, what=what)
    threading.Thread(target=run_planner_job, args=(what, text), daemon=True).start()
    return True


def analysis_status() -> dict:
    return {"jobs": jobs, "queue": list(queue), "current": current["key"],
            "previews": {k: v for k, v in preview_jobs.items()}, "planner": planner_job}


def load_snapshots() -> list[dict]:
    """This PC's snapshot from data/, plus other PCs' snapshots from the synced folder (newest wins)."""
    files = [(fp, "local") for fp in sorted(SNAPSHOTS.glob("*.json"))]
    sd = sync_dir()
    if sd and (sd / "snapshots").is_dir():
        files += [(fp, "synced") for fp in sorted((sd / "snapshots").glob("*.json"))]
    best: dict[str, dict] = {}
    for fp, source in files:
        try:
            snap = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        m = snap.get("machine") or fp.stem
        if m == LOCAL_MACHINE and source == "synced":
            continue  # this PC's own data/ snapshot is authoritative
        snap["_source"] = source
        if m not in best or snap.get("scanned_at", "") > best[m].get("scanned_at", ""):
            best[m] = snap
    from .dashboard_transfer import saved_snapshots
    for snap in saved_snapshots(db):
        snap['_source'] = 'owner import'
        m = snap['machine']
        if m not in best or snap.get('scanned_at', '') > best[m].get('scanned_at', ''):
            best[m] = snap
    return sorted(best.values(), key=lambda s: (s["machine"] != LOCAL_MACHINE, s["machine"]))


# ---------------------------------------------------------------- digital view

def _days_since(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).days


def _identity(p: dict) -> str | None:
    remote = ((p.get("git") or {}).get("remote") or "").lower().rstrip("/")
    if remote:
        return "remote:" + re.sub(r"\.git$", "", re.sub(r"^(https?://|git@)", "", remote).replace(":", "/"))
    first = (p.get("git") or {}).get("first_commit")
    if first and p.get("kind") == "folder":
        return f"root:{p['name'].lower()}:{first}"
    return None


def _central_target(raw, collected):
    identity = _identity(raw)
    if identity:
        for live in collected:
            if _identity(live) == identity: return live['key']
    # An unremoted project can be matched to its exact observed folder, never
    # merely its display name. This handles existing local-only repositories.
    if not (raw.get('git') or {}).get('remote') and raw.get('path'):
        path = raw['path'].replace('\\', '/').rstrip('/').lower()
        for live in collected:
            if not (live.get('git') or {}).get('remote') and str(live.get('path') or '').replace('\\', '/').rstrip('/').lower() == path:
                return live['key']
    return None


def same_project_across_machines(projects: dict[str, dict]) -> dict[str, str]:
    groups: dict[str, list[str]] = {}
    for key, p in projects.items():
        ident = _identity(p)
        if ident:
            groups.setdefault(ident, []).append(key)
    out = {}
    for keys in groups.values():
        if len({projects[k]["machine"] for k in keys}) < 2:
            continue
        keys.sort(key=lambda k: (projects[k]["machine"] != LOCAL_MACHINE, projects[k]["machine"]))
        for k in keys[1:]:
            if projects[k]["machine"] != projects[keys[0]]["machine"]:
                out[k] = keys[0]
    return out


def _merge(target: dict, src: dict):
    for tool, t in (src.get("ai_tools") or {}).items():
        cur = target["ai_tools"].setdefault(tool, {"sessions": 0, "sessions_30d": 0, "turns": 0, "last": None})
        for k in ("sessions", "sessions_30d", "turns"):
            cur[k] += t.get(k, 0)
        cur["last"] = max(filter(None, [cur["last"], t.get("last")]), default=None)
    for day, counts in (src.get("activity") or {}).items():
        dst = target["activity"].setdefault(day, {})
        for k, v in counts.items():
            dst[k] = dst.get(k, 0) + v
    target["recent_sessions"] = sorted(target["recent_sessions"] + src.get("recent_sessions", []),
                                       key=lambda s: s.get("end") or "", reverse=True)[:8]
    target["recent_prompts"] = (target["recent_prompts"] + src.get("recent_prompts", []))[:10]
    target["last_activity"] = max(filter(None, [target.get("last_activity"), src.get("last_activity")]), default=None)
    target["ai_last"] = max(filter(None, [target.get("ai_last"), src.get("ai_last")]), default=None)
    target["machines"] = list(dict.fromkeys(target.get("machines", []) + src.get("machines", [])))
    if not target.get("path") and src.get("digest") and not target.get("digest"):
        target["digest"] = src["digest"]
    target.setdefault("merged_from", []).append({"key": src["key"], "name": src["name"], "machine": src.get("machine"),
                                                 "path": src.get("path")})


def digital_view() -> dict:
    snaps = load_snapshots()
    overrides = db.overrides()
    by_key: dict[str, dict] = {}
    machines = []
    for snap in snaps:
        machines.append({"machine": snap["machine"], "scanned_at": snap["scanned_at"], "source": snap.get("_source"),
                         "local": snap["machine"] == LOCAL_MACHINE, "projects": len(snap["projects"]),
                         "totals": snap.get("totals")})
        for p in snap["projects"]:
            key = p.get('owner_key') or f"{snap['machine']}|{p['key']}"
            by_key[key] = dict(p, key=key, machine=snap["machine"], scan_key=p["key"], machines=[snap["machine"]])

    # Central collector metadata is authoritative for ingested repositories.
    collected = central.raw_projects()
    targets = {key: _central_target(raw, collected) for key, raw in by_key.items()}
    # Retain saved dashboard facts while live collector observations update Git
    # and filesystem metadata. Imports do not run session adapters.
    for key, raw in by_key.items():
        target = targets[key]
        if target:
            live = next(p for p in collected if p['key'] == target)
            for field in ('activity', 'ai_tools', 'ai_first', 'ai_last', 'created', 'readme', 'docs', 'checklist', 'stack'):
                if raw.get(field): live[field] = raw[field]
            subjects = {commit['hash']: commit.get('subject') for commit in (raw.get('git') or {}).get('recent_commits', [])}
            for commit in (live.get('git') or {}).get('recent_commits', []):
                if subjects.get(commit['hash']): commit['subject'] = subjects[commit['hash']]
    # Carry existing owner data over when a snapshot repository first becomes central.
    with db.conn() as c:
        for old_key, raw in by_key.items():
            target = targets[old_key]
            if not target:
                continue
            for table, column in (('items','project_key'), ('digital_overrides','key'), ('analyses','key'), ('directives','project_key'), ('plan_tasks','project_key')):
                c.execute(f'UPDATE OR IGNORE {table} SET {column}=? WHERE {column}=?', (target, old_key))
            c.execute('UPDATE OR IGNORE dashboard_import_previews SET project_key=? WHERE project_key=?', (target, old_key))
    overrides = db.overrides()
    by_key = {k:p for k,p in by_key.items() if not targets[k]}
    by_key.update({p['key']:p for p in collected})

    projects, hidden = {}, []
    for key, p in by_key.items():
        o = overrides.get(key, {})
        p["display_name"] = o.get("name") or p["name"]
        p["note"] = o.get("note") or ""
        if o.get("hidden"):
            hidden.append({"key": key, "name": p["display_name"]})
            continue
        projects[key] = p
    # Merges run after hides so a merge target can't vanish from under its sources.
    for key, o in overrides.items():
        target = o.get("merge_into")
        if key in projects and target in projects and target != key:
            _merge(projects[target], projects.pop(key))
    # The same repo on two PCs becomes one project; this PC's copy is the anchor so edits stay attached.
    for src, target in same_project_across_machines(projects).items():
        if src in projects and target in projects:
            _merge(projects[target], projects.pop(src))

    analyses = db.latest_analyses()
    out = []
    for p in projects.values():
        p["signals"] = digital_signals(p)
        p["days_idle"] = _days_since(p.get("last_activity"))
        runs = analyses.get(p["key"], [])
        p["analysis"] = runs[0] if runs else None
        p["analysis_prev"] = runs[1] if len(runs) > 1 else None
        p["analysis_history"] = db.analysis_history(p["key"]) if runs else []
        # Stale when the project changed after the last analysis.
        p["analysis_stale"] = bool(runs and (p.get("last_activity") or "") > runs[0]["created_at"])
        out.append(p)
    out.sort(key=lambda p: p.get("last_activity") or "", reverse=True)
    general = [dict(s["general"], machine=s["machine"]) for s in snaps]
    return {"projects": out, "hidden": hidden, "machines": machines, "general": general}


def digital_signals(p: dict) -> list[dict]:
    sig = []
    g = p.get("git")
    name = p["display_name"]
    if g:
        if g.get("uncommitted"):
            sig.append({"level": "warning", "text": f"{g['uncommitted']} uncommitted change(s)",
                        "action": f"Review and commit the work in {name}"})
        if g.get("unpushed"):
            sig.append({"level": "warning", "text": f"{g['unpushed']} commit(s) not pushed",
                        "action": f"Push {name} so the remote has your latest work"})
        if not g.get("remote"):
            sig.append({"level": "serious", "text": "No remote (not backed up off this PC)",
                        "action": f"Add a private GitHub remote for {name}"})
        if g.get("commit_count") == 0:
            sig.append({"level": "warning", "text": "Repository has no commits yet",
                        "action": f"Make a first commit in {name}"})
    elif p.get("kind") == "folder" and (p.get("files") or {}).get("loc_total", 0) > 300:
        sig.append({"level": "serious", "text": "Not under version control",
                    "action": f"Run git init in {name} and push it to a private repo"})
    idle = _days_since(p.get("last_activity"))
    if idle is not None and idle >= 14:
        sig.append({"level": "info", "text": f"No activity for {idle} days",
                    "action": f"Decide whether {name} is paused, done or needs a push"})
    return sig


def physical_view() -> list[dict]:
    projects = db.physical()
    today = date.today()
    for p in projects:
        sig = []
        if p["status"] == "active":
            last = p["last_update"]
            idle = (today - date.fromisoformat(last)).days if last else None
            if idle is None or idle >= 14:
                sig.append({"level": "info", "text": "No progress logged in 14+ days" if last else "No progress logged yet",
                            "action": f"Log an update for {p['name']}"})
        if p["budget"] and p["spent"] > p["budget"]:
            sig.append({"level": "serious", "text": f"Over budget by ${p['spent'] - p['budget']:.0f}",
                        "action": f"Review spending on {p['name']}"})
        if p["target_date"] and p["status"] != "done":
            try:
                if date.fromisoformat(p["target_date"]) < today:
                    sig.append({"level": "warning", "text": "Past target date",
                                "action": f"Set a new target date for {p['name']}"})
            except ValueError:
                pass
        p["signals"] = sig
    return projects


# ---------------------------------------------------------------- HTTP

ROUTES: list[tuple[str, re.Pattern, callable]] = []


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append((method, re.compile(f"^{pattern}$"), fn))
        return fn
    return deco


def project_list(view: dict) -> list[dict]:
    overrides = db.overrides()
    items = db.items()
    errors = {k: v["error"] for k, v in preview_jobs.items() if v.get("status") == "error"}
    result = []
    from .dashboard_transfer import initialize
    initialize(db)
    with db.conn() as c:
        imported_previews = {row['project_key']: row['name'] for row in c.execute('SELECT project_key,name FROM dashboard_import_previews')}
    for raw in view['projects']:
        p = projects.build(raw, overrides.get(raw['key'], {}), items.get(raw['key'], []), errors)
        p['facts']['local'] = not is_cloud() and p['facts']['local']
        if not p['previewImage'] and raw['key'] in imported_previews:
            p['previewImage'] = '/previews/' + imported_previews[raw['key']]
            p['previewKind'] = 'screenshot'
        if raw.get('central'):
            p['intelligence'] = raw['central']
            p['lastSynced'] = raw['last_synced']
            p['facts']['todoCount'] = raw.get('todo_count', 0)
            p['facts']['local'] = not is_cloud() and p['facts']['local']
        result.append(p)
    return result


@route("GET", r"/api/state")
def api_state(body, **_):
    view = digital_view()
    plist = project_list(view)
    return {"projects": plist, "planner": planner.payload(db, plist), "central": central.snapshot(),
            "digital": {"hidden": view["hidden"], "machines": view["machines"], "general": view["general"]},
            "physical": physical_view(), "scan": scan_state,
            "meta": {"phases": analyzer.PHASES, "types": analyzer.TYPES, "statuses": projects.STATUSES,
                     "priorities": projects.PRIORITIES, "browser": not is_cloud() and bool(previews.find_browser()),
                     "scanAvailable": not is_cloud()},
            "machine": socket.gethostname(), "analysis": analysis_status(),
            "access": {"remote": is_remote() or is_cloud(), "cloud": is_cloud()},
            "settings": settings_payload()}


@route('GET', r'/api/integrations')
def api_integrations(body, **_):
    return central.snapshot()


@route('GET', r'/api/dashboard/export')
def api_dashboard_export(body, **_):
    from .dashboard_transfer import export_dashboard
    saved = digital_view()
    snapshot = {'machine': LOCAL_MACHINE, 'scanned_at': datetime.now(timezone.utc).isoformat(),
                'projects': [dict(p, owner_key=p['key']) for p in saved['projects']], 'general': {}}
    return export_dashboard(db, [snapshot], LOCAL_MACHINE, previews.PREVIEWS)


@route('POST', r'/api/dashboard/import')
def api_dashboard_import(body, **_):
    from .dashboard_transfer import import_dashboard, validate
    validate(body, db)
    collected = central.raw_projects()
    project_map = {}
    for snap in body.get('snapshots', []) if isinstance(body.get('snapshots'), list) else []:
        if not isinstance(snap, dict): continue
        for p in snap.get('projects', []) if isinstance(snap.get('projects'), list) else []:
            if not isinstance(p, dict): continue
            target = _central_target(p, collected)
            if target: project_map[p.get('owner_key') or snap['machine'] + '|' + p['key']] = target
    return import_dashboard(db, body, project_map)


@route('POST', r'/api/integrations/devices')
def api_register_device(body, **_):
    return central.register(body.get('device_id'))


@route('POST', r'/api/integrations/pair/approve')
def api_pair_approve(body, **_):
    return central.pairing_approve(body.get('code'))


@route('POST', r'/api/integrations/revoke')
def api_revoke_device(body, **_):
    with db.conn() as c:
        c.execute('UPDATE devices SET revoked=1 WHERE id=?', (str(body.get('device_id', '')),))
    return {'ok': True}


@route('POST', r'/api/integrations/sync')
def api_request_sync(body, **_):
    from .central import now
    with db.conn() as c:
        c.execute('INSERT INTO sync_requests(device_id,requested_at) SELECT id,? FROM devices WHERE revoked=0 ON CONFLICT(device_id) DO UPDATE SET requested_at=excluded.requested_at', (now(),))
    return {'ok': True, 'message': 'Sync requested. Online collectors pick it up at their next heartbeat.'}


@route('POST', r'/api/integrations/instruction')
def api_human_instruction(body, **_):
    text = str(body.get('text') or '').strip()
    plist = _planner_projects()
    selected = next((p for p in plist if p['id'] == body.get('project_id')), None)
    if not selected or not text or len(text) > 2000:
        raise ValueError('Choose a project and enter an instruction (maximum 2000 characters)')
    parsed = {'directives':[{'project_name': selected['name'], 'summary':text, 'kind':'focus', 'source':'me', 'strength':'high', 'persist':'until_changed', 'keywords':[], 'proposed_tasks':[]} ]}
    planner.apply_directives(db, plist, text, parsed)
    # The literal human task is preserved; no model interpretation is required.
    with db.conn() as c:
        exists = c.execute("SELECT id FROM items WHERE project_key=? AND title=? AND source='user' AND status!='dismissed'", (selected['id'],text[:300])).fetchone()
    if not exists:
        db.add_item(selected['id'], {'title':text[:300], 'detail':text, 'priority':'high', 'via':'human_instruction'})
    planner.generate(db, _planner_projects(), use_llm=False)
    return {'ok':True}


@route('GET', r'/api/debug')
def api_debug(body, **_):
    with db.conn() as c:
        healthy = c.execute('PRAGMA quick_check').fetchone()[0]
    snap = central.snapshot()
    return {'server': 'ok', 'database': healthy, 'durable_path_configured': bool(os.environ.get('TRACKER_DATA_DIR')), 'devices': snap['devices'], 'sources': snap['sources'], 'ingestion': snap['ingestion'], 'sync_requests': snap['sync_requests'], 'projects': len(snap['projects'])}


@route("GET", r"/api/analysis")
def api_analysis_status(body, **_):
    return analysis_status()


@route("POST", r"/api/analyze")
def api_analyze(body, **_):
    keys = body.get("keys")
    if not keys:
        view = digital_view()["projects"]
        mode = body.get("mode", "changed")
        keys = [p["key"] for p in view if mode == "all" or not p["analysis"] or p["analysis_stale"]]
    return {"queued": enqueue(keys), **analysis_status()}


@route("POST", r"/api/analyze/stop")
def api_analyze_stop(body, **_):
    stop_analysis()
    return analysis_status()


def settings_payload() -> dict:
    sd = sync_dir()
    return {"model": db.get_setting("model", "sonnet"), "models": analyzer.MODELS,
            "claude_found": bool(analyzer.find_claude()), "local_machine": LOCAL_MACHINE,
            "sync_dir": "" if is_remote() else (str(sd) if sd else ""), "sync_ok": bool(sd and sd.is_dir()),
            "kit_ready": bool(sd and (sd / "ytpc-kit" / "install.py").exists()),
            "cloud_url": "" if is_remote() or is_cloud() else db.get_setting("cloud_url", ""),
            "cloud_set": bool(db.get_setting("cloud_password", "")),
            "cloud_pushed": db.get_setting("cloud_pushed", "")}


@route("POST", r"/api/settings")
def api_settings(body, **_):
    if body.get("model") in analyzer.MODELS:
        db.set_setting("model", body["model"])
    if "sync_dir" in body:
        db.set_setting("sync_dir", (body["sync_dir"] or "").strip())
    return settings_payload()


@route("POST", r"/api/sync/kit")
def api_sync_kit(body, **_):
    """Copy the second-PC setup kit into the synced folder so it reaches the other PC via OneDrive."""
    sd = sync_dir()
    if not sd:
        raise ValueError("Set a synced folder first (e.g. your OneDrive)")
    kit = sd / "ytpc-kit"
    kit.mkdir(parents=True, exist_ok=True)
    (sd / "snapshots").mkdir(exist_ok=True)
    for f in KIT_SRC.iterdir():
        if f.is_file():
            shutil.copy2(f, kit / f.name)
    shutil.copy2(ROOT / "tracker" / "scanner.py", kit / "scanner.py")
    return {"path": str(kit), **settings_payload()}


@route("POST", r"/api/sync/open")
def api_sync_open(body, **_):
    sd = sync_dir()
    if not sd or not sd.is_dir():
        raise ValueError("The synced folder doesn't exist yet. Create the setup kit first.")
    os.startfile(sd)
    return {"ok": True}


@route("GET", r"/api/scan")
def api_scan_status(body, **_):
    return scan_state


@route("POST", r"/api/scan")
def api_scan(body, **_):
    if is_cloud():
        raise ValueError("Scanning project folders is available only in local development.")
    return {"started": start_scan(), **scan_state}


@route("POST", r"/api/project/meta")
def api_project_meta(body, **_):
    for f in ("live_url", "preview_url", "github_url"):   # only web links: no file:// screenshots, no javascript: links
        v = (body.get(f) or "").strip() if isinstance(body.get(f), str) else ""
        if v and urlsplit(v).scheme not in ("http", "https"):
            raise ValueError("URLs must start with http:// or https://")
    db.set_override(body["key"], body)
    if any(k in body for k in ("live_url", "preview_url")):
        preview_failed.discard(body["key"])
        enqueue_previews([body["key"]])
    return {"ok": True}


@route("POST", r"/api/project/open")
def api_project_open(body, **_):
    raw = _raw_projects().get(body.get("key"))
    path = raw and raw.get("path")
    if not path or not Path(path).is_dir():
        raise ValueError("This project has no folder on this PC")
    if body.get("app") == "code":
        subprocess.Popen(["cmd", "/c", "code", path], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        os.startfile(path)
    return {"ok": True}


@route("POST", r"/api/items")
def api_add_item(body, **_):
    return {"id": db.add_item(body["key"], body)}


@route("GET", r"/api/planner")
def api_planner(body, **_):
    plist = _planner_projects()
    return {"planner": planner.payload(db, plist), "projects": plist}


@route("GET", r"/api/planner/history")
def api_planner_history(body, **_):
    return {"days": planner.history(db)}


@route("POST", r"/api/planner/instruction")
def api_planner_instruction(body, **_):
    text = (body.get("text") or "").strip()
    if not text:
        raise ValueError("Write what changed first")
    return {"started": start_planner_job("instruction", text[:2000]), "job": planner_job}


@route("POST", r"/api/planner/regenerate")
def api_planner_regenerate(body, **_):
    if is_cloud():
        plist = _planner_projects()
        planner.generate(db, plist, planner.today(), use_llm=False)
        return {'planner': planner.payload(db, plist), 'projects': plist}
    return {"started": start_planner_job("regenerate"), "job": planner_job}


@route("POST", r"/api/planner/tasks")
def api_planner_add(body, **_):
    plist = _planner_projects()
    planner.add_manual(db, plist, body)
    return {"planner": planner.payload(db, plist), "projects": plist}


@route("POST", r"/api/planner/pick")
def api_planner_pick(body, **_):
    plist = _planner_projects()
    planner.pick_candidate(db, plist, body.get("cid") or "")
    return {"planner": planner.payload(db, plist), "projects": plist}


@route("POST", r"/api/planner/tasks/(?P<tid>\d+)/(?P<action>[a-z]+)")
def api_planner_task(body, tid, action):
    plist = _planner_projects()
    planner.task_action(db, plist, int(tid), action, body)
    plist = _planner_projects()
    return {"planner": planner.payload(db, plist), "projects": plist}


@route("DELETE", r"/api/planner/directives/(?P<did>\d+)")
def api_planner_end_directive(body, did):
    planner.end_directive(db, int(did))
    plist = _planner_projects()
    return {"planner": planner.payload(db, plist)}


@route("PATCH", r"/api/items/(?P<iid>\d+)")
def api_update_item(body, iid):
    db.update_item(int(iid), body)
    return {"ok": True}


@route("DELETE", r"/api/items/(?P<iid>\d+)")
def api_delete_item(body, iid):
    db.delete_item(int(iid))
    return {"ok": True}


@route("POST", r"/api/previews")
def api_previews(body, **_):
    keys = body.get("keys")
    for k in keys or []:
        preview_failed.discard(k)
    return {"queued": enqueue_previews(keys, missing_only=body.get("missing_only", False))}


@route("POST", r"/api/project/preview-upload")
def api_preview_upload(body, **_):
    m = re.match(r"^data:image/(png|jpeg|jpg|webp|gif);base64,(.+)$", body.get("dataUrl") or "", re.S)
    if not m:
        raise ValueError("Upload a PNG, JPG, WebP or GIF image")
    data = base64.b64decode(m.group(2))
    if len(data) > 12_000_000:
        raise ValueError("Image is larger than 12 MB")
    ext = "jpg" if m.group(1) == "jpeg" else m.group(1)
    name = f"{previews.preview_name(body['key'])}-upload.{ext}"
    previews.PREVIEWS.mkdir(parents=True, exist_ok=True)
    (previews.PREVIEWS / name).write_bytes(data)
    db.set_override(body["key"], {"preview_image": f"{name}?v={int(datetime.now().timestamp())}"})
    return {"ok": True}


@route("POST", r"/api/physical")
def api_create_physical(body, **_):
    return {"id": db.create_physical(body)}


@route("PATCH", r"/api/physical/(?P<pid>\d+)")
def api_update_physical(body, pid):
    db.update_physical(int(pid), body)
    return {"ok": True}


@route("DELETE", r"/api/physical/(?P<pid>\d+)")
def api_delete_physical(body, pid):
    db.delete_physical(int(pid))
    return {"ok": True}


@route("POST", r"/api/physical/(?P<pid>\d+)/updates")
def api_add_update(body, pid):
    return {"id": db.add_update(int(pid), body)}


@route("DELETE", r"/api/updates/(?P<uid>\d+)")
def api_delete_update(body, uid):
    db.delete_update(int(uid))
    return {"ok": True}


@route("POST", r"/api/physical/(?P<pid>\d+)/milestones")
def api_add_milestone(body, pid):
    return {"id": db.add_milestone(int(pid), (body.get("title") or "").strip() or "New milestone")}


@route("PATCH", r"/api/milestones/(?P<mid>\d+)")
def api_update_milestone(body, mid):
    db.update_milestone(int(mid), body)
    return {"ok": True}


@route("DELETE", r"/api/milestones/(?P<mid>\d+)")
def api_delete_milestone(body, mid):
    db.delete_milestone(int(mid))
    return {"ok": True}


MAX_BODY = 20_000_000
PUBLIC_PATHS = {"/login", "/login.js", "/login.css"}
LOCAL_ONLY = re.compile(r"^/api/(access(/|$)|sync/|project/open$|settings$|cloud/)")   # touch the PC itself, never from a phone
ROOT_FILES = {".html", ".js", ".css", ".svg", ".png", ".ico", ".webp"}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
LOG = DATA / "server.log"


def log_error():
    """Append the current traceback to data/server.log (pythonw has no console)."""
    try:
        DATA.mkdir(exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 1_000_000:
            LOG.replace(LOG.with_suffix(".old"))
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n{traceback.format_exc()}\n")
    except OSError:
        pass


class TrackerServer(ThreadingHTTPServer):
    daemon_threads = True
    remote = False      # True for the phone listener: login required, PC-only routes blocked
    tls = False
    cloud = False
    auth_required = False
    expected_host = None

    def handle_error(self, request, client_address):   # failed TLS handshakes and dropped connections are routine
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = "ProjectTracker"
    sys_version = ""
    timeout = 30        # a stalled client can't hold a thread (or a half-finished TLS handshake) open

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _common_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")

    def _send(self, code: int, payload: bytes, ctype: str, extra=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self._common_headers()
        if self.server.cloud:
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, code: int, obj, extra=()):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json", extra)

    def _redirect(self, where: str):
        self.send_response(302)
        self.send_header("Location", where)
        self.send_header("Content-Length", "0")
        self._common_headers()
        self.end_headers()

    def _file(self, fp: Path):
        ctype = mimetypes.guess_type(fp.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, fp.read_bytes(), ctype)

    def _authed(self) -> bool:
        return not (self.server.remote or self.server.auth_required) or security.valid_session(
            security.cookie_from(self.headers.get("Cookie")))

    def _login(self, body: dict):
        if self.server.cloud:
            ip = self.client_address[0]
            wait = security.throttle_wait(ip)
            if wait:
                return self._json(429, {"error": f"Too many wrong passwords. Try again in {max(1, wait // 60)} min."},
                                  [("Retry-After", str(wait))])
            password = str(body.get("code", ""))[:256]
            if not security.try_password(ip, password, os.environ["APP_PASSWORD"]):
                return self._json(401, {"error": "Incorrect password."})
        elif not self.server.remote:
            return self._json(200, {"ok": True})
        else:
            ip = self.client_address[0]
            wait = security.throttle_wait(ip)
            if wait:
                return self._json(429, {"error": f"Too many wrong codes. Try again in {max(1, wait // 60)} min."},
                                  [("Retry-After", str(wait))])
            if not security.try_code(ip, str(body.get("code", ""))[:64]):
                return self._json(401, {"error": "That code isn't right."})
        token = security.new_session()
        cookie = (f"{security.COOKIE}={token}; Path=/; Max-Age={security.SESSION_DAYS * 86400}; HttpOnly; SameSite=Strict"
                  + ("; Secure" if self.server.tls or self.server.cloud else ""))
        self._json(200, {"ok": True}, [("Set-Cookie", cookie)])

    def _logout(self):
        security.end_session(security.cookie_from(self.headers.get("Cookie")))
        gone = f"{security.COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict" + (
            "; Secure" if self.server.tls or self.server.cloud else "")
        self._json(200, {"ok": True}, [("Set-Cookie", gone)])

    def _mirror(self, raw: bytes):
        """Receive a data snapshot pushed from the owner's PC (cloud mode only)."""
        if not self.server.cloud:
            return self._json(404, {"error": "not found"})
        auth = self.headers.get("Authorization") or ""
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if not token or not security.try_password(self.client_address[0], token[:256], os.environ["APP_PASSWORD"]):
            return self._json(401, {"error": "bad credentials"})
        try:
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
            return self._json(200, apply_mirror(body))
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except Exception:
            log_error()
            return self._json(500, {"error": "Something went wrong. Details are in data/server.log."})

    def _dispatch(self, method: str):
        srv = self.server
        _ctx.remote = srv.remote
        _ctx.cloud = srv.cloud
        path = urlsplit(self.path).path
        host = (self.headers.get("Host") or "").lower()
        # 1. Who is this, and are they talking to us by a name we own?
        if not security.host_ok(host, srv.remote, srv.server_address[1], srv.expected_host if srv.cloud else None):
            return self._json(400, {"error": "unexpected host"})
        if srv.remote and not security.is_private(self.client_address[0]):
            return self._json(403, {"error": "forbidden"})
        # 2. Requests started by another website are refused (CSRF / DNS-rebinding).
        api_call = path.startswith("/api/") or method != "GET"
        if api_call and self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return self._json(403, {"error": "cross-site request blocked"})
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc.lower() != host:
            return self._json(403, {"error": "forbidden origin"})
        if path in ('/health','/api/health') and method == 'GET':
            return self._json(200, {'status':'ok','service':'project-planner','collector_api_version':2,'agent_api_version':1,'collector_endpoints':['register','heartbeat','projects','status']})
        # 3. Read a bounded body.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json(400, {"error": "bad request"})
        if length < 0 or length > (2_000_000 if path.startswith('/api/agent/') else 5_000_000 if path.startswith('/api/collector/') else MAX_BODY):
            return self._json(413, {"error": "request too large"})
        raw = self.rfile.read(length) if length else b""
        if path.startswith('/api/agent/v1/'):
            endpoint=path[len('/api/agent/v1/'):]
            if endpoint in ('pair/start','pair/claim') and method=='POST':
                path='/api/collector/'+endpoint
            else:
                from . import agent_api
                if (method,endpoint) not in (('POST','register'),('POST','heartbeat'),('POST','projects'),('POST','events/batch'),('GET','status')):
                    return self._json(404,{'error':'Agent operation not supported'})
                if length>2_000_000: return self._json(413,{'error':'Agent request too large'})
                auth=self.headers.get('Authorization','')
                device=central.authenticate(auth[7:] if auth.startswith('Bearer ') else '')
                if not device: return self._json(401,{'error':'Invalid or revoked device credential'})
                if agent_api.limited(device): return self._json(429,{'error':'Agent rate limit reached'},[('Retry-After','60')])
                try:
                    body=json.loads(raw or b'{}')
                    if not isinstance(body,dict) or body.get('device_id',device)!=device: raise ValueError('Device identity mismatch')
                    return self._json(200,agent_api.dispatch(central,device,endpoint,body))
                except (ValueError,TypeError): return self._json(400,{'error':'Invalid agent metadata; local queue must be retained'})
                except Exception:
                    log_error(); return self._json(500,{'error':'Agent database operation failed'})
        # 4. Login gate for the phone listener.
        if path == "/api/login" and method == "POST":
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                body = {}
            return self._login(body if isinstance(body, dict) else {})
        if path == "/api/logout" and method == "POST":
            return self._logout()
        if path.startswith('/api/collector/'):
            if path in ('/api/collector/pair/start','/api/collector/pair/claim') and method=='POST':
                try:
                    body=json.loads(raw or b'{}')
                    if not isinstance(body,dict): raise ValueError()
                    if path.endswith('/start'):
                        # Bound requests per client; no browser credential is used by collectors.
                        if security.throttle_wait(self.client_address[0]):
                            return self._json(429,{'error':'Try pairing again later'})
                        return self._json(200,central.pairing_start(body))
                    auth=self.headers.get('Authorization','')
                    return self._json(200,central.pairing_claim(auth[7:] if auth.startswith('Bearer ') else ''))
                except ValueError:
                    return self._json(400,{'error':'Pairing request invalid, expired or at capacity'})
                except Exception:
                    log_error()
                    return self._json(500,{'error':'Pairing database operation failed'})
            if (method,path) not in (('POST','/api/collector/register'),('POST','/api/collector/heartbeat'),('POST','/api/collector/projects'),('GET','/api/collector/status')):
                return self._json(404, {'error': 'Collector endpoint not implemented'})
            auth = self.headers.get('Authorization', '')
            device = central.authenticate(auth[7:] if auth.startswith('Bearer ') else '')
            if not device:
                token=auth[7:] if auth.startswith('Bearer ') else ''
                # Attribute revoked credentials by their stored hash, never by a claimed device name.
                import hashlib
                with db.conn() as c:
                    known=c.execute('SELECT id FROM devices WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone() if token and len(token)<=200 else None
                central.log(known['id'] if known else None, 'rejected', '401 — Collector authentication failed')
                return self._json(401, {'error': 'Invalid or revoked collector credential'})
            try:
                body = json.loads(raw or b'{}')
                if not isinstance(body, dict):
                    raise ValueError('Expected a JSON object')
                if body.get('device_id') and body['device_id'] != device:
                    raise ValueError('Configured device ID does not match the collector token')
                if path.endswith('/register'):
                    result=central.register_collector(device,body)
                elif path.endswith('/status'):
                    result=central.collector_status(device)
                elif path.endswith('/heartbeat'):
                    result=central.heartbeat(device)
                else:
                    result=central.ingest(device,body)
                return self._json(200, result)
            except ValueError:
                central.log(device, 'rejected', 'Malformed metadata: check schema, counts and timestamps')
                return self._json(400, {'error': 'Malformed metadata: check schema, counts and timestamps'})
            except Exception:
                central.log(device, 'failed', 'Database ingestion failed')
                log_error()
                return self._json(500, {'error': 'Database ingestion failed'})
        if path == "/api/mirror" and method == "POST":
            return self._mirror(raw)
        if not self._authed() and path not in PUBLIC_PATHS:
            if api_call:
                return self._json(401, {"error": "login required"})
            return self._redirect("/login")
        if srv.cloud and re.match(r"^/api/(scan|analyze(?:/|$)|previews$|planner/instruction$)", path):
            return self._json(501, {"error": "This feature requires the local development server."})
        if (srv.remote or srv.auth_required) and LOCAL_ONLY.match(path):
            return self._json(403, {"error": "This can only be done on the PC itself."})
        if path == "/login" and self._authed():
            return self._redirect("/")
        # 5. Routes.
        if method == "GET" and path.startswith("/previews/"):
            fp = (previews.PREVIEWS / path[len("/previews/"):]).resolve()
            if fp.is_relative_to(previews.PREVIEWS.resolve()) and fp.is_file():
                return self._file(fp)
            from .dashboard_transfer import initialize
            initialize(db)
            with db.conn() as c:
                image = c.execute('SELECT data FROM dashboard_import_previews WHERE name=?', (path[len('/previews/'):],)).fetchone()
            if image: return self._send(200, image['data'], 'image/png')
            return self._send(404, b"Not found", "text/plain")
        if method == "GET" and path == "/api/repo-image":
            qs = parse_qs(urlsplit(self.path).query)
            raw_p = _raw_projects().get((qs.get("k") or [""])[0])
            try:
                fp = projects.repo_image(raw_p, int((qs.get("i") or ["0"])[0])) if raw_p else None
            except ValueError:
                fp = None
            if fp and fp.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
                return self._file(fp)
            return self._send(404, b"Not found", "text/plain")
        if path.startswith("/api/"):
            for m, pat, fn in ROUTES:
                match = pat.match(path)
                if m == method and match:
                    try:
                        body = json.loads(raw) if raw else {}
                        if not isinstance(body, dict):
                            raise ValueError("Expected a JSON object")
                        return self._json(200, fn(body, **match.groupdict()))
                    except ValueError as e:
                        return self._json(400, {"error": str(e)})
                    except Exception:
                        log_error()
                        return self._json(500, {"error": "Something went wrong. Details are in data/server.log."})
            return self._json(404, {"error": "not found"})
        if method != "GET":
            return self._json(405, {"error": "method not allowed"})
        rel = "index.html" if path in ("", "/") else "login.html" if path == "/login" else path.lstrip("/")
        parts = Path(rel).parts
        fp = (STATIC / rel).resolve()
        if (not (len(parts) == 1 or parts[0] == "js") or any(p.startswith(".") for p in parts)
                or not fp.is_relative_to(STATIC.resolve()) or not fp.is_file() or fp.suffix.lower() not in ROOT_FILES):
            return self._send(404, b"Not found", "text/plain")
        self._file(fp)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")


# ---------------------------------------------------------------- phone (LAN) listener

lan = {"httpd": None, "error": None}
lan_lock = threading.Lock()


def start_lan():
    with lan_lock:
        if lan["httpd"]:
            return
        lan["error"] = None
        try:
            ctx = security.server_context()
            httpd = TrackerServer(("0.0.0.0", security.LAN_PORT), Handler)
            httpd.remote, httpd.tls = True, True
            # Handshake happens lazily in the request thread, so a slow client can't stall the accept loop.
            httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True, do_handshake_on_connect=False)
        except Exception as e:
            lan["error"] = str(e) or e.__class__.__name__
            return
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        lan["httpd"] = httpd


def stop_lan():
    with lan_lock:
        h, lan["httpd"] = lan["httpd"], None
    if h:
        h.shutdown()
        h.server_close()


def access_payload() -> dict:
    return {"enabled": security.is_enabled(), "running": bool(lan["httpd"]), "error": lan["error"],
            "code": security.display_code(), "port": security.LAN_PORT,
            "urls": [f"https://{ip}:{security.LAN_PORT}/" for ip in security.lan_ips()],
            "fingerprint": security.fingerprint(), "sessions": security.session_count(),
            "openssl": security.openssl_available()}


@route("GET", r"/api/access")
def api_access(body, **_):
    return access_payload()


@route("POST", r"/api/access")
def api_access_set(body, **_):
    if body.get("enabled"):
        security.set_enabled(True)
        start_lan()
        if lan["error"]:
            security.set_enabled(False)
            raise ValueError("Phone access could not start: " + lan["error"])
    else:
        security.set_enabled(False)
        stop_lan()
    return access_payload()


@route("POST", r"/api/access/code")
def api_access_code(body, **_):
    security.regenerate_code()
    return access_payload()


@route("POST", r"/api/access/revoke")
def api_access_revoke(body, **_):
    security.revoke_all()
    return access_payload()


# ------------------------------------------------------------------ cloud mirror

MIRROR_NAME = re.compile(r"^[\w][\w.-]{0,119}$")
MIRROR_IMAGE_EXTS = (".png", ".webp", ".jpg", ".jpeg")


def apply_mirror(body: dict) -> dict:
    """Replace this instance's data with the snapshot pushed from the owner's PC."""
    with db.conn() as c:
        if c.execute('SELECT COUNT(*) FROM devices').fetchone()[0]:
            raise ValueError('Whole-database mirroring is disabled once collectors are registered. Use incremental collectors to preserve all devices and owner edits.')
    blob = base64.b64decode(str(body.get("db") or ""), validate=True)
    if not blob.startswith(b"SQLite format 3\x00"):
        raise ValueError("Not a SQLite database")
    snaps = body.get("snapshots") or {}
    prevs = body.get("previews") or {}
    if not isinstance(snaps, dict) or not isinstance(prevs, dict):
        raise ValueError("Bad snapshot payload")
    for name in list(snaps) + list(prevs):
        if not isinstance(name, str) or not MIRROR_NAME.match(name) or ".." in name:
            raise ValueError("Bad file name")
    tmp = DATA / "tracker.db.push"
    tmp.write_bytes(blob)
    try:
        src = sqlite3.connect(tmp)
        try:
            dst = sqlite3.connect(db.path, timeout=30)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    finally:
        tmp.unlink(missing_ok=True)
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    for f in SNAPSHOTS.glob("*.json"):
        f.unlink()
    for name, content in snaps.items():
        if not name.endswith(".json"):
            raise ValueError("Snapshots must be .json")
        (SNAPSHOTS / name).write_text(json.dumps(content), encoding="utf-8")
    previews.PREVIEWS.mkdir(parents=True, exist_ok=True)
    for name, b64 in prevs.items():
        if Path(name).suffix.lower() not in MIRROR_IMAGE_EXTS:
            raise ValueError("Previews must be images")
        (previews.PREVIEWS / name).write_bytes(base64.b64decode(str(b64), validate=True))
    for f in previews.PREVIEWS.iterdir():
        if f.is_file() and f.name not in prevs:
            f.unlink()
    stamp = {"pushed_at": datetime.now(timezone.utc).isoformat(), "machine": str(body.get("machine") or "")[:80]}
    (DATA / "mirror.json").write_text(json.dumps(stamp), encoding="utf-8")
    return {"ok": True, **stamp}


@route("POST", r"/api/cloud/push")
def api_cloud_push(body, **_):
    """Send a snapshot of this PC's data to the cloud mirror site."""
    import urllib.error
    import urllib.request
    url = (str(body.get("url") or "") or db.get_setting("cloud_url", "")).strip().rstrip("/")
    password = str(body.get("password") or "") or db.get_setting("cloud_password", "")
    if not url.startswith(("http://", "https://")):
        raise ValueError("Enter the cloud site address (https://...)")
    if len(password) < 16:
        raise ValueError("Enter the deployment password (at least 16 characters)")
    db.set_setting("cloud_url", url)
    db.set_setting("cloud_password", password)
    payload = {"machine": LOCAL_MACHINE,
               "db": base64.b64encode(db.path.read_bytes()).decode(),
               "snapshots": {f.name: json.loads(f.read_text(encoding="utf-8")) for f in SNAPSHOTS.glob("*.json")},
               "previews": {f.name: base64.b64encode(f.read_bytes()).decode() for f in previews.PREVIEWS.iterdir()
                            if f.is_file() and f.suffix.lower() in MIRROR_IMAGE_EXTS
                            and f.stat().st_size <= 2_000_000}}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url + "/api/mirror", data=data, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + password})
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read() or b"{}").get("error") or f"HTTP {e.code}"
        except ValueError:
            msg = f"HTTP {e.code}"
        raise ValueError(f"The cloud site refused the push: {msg}")
    except (TimeoutError, OSError) as e:
        raise ValueError(f"Couldn't reach the cloud site: {getattr(e, 'reason', e)}")
    stamp = datetime.now(timezone.utc).isoformat()
    db.set_setting("cloud_pushed", stamp)
    return {"ok": True, "pushed_at": stamp, "bytes": len(data)}


def serve(port: int = 8765, *, host: str = "127.0.0.1", production: bool = False,
          expected_host: str | None = None) -> ThreadingHTTPServer:
    if production:
        password = os.environ.get("APP_PASSWORD", "")
        if len(password) < 16:
            raise RuntimeError("Set APP_PASSWORD to a strong secret of at least 16 characters before production startup.")
        if not expected_host:
            raise RuntimeError("Set PUBLIC_HOSTNAME or RENDER_EXTERNAL_HOSTNAME before production startup.")
        host = "0.0.0.0"
    # Windows can map .js/.css to text/plain via the registry; browsers then refuse them.
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("image/webp", ".webp")
    httpd = TrackerServer((host, port), Handler)
    httpd.cloud = production
    httpd.auth_required = production
    httpd.expected_host = expected_host.strip().lower().rstrip(".") if expected_host else None
    if not production and security.is_enabled():
        threading.Thread(target=start_lan, daemon=True).start()
    if production:
        scan_state.update(running=False, message="Scanning unavailable in cloud mode", error=None)
    elif not list(SNAPSHOTS.glob("*.json")):
        start_scan()  # first launch: populate the digital dashboard
    else:
        threading.Thread(target=enqueue_previews, kwargs={"missing_only": True}, daemon=True).start()
    return httpd
