"""Daily planner: a deterministic priority score picks the candidates, the LLM turns them into today's plan.

Directives (what the owner, a manager or a client said) live in their own table. They change today's ranking but never
rewrite the project's own priorities or tasks. If the LLM is unavailable, a rules-only plan is built from the same scores.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import subprocess
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import analyzer
from .db import _ai_key, now

DATA = Path(__file__).resolve().parent.parent / "data"
LOCK = threading.RLock()

DEFAULT_MINUTES = 360
MIN_TASKS, MAX_TASKS, LLM_POOL = 3, 7, 14
EFFORT_MIN = {"S": 30, "M": 90, "L": 240}
STRENGTH = {"very_high": 100, "high": 60, "medium": 30, "low": 12}
SOURCE_BONUS = {"me": 0, "manager": 15, "client": 10, "collaborator": 5}
SOURCE_LABEL = {"me": "Your", "manager": "Your manager's", "client": "Your client's", "collaborator": "A collaborator's"}
LEVELS = ["Low", "Medium", "High", "Critical"]
PROJECT_PRIORITY = {"High": 30, "Medium": 15, "Low": 4}
TASK_PRIORITY = {"high": 20, "medium": 10, "low": 3}
OPEN = {"task": ("todo", "doing"), "bug": ("open",), "blocker": ("open",)}
DIRECTIVE_KINDS = ["focus", "pause", "avoid_today", "deadline", "time_limit", "focus_area", "blocker", "completed",
                   "note", "release"]
PROJECT_WIDE = 0.35   # share of a directive's weight given to tasks in its project that don't match its keywords


def today() -> str:
    return date.today().isoformat()


def _d(iso: str | None) -> date | None:
    try:
        return date.fromisoformat((iso or "")[:10])
    except ValueError:
        return None


def _days_ago(iso: str | None) -> float | None:
    try:
        dt = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400


def label_for(score: float) -> str:
    return "Critical" if score >= 140 else "High" if score >= 90 else "Medium" if score >= 55 else "Low"


def _vcid(pid: str, title: str) -> str:
    return "v" + hashlib.md5(f"{pid}|{_ai_key(title)}".encode()).hexdigest()[:10]


# ------------------------------------------------------------------ directives

def _row(r, *json_cols) -> dict:
    d = dict(r)
    for c in json_cols:
        try:
            d[c] = json.loads(d.get(c) or "[]")
        except ValueError:
            d[c] = []
    return d


def active_directives(db, day: str, projs: list[dict] | None = None) -> list[dict]:
    """Active directives for `day`; ones whose end condition has been met are closed here."""
    status = {}
    for p in projs or []:
        for k in ("tasks", "bugs", "blockers"):
            for it in p.get(k, []):
                if it.get("id") is not None:
                    status[it["id"]] = it["status"]
    out = []
    with LOCK, db.conn() as c:
        for r in c.execute("SELECT * FROM directives WHERE active=1 ORDER BY id"):
            d = _row(r, "keywords", "track_item_ids")
            why = None
            if d["persist"] == "today" and d["created_day"] != day:
                why = "Expired (today only)"
            elif d["persist"] in ("this_week", "until_date") and d["until_date"] and d["until_date"] < day:
                why = "Expired"
            elif d["persist"] == "until_milestone" and d["track_item_ids"] and projs is not None and all(
                    status.get(i, "done") in ("done", "resolved", "dismissed") for i in d["track_item_ids"]):
                why = "Milestone complete"
            if why:
                c.execute("UPDATE directives SET active=0, ended_at=?, ended_why=? WHERE id=?", (now(), why, d["id"]))
            else:
                out.append(d)
    return out


def end_directive(db, did: int, why: str = "Ended by you"):
    with LOCK, db.conn() as c:
        c.execute("UPDATE directives SET active=0, ended_at=?, ended_why=? WHERE id=? AND active=1", (now(), why, did))


def _match(d: dict, c: dict) -> float:
    """How strongly a directive applies to a candidate: 1 = names it, PROJECT_WIDE = same project only, 0 = unrelated."""
    if c["item_id"] is not None and c["item_id"] in d["track_item_ids"]:
        return 1.0
    text = (c["title"] + " " + c["detail"]).lower()
    hit = any(k and k in text for k in d["keywords"])
    if d["project_key"]:
        if d["project_key"] != c["pid"]:
            return 0.0
        return 1.0 if hit else PROJECT_WIDE
    return 1.0 if hit else 0.0


def _directive_label(d: dict) -> str:
    who = SOURCE_LABEL.get(d["source"], "Your")
    return f"{who} directive: {d['summary'] or d['text']}"[:140]


# ------------------------------------------------------------------ candidates and scoring

def _context(db, projs: list[dict], day: str) -> dict:
    dirs = active_directives(db, day, projs)
    items = {}
    dependents: dict[int, int] = {}
    for p in projs:
        for k in ("tasks", "bugs", "blockers"):
            for it in p.get(k, []):
                if it.get("id") is not None:
                    items[it["id"]] = it
    for it in items.values():
        dep = it.get("dependsOn")
        if dep and it["status"] in ("todo", "doing", "open"):
            dependents[dep] = dependents.get(dep, 0) + 1
    start = (_d(day) - timedelta(days=5)).isoformat()
    carry: dict[str, int] = {}
    recent_done: dict[str, int] = {}
    with db.conn() as c:
        for r in c.execute("SELECT cid, status, day, project_key FROM plan_tasks WHERE day>=? AND day<=?", (start, day)):
            if r["day"] < day and r["status"] in ("todo", "doing") and r["cid"]:
                carry[r["cid"]] = carry.get(r["cid"], 0) + 1
            if r["status"] == "done" and r["day"] >= (_d(day) - timedelta(days=3)).isoformat():
                recent_done[r["project_key"]] = recent_done.get(r["project_key"], 0) + 1
        bias = {r["task_key"]: dict(r) for r in c.execute(
            "SELECT * FROM task_bias WHERE expires IS NULL OR expires>=?", (day,))}
        taken = {r["cid"]: r["status"] for r in c.execute("SELECT cid, status FROM plan_tasks WHERE day=?", (day,))}
    avail = DEFAULT_MINUTES
    for d in dirs:
        if d["kind"] == "time_limit" and d["available_minutes"]:
            avail = int(d["available_minutes"])
    return {"day": day, "dirs": dirs, "items": items, "dependents": dependents, "carry": carry,
            "recent_done": recent_done, "bias": bias, "taken": taken, "available": avail}


def _candidates(projs: list[dict]) -> list[dict]:
    out = []
    for p in projs:
        if p["status"] == "Completed":
            continue
        base = {"pid": p["id"], "pname": p["name"]}
        n_open_tasks = 0
        mine = []
        for kind, key in (("task", "tasks"), ("bug", "bugs"), ("blocker", "blockers")):
            for it in p.get(key, []):
                if it.get("id") is None or it["status"] not in OPEN[kind]:
                    continue
                if kind == "task":
                    n_open_tasks += 1
                mine.append({**base, "cid": f"i{it['id']}", "item_id": it["id"], "kind": kind, "title": it["title"],
                             "detail": it.get("detail") or "", "status": it["status"], "priority": it["priority"],
                             "due": it.get("due"), "effort": it.get("effort"), "depends_on": it.get("dependsOn"),
                             "created": it.get("createdAt"), "virtual": False})
        ai = p.get("ai") or {}
        if n_open_tasks == 0:
            for s in (ai.get("nextSteps") or [])[:5]:
                mine.append({**base, "cid": _vcid(p["id"], s["title"]), "item_id": None, "kind": "next_step",
                             "title": s["title"], "detail": s.get("detail") or "", "status": "todo", "priority": "medium",
                             "due": None, "effort": EFFORT_MIN.get(s.get("effort")), "depends_on": None, "created": None,
                             "virtual": True})
        for s in [x for x in (ai.get("needsFromMe") or []) if x.get("priority") == "high"][:2]:
            mine.append({**base, "cid": _vcid(p["id"], s["title"]), "item_id": None, "kind": "needs", "title": s["title"],
                         "detail": s.get("detail") or "", "status": "todo", "priority": "medium", "due": None,
                         "effort": 30, "depends_on": None, "created": None, "virtual": True})
        out.extend(mine)
    return out


def _deadline_pts(due: str | None, day: str) -> tuple[float, int | None]:
    dd, td = _d(due), _d(day)
    if not dd:
        return 0, None
    n = (dd - td).days
    return (55 if n <= 0 else 45 if n <= 2 else 35 if n <= 7 else 20 if n <= 14 else 8 if n <= 30 else 0), n


def score_candidate(c: dict, P: dict, ctx: dict) -> dict:
    """Adds `score`, `breakdown`, `excluded`, `waiting_on` and `blocker_status` to the candidate."""
    bd: list[dict] = []

    def add(key, label, pts):
        if pts:
            bd.append({"k": key, "label": label, "pts": round(pts, 1)})

    day = ctx["day"]
    excluded = None
    dir_pts = 0.0
    dir_labels = []
    due_best = (0.0, "")
    pd, n = _deadline_pts(c["due"], day)
    if pd:
        due_best = (pd, _due_text(n, "Due"))
    pd, n = _deadline_pts(P.get("targetDate"), day)
    if pd * 0.7 > due_best[0]:
        due_best = (pd * 0.7, _due_text(n, "Project target"))

    for d in ctx["dirs"]:
        m = _match(d, c)
        if not m:
            continue
        if d["kind"] in ("pause", "avoid_today"):
            if m == 1.0 or not d["keywords"]:
                excluded = _directive_label(d)
            continue
        if d["kind"] in ("note", "completed", "time_limit", "release"):
            continue
        weight = STRENGTH.get(d["strength"], 60) + SOURCE_BONUS.get(d["source"], 0)
        if d["kind"] == "deadline":
            dp, n = _deadline_pts(d["until_date"], day)
            if dp * m * 0.9 > due_best[0]:
                due_best = (dp * m * 0.9, _due_text(n, "Deadline") + f": {d['summary'] or d['text']}"[:80])
            weight *= 0.5
        pts = weight * m
        dir_pts += pts
        dir_labels.append((pts, _directive_label(d)))
    if dir_pts:
        dir_pts = min(dir_pts, 200.0)
        add("directive", max(dir_labels)[1], dir_pts)

    if c["kind"] == "blocker":
        add("blocking", "An open blocker for this project", 20)
    deps = ctx["dependents"].get(c["item_id"], 0) if c["item_id"] else 0
    if deps:
        add("blocking", f"Unblocks {deps} other task{'s' if deps > 1 else ''}", min(36, 12 * deps))
    add("deadline", due_best[1], due_best[0])
    add("project", f"{P['priority']} priority project", PROJECT_PRIORITY.get(P["priority"], 15))
    if c["kind"] != "blocker":  # blockers default to "high", which would double-count the blocker bonus
        add("priority", f"{c['priority'].title()} priority", TASK_PRIORITY.get(c["priority"], 10))
    if c["status"] == "doing":
        add("momentum", "Already in progress", 14)
    age = _days_ago(c["created"])
    if age and age > 2:
        add("age", f"Sitting for {int(age)} days", min(15, age / 2))
    idle = (P.get("facts") or {}).get("daysIdle")
    if idle and idle > 3:
        add("idle", f"Project idle for {idle} days", min(10, idle / 3))
    impact = 4 + (P.get("progress") or 0) / 10
    if c["kind"] == "blocker" and P["status"] == "Blocked":
        impact += 6
    add("impact", "Impact on the project", impact)
    eff = c["effort"] or 60
    add("effort", "Quick win" if eff <= 30 else "Short task" if eff <= 60 else "Long task", 6 if eff <= 30 else 3 if eff <= 60 else -4 if eff > 240 else 0)
    if eff > ctx["available"] * 0.8:
        add("effort", "Longer than today's time allows", -10)
    if ctx["recent_done"].get(c["pid"]):
        add("momentum", "Recent progress in this project", 6)
    carry = ctx["carry"].get(c["cid"], 0)
    if carry:
        add("carry", f"Planned before and not finished ({carry}x)", min(16, 8 * carry))
    if P["status"] == "Paused":
        add("project", "Project is paused", -25)

    sub = sum(b["pts"] for b in bd)
    waiting_on = None
    dep = ctx["items"].get(c["depends_on"]) if c["depends_on"] else None
    if dep and dep["status"] not in ("done", "resolved", "dismissed"):
        waiting_on = dep["title"]
        steered = dir_pts >= 60  # a chain the owner asked for shouldn't sink below unrelated work just because it is sequential
        add("readiness", f"Waiting on: {dep['title']}"[:100], -(0.2 if steered else 0.45) * max(sub, 0))
    b = ctx["bias"].get(c["cid"])
    if b:
        add("bias", b["reason"] or "Adjusted by you", b["bias"])

    c.update(score=round(sum(x["pts"] for x in bd), 1), breakdown=bd, excluded=excluded, waiting_on=waiting_on)
    c["blocker_status"] = (f"Waiting on: {waiting_on}" if waiting_on else "Blocker to resolve" if c["kind"] == "blocker"
                           else f"Unblocks {deps} task{'s' if deps > 1 else ''}" if deps else "Ready to start")
    c["label"] = label_for(c["score"])
    return c


def _due_text(n: int | None, what: str) -> str:
    if n is None:
        return what
    return f"{what} {'was ' + str(-n) + ' day(s) ago' if n < 0 else 'today' if n == 0 else 'in ' + str(n) + ' day(s)'}"


def rank_candidates(db, projs: list[dict], day: str, ctx: dict | None = None) -> tuple[list[dict], dict]:
    ctx = ctx or _context(db, projs, day)
    by_id = {p["id"]: p for p in projs}
    scored = [score_candidate(c, by_id[c["pid"]], ctx) for c in _candidates(projs)]
    scored = [c for c in scored if not c["excluded"]]
    scored.sort(key=lambda c: -c["score"])
    per, kept = {}, []
    for c in scored:  # at most 12 per project so one big backlog can't crowd out the rest
        per[c["pid"]] = per.get(c["pid"], 0) + 1
        if per[c["pid"]] <= 12:
            kept.append(c)
    return kept, ctx


def why_short(c: dict, n: int = 2) -> str:
    top = sorted([b for b in c["breakdown"] if b["pts"] > 0 and b["k"] not in ("impact", "effort", "priority")],
                 key=lambda b: -b["pts"])[:n]
    return "; ".join(b["label"] for b in top) or "Highest-value ready task for this project"


# ------------------------------------------------------------------ the LLM

def llm_json(prompt: str, schema: dict, model: str, timeout: int = 300) -> dict:
    exe = analyzer.find_claude()
    if not exe:
        raise RuntimeError("Claude Code CLI not found")
    cmd = [exe, "-p", "--output-format", "json", "--no-session-persistence", "--model", model, "--tools", "",
           "--json-schema", json.dumps(schema), "--setting-sources", "user", "--strict-mcp-config"]
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDECODE") and k != "CLAUDE_CODE_ENTRYPOINT"}
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                           cwd=str(DATA), env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise RuntimeError("The AI took too long to answer")
    try:
        out = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError((r.stderr or r.stdout or "No answer from the AI").strip()[:300])
    if out.get("is_error"):
        raise RuntimeError(str(out.get("result") or "The AI returned an error")[:300])
    data = out.get("structured_output")
    if data is None:
        try:
            data = json.loads(out.get("result") or "")
        except ValueError:
            raise RuntimeError("The AI didn't return a structured answer")
    return data


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": props, "required": required or list(props)}


def _arr(props: dict) -> dict:
    return {"type": "array", "items": _obj(props)}


_S = {"type": "string"}
_I = {"type": "integer"}

PLAN_SCHEMA = _obj({
    "headline": {"type": "string", "description": "Under 12 words: today's focus in one line."},
    "focus": {"type": "string", "description": "2-4 sentences, second person: where attention should go today and the biggest immediate goal."},
    "tasks": _arr({
        "id": {"type": "string", "description": "A candidate id from the list, exactly as given."},
        "reason": {"type": "string", "description": "One sentence on why this is on today's list. Concrete; mention directives and blockers."},
        "blocker_status": {"type": "string", "description": "Short: 'Ready', 'Blocking X', or 'Waiting on Y'."},
        "impact": {"type": "string", "description": "Short: what finishing this does for the project."},
        "est_minutes": {"type": "integer", "description": "Realistic minutes of work today."},
    }),
})

DIRECTIVE_SCHEMA = _obj({
    "reply": {"type": "string", "description": "One or two sentences back to the user: what you understood and changed."},
    "unmatched": {"type": "array", "items": _S, "description": "Project names the user mentioned that are not in the list."},
    "directives": _arr({
        "kind": {"type": "string", "enum": DIRECTIVE_KINDS},
        "source": {"type": "string", "enum": ["me", "manager", "client", "collaborator"]},
        "project_id": {"type": "string", "description": "Project id like P3 from the list, or empty."},
        "project_name": {"type": "string"},
        "summary": {"type": "string", "description": "The directive in one short sentence."},
        "strength": {"type": "string", "enum": ["very_high", "high", "medium", "low"]},
        "keywords": {"type": "array", "items": _S, "description": "3-10 lowercase words that identify related tasks (stems like 'scan' help)."},
        "persist": {"type": "string", "enum": ["until_milestone", "until_changed", "today", "this_week", "until_date"]},
        "until_date": {"type": "string", "description": "YYYY-MM-DD, or empty."},
        "until_condition": {"type": "string", "description": "For until_milestone: what 'done' means, e.g. 'QR system operational'."},
        "available_minutes": {"type": "integer", "description": "For time_limit: minutes available today, else 0."},
        "focus_area": {"type": "string", "description": "For focus_area: e.g. 'backend', else empty."},
        "completed_item_ids": {"type": "array", "items": _I, "description": "Item ids from the list the user says are finished."},
        "proposed_tasks": _arr({
            "title": _S, "detail": _S,
            "effort_minutes": _I,
            "priority": {"type": "string", "enum": ["high", "medium", "low"]},
            "existing_item_id": {"type": "integer", "description": "An item id from the list this step already matches, else 0."},
            "depends_on_index": {"type": "integer", "description": "Index (0-based) of an earlier proposed task this needs first, else -1."},
        }),
    }),
})


def _proj_lines(projs: list[dict], limit_items: int = 0) -> str:
    lines = []
    for i, p in enumerate(projs):
        f = p.get("facts") or {}
        summ = ((p.get("ai") or {}).get("summary") or p.get("oneLiner") or "")[:220].replace("\n", " ")
        tgt = f" target {p['targetDate']}" if p.get("targetDate") else ""
        lines.append(f"P{i + 1} {p['name']}: {p['status']}, {p['phase']} {p['progress']}%, {p['priority']} priority{tgt}, "
                     f"idle {f.get('daysIdle', '?')}d, {len(p['blockers'])} blockers. {summ}")
        if limit_items:
            for k, key in (("task", "tasks"), ("bug", "bugs"), ("blocker", "blockers")):
                its = [x for x in p.get(key, []) if x.get("id") is not None]
                shown = [x for x in its if x["status"] in OPEN[k]][:limit_items] + [x for x in its if x["status"] == "done"][:4]
                for it in shown:
                    lines.append(f"    [{it['id']}] {k} {it['status']}: {it['title'][:90]}")
    return "\n".join(lines)


def _events_text(db, day: str) -> str:
    since = (_d(day) - timedelta(days=3)).isoformat()
    with db.conn() as c:
        rows = c.execute("SELECT day, kind, text FROM planner_events WHERE day>=? AND kind!='complete' ORDER BY id DESC LIMIT 14",
                         (since,)).fetchall()
    return "\n".join(f"- {r['day']} {r['kind']}: {r['text']}" for r in reversed(rows)) or "(none)"


def _dir_text(dirs: list[dict]) -> str:
    out = []
    for d in dirs:
        bits = [f"[{SOURCE_LABEL.get(d['source'], 'Your')} / {d['kind']} / {d['strength']}]", d["summary"] or d["text"]]
        if d["project_name"]:
            bits.append(f"(project: {d['project_name']})")
        if d["until_condition"]:
            bits.append(f"until: {d['until_condition']}")
        elif d["until_date"]:
            bits.append(f"until {d['until_date']}")
        out.append("- " + " ".join(bits))
    return "\n".join(out) or "(none)"


def _prev_summary(db, day: str) -> str:
    with db.conn() as c:
        r = c.execute("SELECT * FROM plan_days WHERE day<? AND generated_at IS NOT NULL ORDER BY day DESC LIMIT 1", (day,)).fetchone()
        if not r:
            return "(no earlier plan)"
        t = c.execute("SELECT status, title FROM plan_tasks WHERE day=?", (r["day"],)).fetchall()
    done = [x["title"] for x in t if x["status"] == "done"]
    left = [x["title"] for x in t if x["status"] in ("todo", "doing")]
    return f"{r['day']}: {r['headline']}. Done: {'; '.join(done[:5]) or 'none'}. Unfinished: {'; '.join(left[:5]) or 'none'}."


def llm_plan(db, projs, ranked, ctx, kept, slots, budget, model) -> dict:
    pool = ranked[:LLM_POOL]
    weekday = _d(ctx["day"]).strftime("%A")
    rows = []
    for c in pool:
        facts = "; ".join(f"{b['label']} ({b['pts']:+.0f})" for b in sorted(c["breakdown"], key=lambda b: -abs(b["pts"]))[:4])
        rows.append(f"{c['cid']} | {c['pname']} | {c['kind']} | {c['title'][:100]} | prio {c['priority']} | {c['status']} | "
                    f"effort {c['effort'] or '?'}m | score {c['score']:.0f} | {c['blocker_status']} | {facts}")
    keep_txt = "\n".join(f"- {t['project_name']}: {t['title']} ({t['status']})" for t in kept) or "(none)"
    prompt = f"""You are the daily planner for one person who runs several software and hardware projects. Today is {weekday} {ctx['day']}.
Decide what they should work on TODAY and write the plan. Be realistic and specific; this is a short list, not the backlog.

How the candidates were scored (already done for you): directives from the owner/manager/client weigh most, then tasks blocking other tasks, deadlines, project and task priority, time since last worked on, impact, effort and readiness. Respect that ranking. You may reorder or drop a candidate only for a clear reason (dependencies, time budget, a directive's wording), and you must never invent a task: choose ids from the candidate list only.

ACTIVE DIRECTIVES (strongest influence; honour their wording, for example "until the QR system is operational"):
{_dir_text(ctx['dirs'])}

PROJECTS:
{_proj_lines(projs)}

ALREADY ON TODAY'S LIST (do not repeat):
{keep_txt}

RECENT OVERRIDES AND SKIPS BY THE USER (learn from these):
{_events_text(db, ctx['day'])}

YESTERDAY: {_prev_summary(db, ctx['day'])}

TIME AVAILABLE TODAY: {ctx['available']} minutes in total; about {budget} minutes are still unplanned.

CANDIDATES (id | project | kind | title | priority | status | effort | score | readiness | top score factors):
{chr(10).join(rows)}

Pick {min(MIN_TASKS, slots)} to {slots} candidates, most important first, whose estimated minutes roughly fit the unplanned time. A candidate that is waiting on something is only valid if the thing it waits on is also picked earlier. If a directive makes one project today's priority, most picks should come from it, while a very urgent item from another project may still earn a place.
In `focus`, speak to the user ("you"), name the project that deserves most attention and the one concrete goal to reach today, and mention the directive behind it if there is one. Do not mention scores or ids."""
    return llm_json(prompt, PLAN_SCHEMA, model)


# ------------------------------------------------------------------ building a plan

def _insert_task(c, day: str, rank: int, cand: dict | None, *, origin: str, **kw) -> int:
    t = now()
    g = (lambda k, d="": kw.get(k, (cand or {}).get(k, d)))
    return c.execute(
        "INSERT INTO plan_tasks (day, rank, cid, project_key, project_name, item_id, title, priority, est_minutes, reason,"
        " blocker_status, impact, status, score, breakdown, origin, accepted, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'todo', ?, ?, ?, ?, ?, ?)",
        (day, rank, g("cid"), kw.get("project_key", (cand or {}).get("pid", "")), kw.get("project_name", (cand or {}).get("pname", "")),
         g("item_id", None), kw.get("title") or cand["title"], kw.get("priority") or (cand or {}).get("label", "Medium"),
         kw.get("est_minutes"), kw.get("reason", ""), kw.get("blocker_status", ""), kw.get("impact", ""),
         (cand or {}).get("score", 0), json.dumps((cand or {}).get("breakdown", [])), origin, kw.get("accepted", 0), t, t)).lastrowid


def _rules_pick(ranked: list[dict], slots: int, budget: int, ctx: dict) -> list[dict]:
    picks, used, per, blockers = [], 0, {}, 0
    boosted = {c["pid"] for c in ranked if any(b["k"] == "directive" and b["pts"] >= 40 for b in c["breakdown"])}
    for c in ranked:
        if len(picks) >= slots:
            break
        if c["waiting_on"] and not any(p["title"] == c["waiting_on"] for p in picks):
            continue
        est = c["effort"] or 60
        if len(picks) >= 2 and used + est > budget * 1.1:
            continue
        if per.get(c["pid"], 0) >= (5 if c["pid"] in boosted else 3):
            continue
        if c["kind"] == "blocker" and blockers >= 2 and c["pid"] not in boosted:
            continue
        blockers += c["kind"] == "blocker"
        picks.append(c)
        per[c["pid"]] = per.get(c["pid"], 0) + 1
        used += est
    return picks


def _rules_focus(picks: list[dict], ctx: dict) -> tuple[str, str]:
    if not picks:
        return "Nothing urgent today", "There's nothing ready to work on. Add a task or tell the AI what changed."
    names: list[str] = []
    for p in picks:
        if p["pname"] not in names:
            names.append(p["pname"])
    top = picks[0]
    strong = [d for d in ctx["dirs"] if d["kind"] in ("focus", "blocker", "focus_area", "deadline")]
    parts = [f"{names[0]} should get most of your attention today."]
    if strong:
        parts.append(f"{SOURCE_LABEL.get(strong[0]['source'], 'Your')} directive: {strong[0]['summary'].rstrip('.') or strong[0]['text']}.")
    t = top["title"]
    t = t[0].lower() + t[1:] if len(t) > 1 and t[1].islower() else t
    goal = {"blocker": f"clear the blocker “{top['title']}”", "needs": f"settle “{top['title']}”"}.get(top["kind"], t)
    parts.append(f"The biggest immediate goal is to {goal}.")
    if len(names) > 1:
        parts.append(f"After that, {names[1]} has the next most pressing work.")
    return f"{names[0]}: {top['title']}"[:90], " ".join(parts)


def _est(c: dict) -> int:
    return int(c.get("effort") or 60)


def generate(db, projs: list[dict], day: str | None = None, model: str = "sonnet", use_llm: bool = True,
             progress=None) -> dict:
    """(Re)build `day`'s plan. Finished, in-progress, accepted and manual tasks stay; the rest is re-chosen."""
    day = day or today()
    progress = progress or (lambda m: None)
    with LOCK:
        with db.conn() as c:
            c.execute("DELETE FROM plan_tasks WHERE day=? AND status='todo' AND accepted=0 AND origin IN ('ai','rules')", (day,))
            kept = [dict(r) for r in c.execute("SELECT * FROM plan_tasks WHERE day=? ORDER BY rank, id", (day,))]
        progress("Scoring every open task")
        ranked, ctx = rank_candidates(db, projs, day)
        taken_titles = {k["title"].lower() for k in kept}
        ranked = [c for c in ranked if ctx["taken"].get(c["cid"]) is None and c["title"].lower() not in taken_titles]
        pending = sum((k["est_minutes"] or 60) for k in kept if k["status"] in ("todo", "doing"))
        budget = max(0, ctx["available"] - pending)
        slots = MAX_TASKS - sum(1 for k in kept if k["status"] in ("todo", "doing"))
        picks, extra, source, warning = [], {}, "rules", None
        headline = focus = ""
        if slots > 0 and ranked:
            if use_llm:
                try:
                    progress("Asking the AI to write today's plan")
                    out = llm_plan(db, projs, ranked, ctx, [k for k in kept if k["status"] != "skipped"], slots, budget, model)
                    by_cid = {c["cid"]: c for c in ranked}
                    for t in out.get("tasks") or []:
                        c = by_cid.get(t.get("id"))
                        if c and c not in picks and len(picks) < slots:
                            picks.append(c)
                            extra[c["cid"]] = t
                    headline, focus, source = (out.get("headline") or "").strip(), (out.get("focus") or "").strip(), "ai"
                    # The AI may reorder, but not drop the very top, ready, deterministic candidates.
                    for i, c in enumerate([x for x in ranked[:3] if not x["waiting_on"]]):
                        if c not in picks:
                            picks.insert(min(i, len(picks)), c)
                    picks = picks[:slots]
                    if not picks:
                        raise RuntimeError("The AI chose nothing valid")
                except Exception as e:
                    warning = f"AI planning failed ({str(e)[:160]}); showing the rules-based plan."
                    picks, extra, source = [], {}, "rules"
            if not picks:
                picks = _rules_pick(ranked, slots, budget, ctx)
        if not focus:
            headline, focus = _rules_focus(picks or [], ctx)
        rank0 = max([k["rank"] for k in kept], default=-1) + 1
        with db.conn() as c:
            for i, cand in enumerate(picks):
                x = extra.get(cand["cid"], {})
                est = int(x.get("est_minutes") or 0) or _est(cand)
                _insert_task(c, day, rank0 + i, cand, origin="ai" if x else "rules", est_minutes=max(5, min(est, 600)),
                             reason=(x.get("reason") or why_short(cand)).strip(),
                             blocker_status=(x.get("blocker_status") or cand["blocker_status"]).strip(),
                             impact=(x.get("impact") or "").strip())
            pool = [{"cid": r["cid"], "title": r["title"], "project": r["pname"], "score": r["score"], "label": r["label"]}
                    for r in ranked[:12]]
            snap = [{"id": d["id"], "summary": d["summary"] or d["text"], "source": d["source"], "kind": d["kind"],
                     "project": d["project_name"]} for d in ctx["dirs"] if d["kind"] not in ("completed", "release")]
            c.execute(
                "INSERT INTO plan_days (day, headline, focus, available_min, generated_at, model, source, candidates, directives)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(day) DO UPDATE SET headline=excluded.headline, focus=excluded.focus,"
                " available_min=excluded.available_min, generated_at=excluded.generated_at, model=excluded.model,"
                " source=excluded.source, candidates=excluded.candidates, directives=excluded.directives",
                (day, headline[:200], focus, ctx["available"], now(), model if source == "ai" else None, source,
                 json.dumps(pool), json.dumps(snap)))
            # Reorder so unfinished work reads top-down: in progress, then todo, then done.
            _renumber(c, day)
    return {"source": source, "warning": warning, "count": len(picks)}


def _renumber(c, day: str):
    rows = c.execute("SELECT id, status FROM plan_tasks WHERE day=? ORDER BY rank, id", (day,)).fetchall()
    order = {"doing": 0, "todo": 1, "moved": 2, "skipped": 2, "done": 3}
    for i, r in enumerate(sorted(rows, key=lambda r: order.get(r["status"], 1))):
        c.execute("UPDATE plan_tasks SET rank=? WHERE id=?", (i, r["id"]))


def ensure_today(db, projs: list[dict]) -> None:
    """First look at the day: build a rules-only plan at once so the dashboard is never empty. 'Regenerate' brings in the AI."""
    day = today()
    with LOCK:
        with db.conn() as c:
            r = c.execute("SELECT generated_at FROM plan_days WHERE day=?", (day,)).fetchone()
        if r is None or r["generated_at"] is None:
            generate(db, projs, day, use_llm=False)


# ------------------------------------------------------------------ directives from natural language

QR_PLAYBOOK = [
    "Define QR code data structure",
    "Generate unique QR IDs for material containers/bins",
    "Build QR scanning workflow",
    "Connect scans to material movement records",
    "Test Warehouse -> MFG Staging transfers",
    "Test MFG Staging -> Grade C transfers",
    "Test Grade C -> Grade B transfers",
    "Add error handling and audit logging",
    "Test the full workflow",
    "Document remaining validation requirements",
]


def _playbook_text(projs: list[dict], text: str) -> str:
    if not re.search(r"\bqr\b", text, re.I) or not any(p["name"].lower() == "materialos" for p in projs):
        return ""
    steps = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(QR_PLAYBOOK))
    return f"""
OWNER'S REFERENCE BREAKDOWN for getting the MaterialOS QR system operational. When the instruction is about that, use exactly these steps as proposed_tasks, in this order, each depending on the one before where it logically must. Set existing_item_id when the project already has a matching item. Do not invent extra steps and do not drop any:
{steps}
"""


def parse_directive(db, projs: list[dict], text: str, model: str) -> dict:
    day = today()
    weekday = _d(day).strftime("%A")
    prompt = f"""You manage the planning context for one person who runs several projects. They just wrote an instruction in plain English. Turn it into structured directives. Today is {weekday} {day}.

Rules:
- One sentence can hold several directives; return each separately. A "reply" of one or two sentences confirms what you understood.
- Match projects to the list by name (ids P1..Pn). A project not in the list goes in `unmatched` and the directive gets an empty project_id (keep the name in project_name).
- Who said it: "my boss", "my manager" -> manager; a client or customer -> client; a teammate -> collaborator; otherwise me.
- Kinds: focus (work on / prioritise something), pause (stop working on a project or area for a while), avoid_today (do not work on it today), deadline (must be ready by a date; give until_date as YYYY-MM-DD, resolving "Friday" and similar from today's date), time_limit (set available_minutes), focus_area (a kind of work such as backend, frontend or testing; give keywords), blocker (something blocks work; make it a very_high focus on the fix), completed (they finished something; list matching item ids in completed_item_ids and keep a summary), note (context that doesn't change priorities), release (they say the earlier directive no longer applies; name the project).
- strength: an instruction from a manager or client, or words like "must", "blocking", "urgent", "ready by" -> very_high or high; casual preferences -> medium.
- persist: "today" or "only today" -> today; "this week" -> this_week with until_date at the end of the week; a deadline -> until_date; "until it's operational / done / working" or open-ended work on a goal -> until_milestone (describe it in until_condition); otherwise until_changed.
- keywords: lowercase terms that appear in the titles of related tasks. Include word stems ("scan", "qr"). Leave empty for a whole-project directive.
- proposed_tasks: when the instruction states a goal that needs concrete work, break it into 5 to 10 ordered, actionable steps with realistic effort_minutes. Reuse an existing item (set existing_item_id) instead of duplicating one, and use depends_on_index when a step really needs an earlier one. Never propose tasks that merely restate the project's existing plan, and never propose anything for pause, avoid_today, time_limit, completed, note or release.
- If the user gave the steps themselves, use their steps in their order.
{_playbook_text(projs, text)}
PROJECTS (with item ids in [brackets]):
{_proj_lines(projs, limit_items=22)}

CURRENT DIRECTIVES:
{_dir_text(active_directives(db, day))}

INSTRUCTION:
{text}"""
    return llm_json(prompt, DIRECTIVE_SCHEMA, model)


def _resolve_project(projs: list[dict], pid: str, name: str) -> dict | None:
    m = re.fullmatch(r"P(\d+)", (pid or "").strip(), re.I)
    if m and 0 < int(m.group(1)) <= len(projs):
        return projs[int(m.group(1)) - 1]
    norm = lambda s: re.sub(r"[^a-z0-9]+", "", (s or "").lower())
    n = norm(name)
    if len(n) < 3:
        return None
    for p in projs:
        pn = norm(p["name"])
        if pn == n or (len(pn) >= 4 and (pn in n or n in pn)):
            return p
    hit = difflib.get_close_matches(n, [norm(p["name"]) for p in projs], 1, 0.82)
    return next((p for p in projs if norm(p["name"]) == hit[0]), None) if hit else None


def apply_directives(db, projs: list[dict], text: str, parsed: dict) -> dict:
    """Store the parsed directives and any steps they ask for. Existing project items are never deleted or re-prioritised."""
    day = today()
    unmatched = list(parsed.get("unmatched") or [])
    made = {"directives": 0, "tasks_added": 0, "tasks_linked": 0, "completed": 0}
    with LOCK:
        for raw in parsed.get("directives") or []:
            kind = raw.get("kind") if raw.get("kind") in DIRECTIVE_KINDS else "note"
            p = _resolve_project(projs, raw.get("project_id"), raw.get("project_name"))
            pname = p["name"] if p else (raw.get("project_name") or "").strip()
            if raw.get("project_name") and not p and raw["project_name"] not in unmatched:
                unmatched.append(raw["project_name"])
            keywords = sorted({k.strip().lower() for k in raw.get("keywords") or [] if k and len(k.strip()) > 1})
            if not p and pname:  # still let the name itself pull in related work
                keywords = sorted(set(keywords) | {pname.lower()})
            persist = raw.get("persist") if raw.get("persist") in ("until_milestone", "until_changed", "today", "this_week", "until_date") else "until_changed"
            until = raw.get("until_date") or None
            if until and not _d(until):
                until = None
            if persist in ("this_week", "until_date") and not until:
                until = (_d(day) + timedelta(days=7 - _d(day).weekday() - 1)).isoformat() if persist == "this_week" else None
                persist = persist if until else "until_changed"
            if kind == "deadline" and until:
                persist = "until_date"

            if kind == "release":
                with db.conn() as c:
                    for r in c.execute("SELECT id, project_key, keywords FROM directives WHERE active=1").fetchall():
                        if (p and r["project_key"] == p["id"]) or (not p and pname and pname.lower() in r["keywords"]):
                            c.execute("UPDATE directives SET active=0, ended_at=?, ended_why='Released by you' WHERE id=?", (now(), r["id"]))
                made["directives"] += 1
                continue

            items = {it["id"]: (pp, it) for pp in projs for k in ("tasks", "bugs", "blockers") for it in pp.get(k, []) if it.get("id") is not None}
            track: list[int] = []
            if p and kind in ("focus", "blocker", "deadline", "focus_area"):
                made_ids: list[int] = []
                existing_titles = {_ai_key(it["title"]): it["id"] for k in ("tasks", "bugs") for it in p.get(k, [])
                                   if it.get("id") is not None and it["status"] != "dismissed"}
                for t in raw.get("proposed_tasks") or []:
                    title = (t.get("title") or "").strip()
                    if not title:
                        made_ids.append(0)
                        continue
                    ex = t.get("existing_item_id") or 0
                    if ex not in items or items[ex][0]["id"] != p["id"]:
                        ex = existing_titles.get(_ai_key(title), 0)
                    if ex:
                        made["tasks_linked"] += 1
                        made_ids.append(ex)
                        if items[ex][1]["status"] != "done":
                            track.append(ex)
                        continue
                    di = t.get("depends_on_index", -1)
                    dep = made_ids[di] if isinstance(di, int) and 0 <= di < len(made_ids) and made_ids[di] else None
                    iid = db.add_item(p["id"], {"title": title, "detail": t.get("detail") or f"Added by the planner: {raw.get('summary') or text}"[:300],
                                                "priority": t.get("priority") or "medium", "effort_min": t.get("effort_minutes"),
                                                "depends_on": dep, "via": "planner"})
                    existing_titles[_ai_key(title)] = iid
                    made_ids.append(iid)
                    track.append(iid)
                    made["tasks_added"] += 1

            if kind == "completed":
                for iid in raw.get("completed_item_ids") or []:
                    if iid in items and items[iid][1]["status"] not in ("done", "resolved"):
                        db.update_item(iid, {"status": "resolved" if _is_issue(projs, {"item_id": iid}) else "done"})
                        made["completed"] += 1
                        with db.conn() as c:
                            c.execute("UPDATE plan_tasks SET status='done', completed_at=?, updated_at=? WHERE item_id=? AND day=? AND status!='done'",
                                      (now(), now(), iid, day))

            with db.conn() as c:
                if kind in ("focus", "pause", "avoid_today", "time_limit", "focus_area", "blocker"):
                    # A newer directive about the same thing supersedes the old one.
                    for r in c.execute("SELECT id, keywords FROM directives WHERE active=1 AND kind=? AND project_key=?",
                                       (kind, p["id"] if p else "")).fetchall():
                        if kind == "time_limit" or json.loads(r["keywords"]) == keywords:
                            c.execute("UPDATE directives SET active=0, ended_at=?, ended_why='Replaced by a newer directive' WHERE id=?", (now(), r["id"]))
                c.execute(
                    "INSERT INTO directives (text, summary, project_key, project_name, kind, source, strength, keywords, persist,"
                    " until_date, until_condition, available_minutes, focus_area, track_item_ids, active, created_at, created_day)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                    (text[:1000], (raw.get("summary") or text)[:300], p["id"] if p else "", pname, kind,
                     raw.get("source") if raw.get("source") in SOURCE_BONUS else "me",
                     raw.get("strength") if raw.get("strength") in STRENGTH else "high", json.dumps(keywords),
                     persist if not (persist == "until_milestone" and not track) else "until_changed", until,
                     (raw.get("until_condition") or "")[:200], raw.get("available_minutes") or None,
                     (raw.get("focus_area") or "")[:60], json.dumps(track), now(), day))
                made["directives"] += 1
        with db.conn() as c:
            c.execute("INSERT INTO planner_events (day, kind, text, created_at) VALUES (?, 'note', ?, ?)", (day, text[:500], now()))
    return {"reply": (parsed.get("reply") or "").strip(), "unmatched": unmatched, **made}


# ------------------------------------------------------------------ user controls

def _event(c, day, kind, text, task_id=None):
    c.execute("INSERT INTO planner_events (day, kind, task_id, text, created_at) VALUES (?, ?, ?, ?, ?)",
              (day, kind, task_id, text[:500], now()))


def _task_key(t: dict) -> str:
    return t["cid"] or f"t{t['id']}"


def _set_bias(c, key: str, delta: float, reason: str, days: int, day: str, replace: bool = True):
    cur = c.execute("SELECT bias FROM task_bias WHERE task_key=?", (key,)).fetchone()
    val = delta if (replace or not cur) else cur["bias"] + delta
    c.execute("INSERT INTO task_bias (task_key, bias, reason, expires, updated_at) VALUES (?, ?, ?, ?, ?)"
              " ON CONFLICT(task_key) DO UPDATE SET bias=excluded.bias, reason=excluded.reason, expires=excluded.expires, updated_at=excluded.updated_at",
              (key, max(-80, min(80, val)), reason, (_d(day) + timedelta(days=days)).isoformat(), now()))


def _sync_item(db, t: dict, status: str):
    if t.get("item_id"):
        db.update_item(t["item_id"], {"status": status})


def task_action(db, projs: list[dict], tid: int, action: str, body: dict) -> None:
    after: list = []   # item updates run once this connection has committed, so SQLite never sees two writers
    with LOCK:
        _task_action(db, projs, tid, action, body, after)
        for fn in after:
            fn()


def _task_action(db, projs, tid, action, body, after) -> None:
    day = today()
    with db.conn() as c:
        r = c.execute("SELECT * FROM plan_tasks WHERE id=?", (tid,)).fetchone()
        if r is None:
            raise ValueError("That task is no longer in the plan")
        t = dict(r)
        label = f"'{t['title']}' ({t['project_name']})" if t["project_name"] else f"'{t['title']}'"
        stamp = (now(), tid)
        if action == "start":
            c.execute("UPDATE plan_tasks SET status='doing', accepted=1, updated_at=? WHERE id=?", stamp)
            after.append(lambda: _sync_item(db, t, "doing"))
            _event(c, day, "start", f"Started {label}", tid)
        elif action == "complete":
            c.execute("UPDATE plan_tasks SET status='done', completed_at=?, updated_at=? WHERE id=?", (now(), now(), tid))
            after.append(lambda: _sync_item(db, t, "resolved" if _is_issue(projs, t) else "done"))
            _event(c, day, "complete", f"Completed {label}", tid)
        elif action == "reopen":
            c.execute("UPDATE plan_tasks SET status='todo', completed_at=NULL, updated_at=? WHERE id=?", stamp)
            after.append(lambda: _sync_item(db, t, "open" if _is_issue(projs, t) else "todo"))
        elif action == "accept":
            c.execute("UPDATE plan_tasks SET accepted=1, updated_at=? WHERE id=?", stamp)
            _set_bias(c, _task_key(t), 15, "You accepted this recommendation", 3, day)
            _event(c, day, "accept", f"Accepted {label}", tid)
        elif action == "skip":
            why = (body.get("reason") or "").strip()
            c.execute("UPDATE plan_tasks SET status='skipped', skip_reason=?, updated_at=? WHERE id=?", (why, now(), tid))
            _set_bias(c, _task_key(t), -30, "You skipped this recently", 2, day)
            _event(c, day, "skip", f"Skipped {label}" + (f" because: {why}" if why else ""), tid)
        elif action == "move":
            tomorrow = (_d(day) + timedelta(days=1)).isoformat()
            c.execute("UPDATE plan_tasks SET status='moved', updated_at=? WHERE id=?", stamp)
            c.execute("INSERT INTO plan_days (day) VALUES (?) ON CONFLICT(day) DO NOTHING", (tomorrow,))
            n = c.execute("SELECT COALESCE(MAX(rank), -1) + 1 FROM plan_tasks WHERE day=?", (tomorrow,)).fetchone()[0]
            if not c.execute("SELECT 1 FROM plan_tasks WHERE day=? AND cid=? AND cid!=''", (tomorrow, t["cid"])).fetchone():
                _insert_task(c, tomorrow, n, None, origin="moved", cid=t["cid"], project_key=t["project_key"],
                             project_name=t["project_name"], item_id=t["item_id"], title=t["title"], priority=t["priority"],
                             est_minutes=t["est_minutes"], reason="Moved here from today.", blocker_status=t["blocker_status"],
                             impact=t["impact"], accepted=1)
            _set_bias(c, _task_key(t), 25, "You moved this to tomorrow", 2, day)
            _event(c, day, "move", f"Moved {label} to tomorrow", tid)
        elif action == "priority":
            new = body.get("priority")
            if new not in LEVELS:
                raise ValueError("Unknown priority")
            diff = LEVELS.index(new) - LEVELS.index(t["priority"])
            c.execute("UPDATE plan_tasks SET priority=?, updated_at=? WHERE id=?", (new, now(), tid))
            if diff:
                _set_bias(c, _task_key(t), 20 * diff, f"You set this to {new}", 5, day, replace=False)
            _event(c, day, "reprioritize", f"Changed {label} from {t['priority']} to {new}", tid)
        elif action in ("up", "down"):
            rows = c.execute("SELECT id, rank FROM plan_tasks WHERE day=? AND status IN ('todo','doing') ORDER BY rank, id", (t["day"],)).fetchall()
            ids = [x["id"] for x in rows]
            i = ids.index(tid) if tid in ids else -1
            j = i - 1 if action == "up" else i + 1
            if i < 0 or not 0 <= j < len(ids):
                return
            a, b = rows[i], rows[j]
            c.execute("UPDATE plan_tasks SET rank=? WHERE id=?", (b["rank"], a["id"]))
            c.execute("UPDATE plan_tasks SET rank=? WHERE id=?", (a["rank"], b["id"]))
            other = c.execute("SELECT title FROM plan_tasks WHERE id=?", (b["id"],)).fetchone()["title"]
            if action == "up":
                _set_bias(c, _task_key(t), 10, "You moved this up", 3, day, replace=False)
            _event(c, day, "reorder", f"Moved {label} {'above' if action == 'up' else 'below'} '{other}'", tid)
        elif action == "est":
            c.execute("UPDATE plan_tasks SET est_minutes=?, updated_at=? WHERE id=?", (max(5, min(int(body.get("minutes") or 60), 600)), now(), tid))
        elif action == "delete":
            if t["origin"] != "manual":
                raise ValueError("Only tasks you added can be removed; skip it instead")
            c.execute("DELETE FROM plan_tasks WHERE id=?", (tid,))
        else:
            raise ValueError("Unknown action")


def _is_issue(projs: list[dict], t: dict) -> bool:
    return any(it.get("id") == t["item_id"] for p in projs for k in ("bugs", "blockers") for it in p.get(k, []))


def add_manual(db, projs: list[dict], body: dict) -> int:
    title = (body.get("title") or "").strip()
    if not title:
        raise ValueError("Give the task a name")
    day = today()
    p = next((x for x in projs if x["id"] == body.get("project_key")), None)
    level = body.get("priority") if body.get("priority") in LEVELS else "Medium"
    est = max(5, min(int(body.get("est_minutes") or 60), 600))
    with LOCK:
        iid = None
        if p:
            iid = db.add_item(p["id"], {"title": title, "priority": {"Critical": "high", "High": "high", "Medium": "medium", "Low": "low"}[level],
                                        "effort_min": est, "via": "planner"})
        with db.conn() as c:
            c.execute("INSERT INTO plan_days (day) VALUES (?) ON CONFLICT(day) DO NOTHING", (day,))
            n = c.execute("SELECT COALESCE(MAX(rank), -1) + 1 FROM plan_tasks WHERE day=?", (day,)).fetchone()[0]
            tid = _insert_task(c, day, n, None, origin="manual", cid=f"i{iid}" if iid else "", project_key=p["id"] if p else "",
                               project_name=p["name"] if p else "", item_id=iid, title=title, priority=level, est_minutes=est,
                               reason="Added by you.", blocker_status="Ready to start", accepted=1)
            _event(c, day, "override", f"Added '{title}' to today by hand", tid)
            _renumber(c, day)
    return tid


def pick_candidate(db, projs: list[dict], cid: str) -> int:
    """Put a 'next in line' candidate on today's list, overriding the AI's choice."""
    day = today()
    with LOCK:
        ranked, ctx = rank_candidates(db, projs, day)
        c = next((x for x in ranked if x["cid"] == cid), None)
        if c is None:
            raise ValueError("That task is no longer a candidate")
        with db.conn() as conn:
            conn.execute("DELETE FROM plan_tasks WHERE day=? AND cid=? AND status IN ('skipped','moved')", (day, cid))
            n = conn.execute("SELECT COALESCE(MAX(rank), -1) + 1 FROM plan_tasks WHERE day=?", (day,)).fetchone()[0]
            tid = _insert_task(conn, day, n, c, origin="manual", est_minutes=_est(c), reason=f"You chose this. {why_short(c)}.",
                               blocker_status=c["blocker_status"], accepted=1)
            _set_bias(conn, cid, 25, "You chose this over the AI's list", 3, day)
            _event(conn, day, "override", f"Chose '{c['title']}' ({c['pname']}) to work on today", tid)
            _renumber(conn, day)
    return tid


# ------------------------------------------------------------------ what the front end reads

def _sync_done(db, projs: list[dict], day: str):
    """A task finished on the project page counts as done in today's plan."""
    state = {it["id"]: it["status"] for p in projs for k in ("tasks", "bugs", "blockers") for it in p.get(k, []) if it.get("id") is not None}
    with db.conn() as c:
        for r in c.execute("SELECT id, item_id FROM plan_tasks WHERE day=? AND item_id IS NOT NULL AND status IN ('todo','doing')", (day,)).fetchall():
            if state.get(r["item_id"]) in ("done", "resolved"):
                c.execute("UPDATE plan_tasks SET status='done', completed_at=?, updated_at=? WHERE id=?", (now(), now(), r["id"]))


def _task_out(r) -> dict:
    d = _row(r, "breakdown")
    d["accepted"] = bool(d["accepted"])
    return d


def payload(db, projs: list[dict]) -> dict:
    day = today()
    ensure_today(db, projs)
    _sync_done(db, projs, day)
    ranked, ctx = rank_candidates(db, projs, day)
    with db.conn() as c:
        plan = c.execute("SELECT * FROM plan_days WHERE day=?", (day,)).fetchone()
        tasks = [_task_out(r) for r in c.execute("SELECT * FROM plan_tasks WHERE day=? ORDER BY rank, id", (day,))]
    in_plan = {t["cid"] for t in tasks if t["cid"]}
    nxt = [{"cid": x["cid"], "title": x["title"], "project": x["pname"], "pid": x["pid"], "score": x["score"], "label": x["label"],
            "why": why_short(x), "breakdown": x["breakdown"], "waiting_on": x["waiting_on"]}
           for x in ranked if x["cid"] not in in_plan][:6]
    live = [t for t in tasks if t["status"] not in ("skipped", "moved")]
    planned = sum(t["est_minutes"] or 0 for t in live)
    done = sum(1 for t in live if t["status"] == "done")
    dirs = [{k: d[k] for k in ("id", "summary", "text", "project_name", "project_key", "kind", "source", "strength", "persist",
                               "until_date", "until_condition", "focus_area", "available_minutes", "created_day")}
            | {"keywords": d["keywords"], "tracked": len(d["track_item_ids"])} for d in ctx["dirs"]]
    return {
        "day": day,
        "plan": ({"headline": plan["headline"], "focus": plan["focus"], "source": plan["source"], "model": plan["model"],
                  "generatedAt": plan["generated_at"]} if plan and plan["generated_at"] else None),
        "tasks": tasks, "next": nxt, "directives": dirs, "availableMin": ctx["available"],
        "summary": {"planned": len(live), "done": done, "doing": sum(1 for t in live if t["status"] == "doing"),
                    "plannedMin": planned, "doneMin": sum(t["est_minutes"] or 0 for t in live if t["status"] == "done")},
    }


def history(db, limit: int = 30) -> list[dict]:
    out = []
    with db.conn() as c:
        for p in c.execute("SELECT * FROM plan_days WHERE generated_at IS NOT NULL ORDER BY day DESC LIMIT ?", (limit,)):
            tasks = [_task_out(r) for r in c.execute("SELECT * FROM plan_tasks WHERE day=? ORDER BY rank, id", (p["day"],))]
            live = [t for t in tasks if t["status"] not in ("skipped", "moved")]
            worked = []
            for t in tasks:
                if t["status"] in ("done", "doing") and t["project_name"] and t["project_name"] not in worked:
                    worked.append(t["project_name"])
            try:
                dirs = json.loads(p["directives"] or "[]")
            except ValueError:
                dirs = []
            out.append({"day": p["day"], "headline": p["headline"], "focus": p["focus"], "source": p["source"],
                        "tasks": [{k: t[k] for k in ("id", "title", "project_name", "priority", "status", "est_minutes", "skip_reason")} for t in tasks],
                        "planned": len(live), "done": sum(1 for t in live if t["status"] == "done"),
                        "unfinished": sum(1 for t in live if t["status"] in ("todo", "doing")),
                        "skipped": sum(1 for t in tasks if t["status"] == "skipped"),
                        "moved": sum(1 for t in tasks if t["status"] == "moved"),
                        "projects": worked, "directives": dirs})
    return out
