"""SQLite store for physical projects and digital-project overrides."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS physical_projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Other',
    status TEXT NOT NULL DEFAULT 'planning',
    description TEXT NOT NULL DEFAULT '',
    budget REAL,
    target_date TEXT,
    color INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS physical_updates (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES physical_projects(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    progress INTEGER,
    note TEXT NOT NULL DEFAULT '',
    hours REAL NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS milestones (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES physical_projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS digital_overrides (
    key TEXT PRIMARY KEY,
    name TEXT,
    hidden INTEGER NOT NULL DEFAULT 0,
    merge_into TEXT,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    model TEXT,
    phase TEXT,
    health INTEGER,
    result TEXT NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS analyses_key ON analyses(key, id);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    project_key TEXT NOT NULL,
    kind TEXT NOT NULL,              -- task | milestone | blocker | bug | goal
    title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'todo',  -- task/milestone: todo|doing|done; blocker/bug: open|resolved; any: dismissed
    priority TEXT NOT NULL DEFAULT 'medium',
    due TEXT,
    source TEXT NOT NULL DEFAULT 'user',  -- user | ai
    ai_key TEXT,
    user_touched INTEGER NOT NULL DEFAULT 0,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS items_project ON items(project_key, kind);

-- Daily planner. Directives live here, never in the project data, so the original priorities stay intact.
CREATE TABLE IF NOT EXISTS directives (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    project_key TEXT NOT NULL DEFAULT '',
    project_name TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'focus',
    source TEXT NOT NULL DEFAULT 'me',
    strength TEXT NOT NULL DEFAULT 'high',
    keywords TEXT NOT NULL DEFAULT '[]',
    persist TEXT NOT NULL DEFAULT 'until_changed',
    until_date TEXT,
    until_condition TEXT NOT NULL DEFAULT '',
    available_minutes INTEGER,
    focus_area TEXT NOT NULL DEFAULT '',
    track_item_ids TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    created_day TEXT NOT NULL,
    ended_at TEXT,
    ended_why TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS plan_days (
    day TEXT PRIMARY KEY,
    headline TEXT NOT NULL DEFAULT '',
    focus TEXT NOT NULL DEFAULT '',
    available_min INTEGER,
    generated_at TEXT,
    model TEXT,
    source TEXT NOT NULL DEFAULT 'rules',
    candidates TEXT NOT NULL DEFAULT '[]',
    directives TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS plan_tasks (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    rank INTEGER NOT NULL DEFAULT 0,
    cid TEXT NOT NULL DEFAULT '',
    project_key TEXT NOT NULL DEFAULT '',
    project_name TEXT NOT NULL DEFAULT '',
    item_id INTEGER,
    title TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'Medium',
    est_minutes INTEGER,
    reason TEXT NOT NULL DEFAULT '',
    blocker_status TEXT NOT NULL DEFAULT '',
    impact TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'todo',   -- todo | doing | done | skipped | moved
    score REAL NOT NULL DEFAULT 0,
    breakdown TEXT NOT NULL DEFAULT '[]',
    origin TEXT NOT NULL DEFAULT 'ai',     -- ai | rules | manual | moved
    accepted INTEGER NOT NULL DEFAULT 0,
    skip_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS plan_tasks_day ON plan_tasks(day, rank);
CREATE TABLE IF NOT EXISTS planner_events (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    task_id INTEGER,
    text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_bias (
    task_key TEXT PRIMARY KEY,
    bias REAL NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    expires TEXT,
    updated_at TEXT NOT NULL
);
"""

# Columns added to items for the planner: estimated minutes, a prerequisite item, and where the item came from.
ITEM_COLUMNS = {"effort_min": "INTEGER", "depends_on": "INTEGER", "via": "TEXT"}

# Columns added to digital_overrides after the first release (owner-editable project fields).
OVERRIDE_COLUMNS = {
    "type": "TEXT", "priority": "TEXT", "status": "TEXT", "phase": "TEXT", "description": "TEXT",
    "live_url": "TEXT", "preview_url": "TEXT", "github_url": "TEXT", "target_date": "TEXT",
    "progress": "INTEGER", "preview_image": "TEXT",
}
META_FIELDS = ("name", "hidden", "merge_into", "note", *OVERRIDE_COLUMNS)
ITEM_KINDS = ("task", "milestone", "blocker", "bug", "goal")

SEED = [
    ("Drone build", "Drone", "Frame, flight controller, motors, ESCs, FPV and first flight.",
     2, ["Pick frame & parts list", "Order parts", "Assemble frame & motors", "Wire ESCs & flight controller",
         "Flash & configure Betaflight", "Bench test (props off)", "First hover", "FPV setup"]),
    ("Car repair", "Car", "Diagnose and fix the car.", 1,
     ["Diagnose the issue", "Source parts", "Do the repair", "Test drive"]),
    ("3D printing", "3D Printing", "Printer setup, calibration and print projects.", 3,
     ["Level bed & calibrate", "Dial in first-layer & retraction", "Print first project", "Design own part"]),
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        fresh = not path.exists()
        with self.conn() as c:
            c.executescript(SCHEMA)
            have = {r[1] for r in c.execute("PRAGMA table_info(digital_overrides)")}
            for col, typ in OVERRIDE_COLUMNS.items():
                if col not in have:
                    c.execute(f"ALTER TABLE digital_overrides ADD COLUMN {col} {typ}")
            have = {r[1] for r in c.execute("PRAGMA table_info(items)")}
            for col, typ in ITEM_COLUMNS.items():
                if col not in have:
                    c.execute(f"ALTER TABLE items ADD COLUMN {col} {typ}")
            if fresh:
                self._seed(c)

    def conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    def _seed(self, c):
        for name, cat, desc, color, steps in SEED:
            cur = c.execute(
                "INSERT INTO physical_projects (name, category, status, description, color, created_at)"
                " VALUES (?, ?, 'planning', ?, ?, ?)", (name, cat, desc, color, now()))
            for i, step in enumerate(steps):
                c.execute("INSERT INTO milestones (project_id, title, sort) VALUES (?, ?, ?)",
                          (cur.lastrowid, step, i))

    # ------------------------------------------------------------ physical

    def physical(self) -> list[dict]:
        with self.conn() as c:
            projects = [dict(r) for r in c.execute("SELECT * FROM physical_projects ORDER BY id")]
            for p in projects:
                p["updates"] = [dict(r) for r in c.execute(
                    "SELECT * FROM physical_updates WHERE project_id=? ORDER BY day DESC, id DESC", (p["id"],))]
                p["milestones"] = [dict(r) for r in c.execute(
                    "SELECT * FROM milestones WHERE project_id=? ORDER BY sort, id", (p["id"],))]
                with_progress = [u for u in p["updates"] if u["progress"] is not None]
                ms = p["milestones"]
                p["milestone_pct"] = round(100 * sum(m["done"] for m in ms) / len(ms)) if ms else None
                p["progress"] = with_progress[0]["progress"] if with_progress else (p["milestone_pct"] or 0)
                p["spent"] = round(sum(u["cost"] for u in p["updates"]), 2)
                p["hours"] = round(sum(u["hours"] for u in p["updates"]), 1)
                p["last_update"] = p["updates"][0]["day"] if p["updates"] else None
        return projects

    def create_physical(self, d: dict) -> int:
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO physical_projects (name, category, status, description, budget, target_date, color, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (d.get("name") or "Untitled", d.get("category") or "Other", d.get("status") or "planning",
                 d.get("description") or "", _num(d.get("budget")), d.get("target_date") or None,
                 int(d.get("color") or 1), now()))
            return cur.lastrowid

    def update_physical(self, pid: int, d: dict):
        fields = {k: d[k] for k in ("name", "category", "status", "description", "budget", "target_date", "color") if k in d}
        if "budget" in fields:
            fields["budget"] = _num(fields["budget"])
        if not fields:
            return
        with self.conn() as c:
            c.execute(f"UPDATE physical_projects SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                      (*fields.values(), pid))

    def delete_physical(self, pid: int):
        with self.conn() as c:
            c.execute("DELETE FROM physical_projects WHERE id=?", (pid,))

    def add_update(self, pid: int, d: dict) -> int:
        prog = d.get("progress")
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO physical_updates (project_id, day, progress, note, hours, cost, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pid, d.get("day") or date.today().isoformat(),
                 None if prog in (None, "") else max(0, min(100, int(prog))),
                 d.get("note") or "", _num(d.get("hours")) or 0, _num(d.get("cost")) or 0, now()))
            # Logging work moves a "planning" project to "active".
            c.execute("UPDATE physical_projects SET status='active' WHERE id=? AND status='planning'", (pid,))
            if prog not in (None, "") and int(prog) >= 100:
                c.execute("UPDATE physical_projects SET status='done' WHERE id=?", (pid,))
            return cur.lastrowid

    def delete_update(self, uid: int):
        with self.conn() as c:
            c.execute("DELETE FROM physical_updates WHERE id=?", (uid,))

    def add_milestone(self, pid: int, title: str) -> int:
        with self.conn() as c:
            n = c.execute("SELECT COALESCE(MAX(sort), -1) + 1 FROM milestones WHERE project_id=?", (pid,)).fetchone()[0]
            return c.execute("INSERT INTO milestones (project_id, title, sort) VALUES (?, ?, ?)",
                             (pid, title, n)).lastrowid

    def update_milestone(self, mid: int, d: dict):
        with self.conn() as c:
            if "done" in d:
                c.execute("UPDATE milestones SET done=? WHERE id=?", (1 if d["done"] else 0, mid))
            if d.get("title"):
                c.execute("UPDATE milestones SET title=? WHERE id=?", (d["title"], mid))

    def delete_milestone(self, mid: int):
        with self.conn() as c:
            c.execute("DELETE FROM milestones WHERE id=?", (mid,))

    # ------------------------------------------------------------ digital

    def overrides(self) -> dict[str, dict]:
        with self.conn() as c:
            return {r["key"]: dict(r) for r in c.execute("SELECT * FROM digital_overrides")}

    # ------------------------------------------------------------ analyses

    def save_analysis(self, key: str, result: dict, meta: dict) -> int:
        self.sync_ai_items(key, result)
        with self.conn() as c:
            return c.execute(
                "INSERT INTO analyses (key, created_at, model, phase, health, result, meta) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, now(), meta.get("model"), result.get("phase"), result.get("health"),
                 json.dumps(result), json.dumps(meta))).lastrowid

    def latest_analyses(self) -> dict[str, list[dict]]:
        """Latest two analyses per project key (newest first) for the diff view."""
        out: dict[str, list[dict]] = {}
        with self.conn() as c:
            for r in c.execute("SELECT * FROM analyses ORDER BY id DESC"):
                lst = out.setdefault(r["key"], [])
                if len(lst) < 2:
                    lst.append(_analysis_row(r))
        return out

    def analysis_history(self, key: str) -> list[dict]:
        with self.conn() as c:
            return [{"id": r["id"], "created_at": r["created_at"], "phase": r["phase"], "health": r["health"]}
                    for r in c.execute("SELECT id, created_at, phase, health FROM analyses WHERE key=? ORDER BY id", (key,))]

    def get_setting(self, key: str, default=None):
        with self.conn() as c:
            r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_setting(self, key: str, value: str):
        with self.conn() as c:
            c.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, value))

    def set_override(self, key: str, d: dict):
        cur = self.overrides().get(key, {})
        row = {f: cur.get(f) for f in META_FIELDS}
        for f in META_FIELDS:
            if f in d:
                v = d[f]
                row[f] = v.strip() if isinstance(v, str) else v
        row["hidden"] = 1 if row.get("hidden") else 0
        row["note"] = row.get("note") or ""
        if row.get("progress") in ("", None):
            row["progress"] = None
        else:
            row["progress"] = max(0, min(100, int(row["progress"])))
        for f in META_FIELDS:
            if row[f] == "" and f != "note":
                row[f] = None
        cols = ", ".join(META_FIELDS)
        with self.conn() as c:
            c.execute(
                f"INSERT INTO digital_overrides (key, {cols}) VALUES (?, {', '.join('?' for _ in META_FIELDS)})"
                f" ON CONFLICT(key) DO UPDATE SET {', '.join(f'{f}=excluded.{f}' for f in META_FIELDS)}",
                (key, *(row[f] for f in META_FIELDS)))

    # ------------------------------------------------------------ items (tasks, milestones, blockers, bugs, goals)

    def items(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        with self.conn() as c:
            for r in c.execute("SELECT * FROM items WHERE status != 'dismissed' ORDER BY sort, id"):
                out.setdefault(r["project_key"], []).append(dict(r))
        return out

    def add_item(self, key: str, d: dict) -> int:
        kind = d.get("kind") if d.get("kind") in ITEM_KINDS else "task"
        default_status = "open" if kind in ("blocker", "bug") else "todo"
        with self.conn() as c:
            n = c.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM items WHERE project_key=?", (key,)).fetchone()[0]
            return c.execute(
                "INSERT INTO items (project_key, kind, title, detail, status, priority, due, source, sort, created_at, updated_at,"
                " effort_min, depends_on, via) VALUES (?, ?, ?, ?, ?, ?, ?, 'user', ?, ?, ?, ?, ?, ?)",
                (key, kind, (d.get("title") or "Untitled").strip()[:300], (d.get("detail") or "").strip(),
                 d.get("status") or default_status, d.get("priority") or "medium", d.get("due") or None, n, now(), now(),
                 _int(d.get("effort_min")), _int(d.get("depends_on")), d.get("via") or None)
            ).lastrowid

    def update_item(self, item_id: int, d: dict):
        fields = {k: d[k] for k in ("title", "detail", "status", "priority", "due", "effort_min", "depends_on") if k in d}
        if not fields:
            return
        with self.conn() as c:
            c.execute(f"UPDATE items SET {', '.join(f'{k}=?' for k in fields)}, user_touched=1, updated_at=? WHERE id=?",
                      (*fields.values(), now(), item_id))

    def delete_item(self, item_id: int):
        with self.conn() as c:
            # AI items are dismissed rather than deleted so the next analysis doesn't bring them back.
            c.execute("UPDATE items SET status='dismissed', user_touched=1, updated_at=? WHERE id=? AND source='ai'",
                      (now(), item_id))
            c.execute("DELETE FROM items WHERE id=? AND source!='ai'", (item_id,))

    def sync_ai_items(self, key: str, result: dict):
        """Mirror the analysis' tasks/milestones/blockers/bugs/goals, keeping anything the owner changed."""
        incoming: dict[str, list[dict]] = {k: [] for k in ITEM_KINDS}
        for t in result.get("tasks") or []:
            incoming["task"].append({"title": t["title"], "detail": t.get("detail", ""), "priority": t.get("priority", "medium"),
                                     "status": {"in_progress": "doing", "done": "done"}.get(t.get("status"), "todo")})
        for m in result.get("milestones") or []:
            incoming["milestone"].append({"title": m["title"], "detail": "", "priority": "medium",
                                          "status": "done" if m.get("done") else "todo", "due": m.get("target") or None})
        for b in result.get("blockers") or []:
            incoming["blocker"].append({"title": b["title"], "detail": b.get("detail", ""), "priority": "high", "status": "open"})
        for b in result.get("bugs") or []:
            incoming["bug"].append({"title": b["title"], "detail": b.get("detail", ""), "priority": b.get("severity", "medium"),
                                    "status": "open"})
        for g in result.get("goals") or []:
            incoming["goal"].append({"title": g, "detail": "", "priority": "medium", "status": "todo"})
        with self.conn() as c:
            for kind, new in incoming.items():
                existing = {r["ai_key"]: dict(r) for r in c.execute(
                    "SELECT * FROM items WHERE project_key=? AND kind=? AND source='ai'", (key, kind))}
                seen = set()
                for i, it in enumerate(new):
                    ak = _ai_key(it["title"])
                    seen.add(ak)
                    row = existing.get(ak)
                    if row is None:
                        c.execute(
                            "INSERT INTO items (project_key, kind, title, detail, status, priority, due, source, ai_key, sort, created_at, updated_at)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?, 'ai', ?, ?, ?, ?)",
                            (key, kind, it["title"][:300], it["detail"], it["status"], it["priority"], it.get("due"), ak, 1000 + i, now(), now()))
                    elif not row["user_touched"]:
                        c.execute("UPDATE items SET title=?, detail=?, status=?, priority=?, due=?, sort=?, updated_at=? WHERE id=?",
                                  (it["title"][:300], it["detail"], it["status"], it["priority"], it.get("due"), 1000 + i, now(), row["id"]))
                for ak, row in existing.items():
                    if ak not in seen and not row["user_touched"]:
                        c.execute("DELETE FROM items WHERE id=?", (row["id"],))


def _analysis_row(r) -> dict:
    return {"id": r["id"], "created_at": r["created_at"], "result": json.loads(r["result"]),
            "meta": json.loads(r["meta"] or "{}")}


def _ai_key(title: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()[:120]


def _int(v):
    try:
        return int(v) if v not in (None, "", 0) else None
    except (TypeError, ValueError):
        return None


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
