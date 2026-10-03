"""AI analysis of a digital project using the Claude Code CLI in headless mode.

Uses the claude.exe bundled with the VS Code extension (or one on PATH), so it
runs on the user's existing Claude login. The agent may only Read/Glob/Grep
inside the project folder; it cannot edit files or run commands.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

PHASES = ["Idea", "Planning", "Design", "Development", "Testing", "Deployment", "Maintenance"]
TYPES = ["App", "Website", "SaaS", "Internal Tool", "E-commerce", "Automation", "Game", "Library", "Other"]
MODELS = {"sonnet": "Sonnet (balanced)", "opus": "Opus (deepest, uses more quota)", "haiku": "Haiku (fastest)"}
TIMEOUT_S = 900

_lvl = {"type": "string", "enum": ["high", "medium", "low"]}
_effort = {"type": "string", "enum": ["S", "M", "L"]}


def _arr(props: dict, required: list[str]) -> dict:
    return {"type": "array", "items": {"type": "object", "properties": props, "required": required,
                                       "additionalProperties": False}}


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "what_it_is": {"type": "string", "description": "One line: what this product is and who it's for."},
        "description": {"type": "string", "description": "3-5 sentences: what it does, for whom, how, and how it could make money."},
        "type": {"type": "string", "enum": TYPES},
        "progress": {"type": "integer", "minimum": 0, "maximum": 100,
                     "description": "Overall completion toward a public v1 launch."},
        "priority": {"type": "string", "enum": ["High", "Medium", "Low"],
                     "description": "Suggested focus priority given momentum, nearness to launch and potential."},
        "goals": {"type": "array", "items": {"type": "string"}, "description": "2-5 product goals for v1."},
        "tasks": _arr({"title": {"type": "string"}, "detail": {"type": "string"},
                       "status": {"type": "string", "enum": ["done", "in_progress", "todo"]}, "priority": _lvl},
                      ["title", "detail", "status", "priority"]),
        "milestones": _arr({"title": {"type": "string"}, "done": {"type": "boolean"},
                            "target": {"type": "string", "description": "YYYY-MM-DD if the docs give a date, else empty."}},
                           ["title", "done", "target"]),
        "blockers": _arr({"title": {"type": "string"}, "detail": {"type": "string"}}, ["title", "detail"]),
        "bugs": _arr({"title": {"type": "string"}, "detail": {"type": "string"}, "severity": _lvl},
                     ["title", "detail", "severity"]),
        "summary": {"type": "string", "description": "2-4 sentences on where the project stands right now."},
        "phase": {"type": "string", "enum": PHASES},
        "phase_reason": {"type": "string"},
        "phase_progress": {"type": "integer", "minimum": 0, "maximum": 100,
                           "description": "How far through the current phase toward the next one."},
        "health": {"type": "integer", "minimum": 0, "maximum": 100},
        "health_reason": {"type": "string"},
        "needs_from_me": _arr({
            "title": {"type": "string"}, "detail": {"type": "string"}, "priority": _lvl,
            "type": {"type": "string", "enum": ["decision", "account", "credentials", "payment", "content",
                                                "testing", "review", "legal", "other"]},
        }, ["title", "detail", "priority", "type"]),
        "next_steps": _arr({"title": {"type": "string"}, "detail": {"type": "string"}, "effort": _effort},
                           ["title", "detail", "effort"]),
        "optimizations": _arr({
            "title": {"type": "string"}, "detail": {"type": "string"},
            "category": {"type": "string", "enum": ["performance", "security", "ux", "code-quality", "cost",
                                                    "seo", "reliability", "business", "accessibility"]},
            "impact": _lvl, "effort": _effort,
        }, ["title", "detail", "category", "impact", "effort"]),
        "risks": _arr({"title": {"type": "string"}, "detail": {"type": "string"}, "severity": _lvl},
                      ["title", "detail", "severity"]),
        "launch_checklist": _arr({"item": {"type": "string"}, "done": {"type": "boolean"}}, ["item", "done"]),
        "performance": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "assessment": {"type": "string"},
                "metrics": _arr({"label": {"type": "string"}, "value": {"type": "string"}, "note": {"type": "string"}},
                                ["label", "value", "note"]),
            },
            "required": ["assessment", "metrics"],
        },
        "confidence": _lvl,
    },
    "required": ["what_it_is", "description", "type", "progress", "priority", "goals", "tasks", "milestones",
                 "blockers", "bugs", "summary", "phase", "phase_reason", "phase_progress", "health", "health_reason",
                 "needs_from_me", "next_steps", "optimizations", "risks", "launch_checklist", "performance",
                 "confidence"],
}

SECRET_RULES = ["Read(**/.env)", "Read(**/.env.*)", "Read(**/*.pem)", "Read(**/*.key)", "Read(**/*.p12)",
                "Read(**/*credentials*)", "Read(**/*secret*)", "Read(**/auth.json)", "Read(**/*.keystore)",
                "Read(**/*.jks)", "Read(**/*.db)", "Read(**/*.sqlite)"]

INSTRUCTIONS = """You are reviewing one of the owner's software projects for their personal project-tracker dashboard.
The owner is a solo founder building several apps and websites with AI coding tools (Claude Code, Codex, Copilot).
They want an honest, in-depth status report: where the project sits on the road to production, what only THEY can
do to unblock it, the concrete next steps, and optimizations worth making.

How to work:
- You can only read. Use Glob/Grep/Read to explore the project folder (your working directory). Start with
  README/CLAUDE.md/AGENTS.md and any plan, handoff, checklist or roadmap docs, then package/config files, then
  the main entry points, routes/screens, data layer and tests. Aim for roughly 15-40 tool calls; go deeper where
  something looks unfinished or risky.
- Never open secrets (.env, keys, credential or token files) and never quote secret values.
- Ground every claim in what you saw. Cite file names in details (e.g. "src/app/page.tsx has no error state").
  Don't invent traffic, revenue or user numbers. The product is probably not live yet.
- Lifecycle phase: Idea (a concept, little or nothing written) -> Planning (specs/plans/docs, no real code)
  -> Design (UI mockups, data model, prototypes of screens) -> Development (building features; core flow not
  finished or not yet working end to end) -> Testing (feature-complete core flow, now fixing bugs, testing with
  real users or on devices) -> Deployment (shipping: hosting, store listings, payments, legal, release) ->
  Maintenance (released publicly; iterating). phase_progress is how far through the current phase it is.
- progress: overall completion toward a public v1, consistent with the phase (e.g. Development is ~30-60%).
- tasks: 8-20 concrete work items covering the whole road to v1. Include work that is clearly already DONE
  (evidence: commits, docs, working code) with status "done", what is being worked on now as "in_progress",
  and the rest as "todo". If the facts list doc checklist items, those are imported separately: do not repeat
  them. milestones: 3-6 big checkpoints (e.g. "Core flow works", "Beta on TestFlight", "Public launch").
- blockers: only things currently stopping progress. bugs: concrete defects or broken behaviour you saw in the
  code (cite files); leave empty rather than guess.
- needs_from_me: ONLY things an AI coding assistant cannot do for them: product decisions, creating accounts,
  API keys/credentials, payments and subscriptions, app-store/domain/hosting setup, legal text sign-off, real
  content/branding/photos, testing on a real phone, answering open questions left in the docs. Be specific.
- next_steps: the 3-7 most valuable engineering steps in order. optimizations: 3-8 concrete improvements
  (performance, security, UX, cost, SEO, reliability, code quality, business).
- performance: assess how the app/site would perform for users (bundle/asset weight, slow queries, N+1 calls,
  caching, image sizes, cold starts, test coverage), with a few concrete metrics you can measure from the code
  (e.g. test count, largest asset, number of routes, dependency count).
- health (0-100): momentum + code quality + risk. Be calibrated; 50 is average.
- Plain, direct English. The owner reads this on a dashboard, so keep each detail to 1-3 sentences.

Facts the dashboard already collected (from git and the owner's AI-tool history):
"""

NO_FOLDER_NOTE = """
This project has no folder on disk; it exists only as AI-chat threads (Codex). You have no tools. Judge it
from the facts and prompts below, set confidence to "low", and put "find or create the project folder" in
needs_from_me if the work seems worth continuing.
"""


REMOTE_NOTE = """
This project lives on another PC ({machine}); you cannot open its files and have no tools. Judge it from the
facts above and the digest below (its file list and key docs, captured by that PC's scanner). Say in
details when something can't be verified from the digest, and use confidence "medium" at most.
"""


def format_digest(d: dict) -> str:
    parts = ["\nFile list (first 400):\n" + "\n".join(d.get("tree", []))]
    for name, text in (d.get("files") or {}).items():
        parts.append(f"\n----- {name} -----\n{text}")
    return "\n".join(parts)


def find_claude() -> str | None:
    exts = sorted(Path.home().glob(".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude.exe"),
                  key=lambda p: [int(x) if x.isdigit() else x for x in re.split(r"[.-]", p.parts[-4])])
    if exts:
        return str(exts[-1])
    return shutil.which("claude")


def build_facts(p: dict) -> str:
    g = p.get("git") or {}
    f = p.get("files") or {}
    lines = [
        f"Name: {p.get('display_name') or p.get('name')}",
        f"Folder: {p.get('path') or '(none)'}   Machine: {p.get('machine')}",
        f"Detected stack: {', '.join(p.get('stack') or []) or 'unknown'}",
        f"Last activity: {p.get('last_activity')}",
    ]
    if f:
        lines.append(f"Files: {f.get('files')}  Lines of code: {f.get('loc_total')}  by language: {f.get('loc')}  TODO/FIXME: {f.get('todos')}")
    if g:
        lines.append(f"Git: branch {g.get('branch')}, {g.get('commit_count')} commits, {g.get('uncommitted')} uncommitted changes, "
                     f"unpushed: {g.get('unpushed')}, remote: {g.get('remote') or 'none'}")
        for c in g.get("recent_commits", [])[:8]:
            lines.append(f"  commit {c['ts'][:10]} {c['subject']}")
    else:
        lines.append("Git: not a repository")
    if p.get("docs"):
        lines.append("Docs: " + ", ".join(f"{d['name']} ({(d['modified'] or '')[:10]})" for d in p["docs"][:12]))
    tools = p.get("ai_tools") or {}
    if tools:
        lines.append("AI tool usage: " + "; ".join(f"{k}: {v['sessions']} sessions, last {(v['last'] or '')[:10]}" for k, v in tools.items()))
    for s in (p.get("recent_sessions") or [])[:6]:
        lines.append(f"  session [{s['tool']}] {(s.get('end') or '')[:10]} \"{s.get('title') or ''}\" last prompt: \"{(s.get('last_prompt') or '')[:200]}\"")
    if p.get("recent_prompts"):
        lines.append("Owner's recent prompts (newest first):")
        lines += [f"  - [{r['tool']}] {r['text'][:250]}" for r in p["recent_prompts"][:8]]
    checks = p.get("checklist") or []
    if checks:
        done = sum(1 for c in checks if c["done"])
        lines.append(f"Doc checklist items already tracked ({done}/{len(checks)} done; don't repeat as tasks): "
                     + "; ".join(c["text"][:80] for c in checks[:25]))
    if p.get("signals"):
        lines.append("Dashboard signals: " + "; ".join(s["text"] for s in p["signals"]))
    if p.get("merged_from"):
        lines.append("Also includes merged items: " + ", ".join(m["name"] for m in p["merged_from"]))
    if p.get("note"):
        lines.append(f"Owner's note: {p['note']}")
    return "\n".join(lines)


def _describe_tool(block: dict, cwd: str | None) -> str:
    name, inp = block.get("name"), block.get("input") or {}
    target = inp.get("file_path") or inp.get("pattern") or inp.get("path") or ""
    if cwd and target.lower().startswith(cwd.lower()):
        target = target[len(cwd):].lstrip("\\/")
    if name == "StructuredOutput":
        return "Writing report"
    verb = {"Read": "Reading", "Glob": "Looking for", "Grep": "Searching for"}.get(name, name)
    return f"{verb} {target}"[:120]


def analyze(p: dict, model: str = "sonnet", on_progress=None, on_proc=None, extra_dirs: list[str] | None = None) -> dict:
    """Run one analysis. Returns {"result": {...}, "meta": {...}}; raises RuntimeError on failure."""
    exe = find_claude()
    if not exe:
        raise RuntimeError("Claude Code CLI not found. Install the Claude Code VS Code extension.")
    say = on_progress or (lambda m: None)
    folder = p.get("path") if p.get("path") and Path(p["path"]).is_dir() else None
    if folder:
        extra = ""
    elif p.get("digest"):
        extra = REMOTE_NOTE.format(machine=p.get("machine")) + format_digest(p["digest"])
    else:
        extra = NO_FOLDER_NOTE
    prompt = INSTRUCTIONS + build_facts(p) + extra + "\n\nReturn the report as structured output matching the schema."
    tools = "Read,Glob,Grep" if folder else ""
    cmd = [exe, "-p", "--output-format", "stream-json", "--verbose", "--no-session-persistence",
           "--model", model, "--tools", tools, "--json-schema", json.dumps(SCHEMA),
           "--setting-sources", "user", "--strict-mcp-config"]
    if folder:
        cmd += ["--allowedTools", "Read", "Glob", "Grep", "--disallowedTools", *SECRET_RULES]
        for d in extra_dirs or []:
            if Path(d).is_dir():
                cmd += ["--add-dir", d]
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDECODE") and k != "CLAUDE_CODE_ENTRYPOINT"}
    cwd = folder or str(Path(__file__).resolve().parent.parent / "data")
    t0 = time.time()
    say("Starting Claude")
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if on_proc:
        on_proc(proc)
    proc.stdin.write(prompt)
    proc.stdin.close()
    final, tool_calls, files_read = None, 0, set()
    try:
        for line in proc.stdout:
            if time.time() - t0 > TIMEOUT_S:
                proc.kill()
                raise RuntimeError(f"Timed out after {TIMEOUT_S // 60} minutes")
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "assistant":
                for block in (ev.get("message") or {}).get("content") or []:
                    if block.get("type") == "tool_use":
                        tool_calls += 1
                        if block.get("name") == "Read":
                            files_read.add((block.get("input") or {}).get("file_path"))
                        say(_describe_tool(block, folder))
                    elif block.get("type") == "text" and block.get("text", "").strip():
                        say("Writing report")
            elif ev.get("type") == "result":
                final = ev
    finally:
        proc.wait(timeout=30)
    err = proc.stderr.read()[-800:] if proc.stderr else ""
    if not final:
        raise RuntimeError(("Claude exited without a result. " + err).strip() if proc.returncode else "Stopped")
    if final.get("is_error") or not final.get("structured_output"):
        raise RuntimeError(str(final.get("result") or final.get("subtype") or "Analysis failed")[:500])
    result = final["structured_output"]
    model_ids = [m for m in (final.get("modelUsage") or {}) if "haiku" not in m] or list(final.get("modelUsage") or {})
    return {
        "result": result,
        "meta": {
            "model": model_ids[0] if model_ids else model,
            "duration_s": round(time.time() - t0, 1),
            "cost_usd": final.get("total_cost_usd"),
            "turns": final.get("num_turns"),
            "tool_calls": tool_calls,
            "files_read": len([f for f in files_read if f]),
        },
    }
