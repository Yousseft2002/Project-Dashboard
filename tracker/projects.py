"""The canonical project model the dashboard renders.

Every digital project, whatever it was built from (scanner facts, AI analysis, owner edits, task items),
is normalised into one shape here, so the front end never has to know where a field came from:

    id, name, description, oneLiner, type, status, phase, phaseProgress, progress, priority, health,
    previewImage, previewDevice, liveUrl, previewUrl, githubUrl, technologies, goals, notes,
    tasks, milestones, blockers, bugs, taskCounts, createdAt, updatedAt, targetDate,
    sources {field: "you" | "ai" | "estimate" | "scan"}, ai {...}, facts {...}

Owner edits win, then the latest AI analysis, then an estimate from the scan.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .analyzer import PHASES, TYPES
from .previews import preview_path

STATUSES = ["Active", "Blocked", "Paused", "Completed"]
PRIORITIES = ["High", "Medium", "Low"]
# Analyses written before the 7-stage lifecycle used a launch-oriented scale.
OLD_PHASES = {"Prototype": "Development", "MVP": "Development", "Beta": "Testing",
              "Launch-ready": "Deployment", "Live": "Maintenance"}
PHASE_PROGRESS = {"Idea": 5, "Planning": 12, "Design": 22, "Development": 45, "Testing": 70,
                  "Deployment": 88, "Maintenance": 100}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def github_url(remote: str | None) -> str | None:
    if not remote:
        return None
    m = re.match(r"^(?:git@github\.com:|https?://(?:[^@/]+@)?github\.com/)([^/]+)/(.+?)(?:\.git)?/?$", remote.strip())
    return f"https://github.com/{m.group(1)}/{m.group(2)}" if m else None


def guess_type(f: dict) -> str:
    stack = set(f.get("stack") or [])
    if f.get("kind") == "codex-thread":
        return "Other"
    if stack & {"Capacitor", "Expo", "Electron"}:
        return "App"
    if "Shopify" in stack:
        return "E-commerce"
    if stack & {"Next.js", "React", "Vue", "Svelte", "Vite", "FastAPI", "Flask", "Django"}:
        return "SaaS" if stack & {"Prisma", "Supabase", "Stripe"} else "Website"
    if f.get("preview_sources"):
        return "Website"
    if "Python" in stack:
        return "Automation"
    return "Other"


def guess_phase(f: dict) -> str:
    loc = (f.get("files") or {}).get("loc_total") or 0
    if f.get("kind") == "codex-thread":
        return "Idea"
    if loc < 80:
        return "Planning" if f.get("docs") else "Idea"
    return "Development"


def _norm_phase(ph: str | None) -> str | None:
    if not ph:
        return None
    ph = OLD_PHASES.get(ph, ph)
    return ph if ph in PHASES else None


def _item(r: dict) -> dict:
    return {"id": r["id"], "title": r["title"], "detail": r["detail"], "status": r["status"],
            "priority": r["priority"], "due": r["due"], "source": r["source"], "editable": True,
            "updatedAt": r["updated_at"], "createdAt": r.get("created_at"), "effort": r.get("effort_min"),
            "dependsOn": r.get("depends_on"), "via": r.get("via")}


def build(raw: dict, override: dict, items: list[dict], preview_errors: dict | None = None, *, local=True) -> dict:
    o = override or {}
    a = raw.get("analysis")
    r = (a or {}).get("result") or {}
    src: dict[str, str] = {}

    def pick(field, you, ai, est, est_src="estimate"):
        if you not in (None, ""):
            src[field] = "you"
            return you
        if ai not in (None, ""):
            src[field] = "ai"
            return ai
        src[field] = est_src
        return est

    by_kind: dict[str, list[dict]] = {k: [] for k in ("task", "milestone", "blocker", "bug", "goal")}
    for it in items:
        by_kind.setdefault(it["kind"], []).append(_item(it))
    for c in raw.get("checklist") or []:
        by_kind["task"].append({"id": None, "title": c["text"], "detail": f"From {c['file']}",
                                "status": "done" if c["done"] else "todo", "priority": "medium", "due": None,
                                "source": "doc", "editable": False, "file": c["file"], "updatedAt": None})
    tasks = by_kind["task"]
    counts = {
        "total": len(tasks),
        "done": sum(1 for t in tasks if t["status"] == "done"),
        "doing": sum(1 for t in tasks if t["status"] == "doing"),
        "todo": sum(1 for t in tasks if t["status"] == "todo"),
        "highOpen": sum(1 for t in tasks if t["status"] != "done" and t["priority"] == "high"),
    }
    counts["open"] = counts["total"] - counts["done"]
    open_blockers = [b for b in by_kind["blocker"] if b["status"] == "open"]

    phase = pick("phase", o.get("phase"), _norm_phase(r.get("phase")), guess_phase(raw))
    phase_progress = r.get("phase_progress") if src["phase"] == "ai" else None
    est_progress = PHASE_PROGRESS[phase]
    ai_progress = r.get("progress")
    if ai_progress is None and a:  # old-format analysis: derive from phase
        ai_progress = PHASE_PROGRESS.get(_norm_phase(r.get("phase")) or "", None)
    progress = pick("progress", o.get("progress"), ai_progress, est_progress)

    idle = raw.get("days_idle")
    if o.get("status"):
        status, src["status"] = o["status"], "you"
    elif phase == "Maintenance":
        status, src["status"] = "Completed", "estimate"
    elif open_blockers:
        status, src["status"] = "Blocked", "estimate"
    elif idle is not None and idle > 30:
        status, src["status"] = "Paused", "estimate"
    else:
        status, src["status"] = "Active", "estimate"

    preview, device, preview_kind = None, None, None
    ptype = pick("type", o.get("type"), r.get("type") if r.get("type") in TYPES else None, guess_type(raw))
    if o.get("preview_image"):
        preview, preview_kind = f"/previews/{o['preview_image']}", "upload"
    else:
        shot = preview_path(raw["key"])
        if local and shot.exists():
            preview, preview_kind = f"/previews/{shot.name}?v={int(shot.stat().st_mtime)}", "screenshot"
        elif local and raw.get("images"):
            preview, preview_kind = f"/api/repo-image?k={_q(raw['key'])}&i=0", "repo-image"
    device = "phone" if ptype in ("App", "Game") else "desktop"

    g = raw.get("git") or {}
    files = raw.get("files") or {}
    techs = list(raw.get("stack") or [])
    techs += [lang for lang in (files.get("loc") or {}) if lang not in techs][:4]

    ai = None
    if a:
        ai = {
            "createdAt": a["created_at"], "meta": a["meta"], "stale": raw.get("analysis_stale"),
            "summary": r.get("summary"), "whatItIs": r.get("what_it_is"), "phaseReason": r.get("phase_reason"),
            "health": r.get("health"), "healthReason": r.get("health_reason"),
            "needsFromMe": r.get("needs_from_me") or [], "nextSteps": r.get("next_steps") or [],
            "optimizations": r.get("optimizations") or [], "risks": r.get("risks") or [],
            "launchChecklist": r.get("launch_checklist") or [], "performance": r.get("performance") or {},
            "confidence": r.get("confidence"), "history": raw.get("analysis_history") or [],
            "previous": (raw.get("analysis_prev") or {}).get("result"),
            "rawPhase": r.get("phase"),
        }

    return {
        "id": raw["key"],
        "name": raw["display_name"],
        "oneLiner": pick("oneLiner", None, r.get("what_it_is"), raw.get("readme") or "", "scan"),
        "description": pick("description", o.get("description"), r.get("description") or r.get("what_it_is"),
                            raw.get("readme") or "", "scan"),
        "type": ptype,
        "status": status,
        "phase": phase,
        "phaseProgress": phase_progress,
        "progress": int(progress or 0),
        "priority": pick("priority", o.get("priority"), r.get("priority"), "Medium"),
        "health": r.get("health"),
        "previewImage": preview,
        "previewKind": preview_kind,
        "previewDevice": device,
        "previewError": (preview_errors or {}).get(raw["key"]),
        "liveUrl": o.get("live_url"),
        "previewUrl": o.get("preview_url"),
        "githubUrl": o.get("github_url") or github_url(g.get("remote")),
        "technologies": techs,
        "goals": [x["title"] for x in by_kind["goal"]],
        "goalItems": by_kind["goal"],
        "notes": o.get("note") or "",
        "tasks": tasks,
        "milestones": sorted(by_kind["milestone"], key=lambda m: (m["status"] == "done", m["due"] or "9999")),
        "blockers": by_kind["blocker"],
        "bugs": by_kind["bug"],
        "taskCounts": counts,
        "createdAt": raw.get("created"),
        "updatedAt": raw.get("last_activity"),
        "targetDate": o.get("target_date"),
        "sources": src,
        "ai": ai,
        "facts": {
            "kind": raw.get("kind"), "path": raw.get("path"), "machine": raw.get("machine"),
            "machines": raw.get("machines") or [raw.get("machine")],
            "local": bool(local and raw.get("path") and Path(raw["path"]).is_dir()),
            "git": raw.get("git"), "files": raw.get("files"), "docs": raw.get("docs") or [],
            "readme": raw.get("readme"), "signals": raw.get("signals") or [], "aiTools": raw.get("ai_tools") or {},
            "recentSessions": raw.get("recent_sessions") or [], "recentPrompts": raw.get("recent_prompts") or [],
            "activity": raw.get("activity") or {}, "daysIdle": idle, "mergedFrom": raw.get("merged_from") or [],
            "images": len(raw.get("images") or []), "previewSources": raw.get("preview_sources") or [],
        },
    }


def _q(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")


def repo_image(raw: dict, i: int) -> Path | None:
    imgs = raw.get("images") or []
    if 0 <= i < len(imgs) and Path(imgs[i]).is_file():
        return Path(imgs[i])
    return None
