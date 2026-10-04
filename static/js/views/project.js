// Project detail view: hero -> lifecycle -> sections (overview, tasks, milestones, issues, AI, activity, code).
import { esc, ago, fmt, dateLabel } from "../util.js";
import { icon } from "../icons.js";
import { ring, stackedBars, TOOL } from "../charts.js";
import { typeColor } from "../model.js";
import {
  previewFrame, statusBadge, priorityBadge, typeChip, lifecycle, levelChip, sourceTag, sourceHint, panel, empty,
  dueLabel, jobLine,
} from "../components.js";
import { state, project } from "../state.js";
import { machineLabel } from "./settings.js";
import { timeline } from './integrations.js';

const SECTIONS = [["overview", "Overview"], ["tasks", "Tasks"], ["milestones", "Milestones"], ["issues", "Blockers & bugs"],
  ["insights", "AI insights"], ["activity", "Activity"], ["code", "Code"]];

export function projectView(id) {
  const p = project(id);
  if (!p) return `<a class="back" href="#/">${icon("arrowLeft", 15)}Dashboard</a>${empty("Project not found. It may be hidden or merged.", "search")}`;
  return `
  <a class="back" href="#/">${icon("arrowLeft", 15)}Dashboard</a>
  ${hero(p)}
  ${p.intelligence ? `<section class="card" style="padding:20px"><h2>Collector intelligence</h2><p>Last synced ${esc(ago(p.lastSynced))}${Date.now()-Date.parse(p.lastSynced)>86400000?' · STALE':''} · ${p.facts.todoCount || 0} TODO/FIXME markers observed</p>${p.intelligence.observations.map(o=>`<p><b>${esc(o.device_id)}</b> · ${esc(o.branch || 'No branch')} · ${o.changed_files === null ? 'Git status unavailable' : o.changed_files + ' changed files'} · Last activity ${o.last_activity ? esc(ago(o.last_activity)) : 'unavailable'} · synced ${esc(ago(o.synced_at))}</p>`).join('')}<h3>Chronological activity</h3>${timeline(p.intelligence.timeline)}</section>` : ''}
  <section class="card lc-card">${lifecycle(p.phase, p.phaseProgress)}
    ${p.ai?.phaseReason ? `<p class="lc-reason">${icon("sparkles", 13)}${esc(p.ai.phaseReason)}</p>` : `<p class="lc-reason muted">Stage ${esc(sourceHint(p.sources.phase))}. ${p.sources.phase === "estimate" ? "Run AI analysis for an accurate stage." : ""}</p>`}
  </section>
  <nav class="subnav" aria-label="Project sections">${SECTIONS.map(([k, l]) => `<a href="#sec-${k}" data-act="jump" data-target="sec-${k}">${l}${sectionCount(p, k)}</a>`).join("")}</nav>
  ${overviewSection(p)}
  ${tasksSection(p)}
  ${milestonesSection(p)}
  ${issuesSection(p)}
  ${insightsSection(p)}
  ${activitySection(p)}
  ${codeSection(p)}`;
}

function sectionCount(p, k) {
  const n = { tasks: p.taskCounts.open, milestones: p.milestones.filter((m) => m.status !== "done").length,
    issues: p.blockers.filter((b) => b.status === "open").length + p.bugs.filter((b) => b.status === "open").length }[k];
  return n ? `<span>${n}</span>` : "";
}

// ------------------------------------------------------------------ hero

function hero(p) {
  const links = [
    p.githubUrl && `<a class="btn" href="${esc(p.githubUrl)}" target="_blank" rel="noopener">${icon("github", 15)}GitHub</a>`,
    p.liveUrl && `<a class="btn" href="${esc(p.liveUrl)}" target="_blank" rel="noopener">${icon("link", 15)}Live site</a>`,
    p.facts.local && `<button class="btn" data-act="openCode" data-key="${esc(p.id)}">${icon("code", 15)}Open in VS Code</button>`,
    p.facts.local && `<button class="btn" data-act="openFolder" data-key="${esc(p.id)}">${icon("folder", 15)}Folder</button>`,
  ].filter(Boolean).join("");
  return `<section class="phero card" style="--tc:${typeColor(p.type)}">
    <div class="phero-preview">${previewFrame(p, { large: true })}
      <div class="pv-actions">
        <button class="btn small" data-act="refreshPreview" data-key="${esc(p.id)}" ${state.data.meta.browser ? "" : "disabled"} title="Capture a new screenshot from the live/preview URL or the local web page">${icon("refresh", 13)}Refresh preview</button>
        <label class="btn small">${icon("upload", 13)}Upload image<input type="file" accept="image/png,image/jpeg,image/webp,image/gif" data-act="uploadPreview" data-key="${esc(p.id)}" hidden></label>
        ${p.previewKind === "upload" ? `<button class="btn small" data-act="clearUpload" data-key="${esc(p.id)}">${icon("x", 13)}Remove upload</button>` : ""}
      </div>
      ${p.previewError ? `<p class="pv-error">${icon("alert", 13)}${esc(p.previewError)}</p>` : ""}
      ${!p.previewImage && !p.liveUrl && !p.previewUrl && !p.facts.previewSources.length ? `<p class="muted small">Add a live URL or a local dev URL in Edit details to capture a preview.</p>` : ""}
    </div>
    <div class="phero-info">
      <div class="badges-row">${typeChip(p.type)}${statusBadge(p.status)}${priorityBadge(p.priority)}</div>
      <h1>${esc(p.name)}</h1>
      <p class="phero-one">${esc(p.oneLiner || "No description yet.")}</p>
      <div class="phero-metrics">
        ${ring(p.progress, { size: 128, stroke: 11, label: "complete", color: p.status === "Completed" ? "var(--good)" : "var(--accent)" })}
        <div class="pm-grid">
          <div><span>Stage</span><b>${esc(p.phase)}</b><em>${esc(sourceHint(p.sources.phase))}</em></div>
          <div><span>Health</span><b>${p.health ?? "–"}${p.health != null ? "<small>/100</small>" : ""}</b><em>${p.health != null ? "AI-rated" : "not analyzed"}</em></div>
          <div><span>Tasks</span><b>${p.taskCounts.done}<small>/${p.taskCounts.total}</small></b><em>${p.taskCounts.open} open</em></div>
          <div><span>Progress</span><b>${p.progress}%</b><em>${esc(sourceHint(p.sources.progress))}</em></div>
        </div>
      </div>
      <dl class="dates">
        <div><dt>${icon("calendar", 13)}Created</dt><dd>${esc(dateLabel(p.createdAt, true))}</dd></div>
        <div><dt>${icon("clock", 13)}Updated</dt><dd>${esc(ago(p.updatedAt))}</dd></div>
        <div><dt>${icon("cpu", 13)}Computer</dt><dd>${esc(p.facts.machines.map(machineLabel).join(" + "))}</dd></div>
        <div><dt>${icon("flag", 13)}Target</dt><dd>${p.targetDate ? dueLabel(p.targetDate) : `<button class="linklike" data-act="editProject" data-key="${esc(p.id)}">Set a date</button>`}</dd></div>
      </dl>
      <div class="phero-links">${links}</div>
      <div class="phero-actions">
        <button class="btn primary" data-act="editProject" data-key="${esc(p.id)}">${icon("edit", 15)}Edit details</button>
        ${state.data.settings.claude_found ? `<button class="btn" data-act="analyzeOne" data-key="${esc(p.id)}">${icon("sparkles", 15)}${p.ai ? "Re-analyze" : "Analyze with AI"}</button>` : ""}
        <select data-act="merge" data-key="${esc(p.id)}" aria-label="Merge into another project" title="Fold this project into another one"><option value="">Merge into…</option>${state.data.projects.filter((x) => x.id !== p.id).map((o) => `<option value="${esc(o.id)}">${esc(o.name)}</option>`).join("")}</select>
        <button class="btn ghost" data-act="hide" data-key="${esc(p.id)}">${icon("eyeOff", 15)}Hide</button>
      </div>
      <div>${jobLine(p.id)}</div>
    </div>
  </section>`;
}

// ------------------------------------------------------------------ sections

function section(id, title, iconName, body, action = "") {
  return `<section class="psec" id="sec-${id}"><div class="psec-head"><h2>${icon(iconName, 18)}${esc(title)}</h2>${action}</div>${body}</section>`;
}

function overviewSection(p) {
  const ai = p.ai;
  const goals = p.goalItems;
  return section("overview", "Overview", "layers", `<div class="grid-2">
    ${panel("Description", `<p class="prose">${esc(p.description || "No description yet.")}</p>
      ${ai?.summary ? `<h3 class="sub-h">Where it stands</h3><p class="prose muted-2">${esc(ai.summary)}</p>` : ""}
      <h3 class="sub-h">Technologies</h3><div class="chips">${p.technologies.map((t) => `<span class="chip">${esc(t)}</span>`).join("") || '<span class="muted">Unknown</span>'}</div>`, { iconName: "note" })}
    <div class="stack">
      ${panel("Goals", `${goals.length ? `<ul class="goal-list">${goals.map((g) => `<li>${icon("target", 15)}<span>${esc(g.title)}</span>${sourceTag(g.source)}<button class="icon-x" data-act="deleteItem" data-id="${g.id}" aria-label="Remove goal">${icon("x", 13)}</button></li>`).join("")}</ul>` : empty("No goals yet.", "target")}
        <form class="inline-add" data-act="addItem" data-key="${esc(p.id)}" data-kind="goal"><input name="title" placeholder="Add a goal" required><button class="btn">Add</button></form>`, { iconName: "target" })}
      ${panel("Important notes", `<textarea class="notes" data-act="saveNotes" data-key="${esc(p.id)}" placeholder="Decisions, ideas, links, reminders…">${esc(p.notes)}</textarea><div class="muted small">Saved automatically when you click away.</div>`, { iconName: "edit" })}
    </div>
  </div>`);
}

const TASK_STATUS_ICON = { todo: "circle", doing: "half", done: "checkCircle" };
const PRIO_ORDER = { high: 0, medium: 1, low: 2 };

function taskItem(t) {
  const ctl = t.editable
    ? `<button class="tstat tstat-${t.status}" data-act="cycleTask" data-id="${t.id}" data-status="${t.status}" title="Change status (to do → in progress → done)">${icon(TASK_STATUS_ICON[t.status], 18)}</button>`
    : `<span class="tstat tstat-${t.status}" title="Edit ${esc(t.file || "the doc")} to change this">${icon(TASK_STATUS_ICON[t.status], 18)}</span>`;
  return `<li class="titem ${t.status}">${ctl}<div class="t-body"><div class="t-title">${esc(t.title)}</div>
    ${t.detail ? `<div class="t-detail">${esc(t.detail)}</div>` : ""}<div class="t-meta">${levelChip(t.priority)}${sourceTag(t.source)}</div></div>
    ${t.editable ? `<button class="icon-x" data-act="deleteItem" data-id="${t.id}" aria-label="Delete task">${icon("x", 13)}</button>` : ""}</li>`;
}

function tasksSection(p) {
  const by = (st) => p.tasks.filter((t) => t.status === st).sort((a, b) => (PRIO_ORDER[a.priority] ?? 1) - (PRIO_ORDER[b.priority] ?? 1));
  const cols = [["doing", "In progress", "play"], ["todo", "Up next", "list"], ["done", "Completed", "checkCircle"]];
  const c = p.taskCounts;
  return section("tasks", "Tasks", "checkCircle", `
    <div class="task-summary"><span class="tk-track big"><span class="tk-done" style="width:${c.total ? (c.done / c.total) * 100 : 0}%"></span><span class="tk-doing" style="width:${c.total ? (c.doing / c.total) * 100 : 0}%"></span></span>
      <span><b>${c.done}</b> done · <b>${c.doing}</b> in progress · <b>${c.todo}</b> to do${c.highOpen ? ` · <b class="hi">${c.highOpen}</b> high priority` : ""}</span></div>
    <form class="inline-add wide" data-act="addItem" data-key="${esc(p.id)}" data-kind="task">
      <input name="title" placeholder="Add a task…" required>
      <select name="priority" aria-label="Priority"><option value="high">High</option><option value="medium" selected>Medium</option><option value="low">Low</option></select>
      <select name="status" aria-label="Status"><option value="todo">To do</option><option value="doing">In progress</option></select>
      <button class="btn primary">${icon("plus", 14)}Add</button></form>
    <div class="kanban">${cols.map(([st, label, ic]) => {
      const items = by(st);
      return `<div class="kcol kcol-${st}"><div class="kcol-head">${icon(ic, 15)}${label}<span>${items.length}</span></div>
        <ul class="tlist">${items.slice(0, 8).map(taskItem).join("") || `<li class="kempty">Nothing here</li>`}</ul>
        ${items.length > 8 ? `<details class="more"><summary>Show ${items.length - 8} more</summary><ul class="tlist">${items.slice(8).map(taskItem).join("")}</ul></details>` : ""}</div>`;
    }).join("")}</div>`);
}

function milestonesSection(p) {
  const ms = p.milestones;
  return section("milestones", "Milestones", "flag", `
    ${ms.length ? `<ol class="mtimeline">${ms.map((m) => `
      <li class="${m.status === "done" ? "done" : ""}"><button class="m-node" data-act="toggleMilestone" data-id="${m.id}" data-done="${m.status === "done"}" aria-label="Toggle milestone">${m.status === "done" ? icon("check", 13) : ""}</button>
        <div class="m-body"><div class="m-title">${esc(m.title)}${sourceTag(m.source)}</div><div class="m-due">${m.status === "done" ? "Done" : dueLabel(m.due)}</div></div>
        <button class="icon-x" data-act="deleteItem" data-id="${m.id}" aria-label="Delete milestone">${icon("x", 13)}</button></li>`).join("")}</ol>` : empty("No milestones yet.", "flag")}
    <form class="inline-add wide" data-act="addItem" data-key="${esc(p.id)}" data-kind="milestone">
      <input name="title" placeholder="Add a milestone, e.g. Beta on TestFlight" required><input type="date" name="due" aria-label="Due date">
      <button class="btn">${icon("plus", 14)}Add</button></form>`);
}

function issueList(items, kind) {
  if (!items.length) return empty(kind === "blocker" ? "Nothing is blocking this project." : "No known bugs.", "checkCircle");
  return `<ul class="issues">${items.map((b) => `
    <li class="${b.status}"><button class="tstat tstat-${b.status === "resolved" ? "done" : "todo"}" data-act="toggleIssue" data-id="${b.id}" data-status="${b.status}" title="${b.status === "resolved" ? "Reopen" : "Mark resolved"}">${icon(b.status === "resolved" ? "checkCircle" : kind === "blocker" ? "lock" : "bug", 17)}</button>
      <div class="t-body"><div class="t-title">${esc(b.title)}</div>${b.detail ? `<div class="t-detail">${esc(b.detail)}</div>` : ""}
      <div class="t-meta">${kind === "bug" ? levelChip(b.priority) : ""}${sourceTag(b.source)}${b.status === "resolved" ? '<span class="muted small">Resolved</span>' : ""}</div></div>
      <button class="icon-x" data-act="deleteItem" data-id="${b.id}" aria-label="Delete">${icon("x", 13)}</button></li>`).join("")}</ul>`;
}

function issuesSection(p) {
  const order = (xs) => xs.slice().sort((a, b) => (a.status === "resolved") - (b.status === "resolved"));
  const form = (kind, ph) => `<form class="inline-add" data-act="addItem" data-key="${esc(p.id)}" data-kind="${kind}"><input name="title" placeholder="${ph}" required>${kind === "bug" ? `<select name="priority" aria-label="Severity"><option value="high">High</option><option value="medium" selected>Medium</option><option value="low">Low</option></select>` : ""}<button class="btn">Add</button></form>`;
  return section("issues", "Blockers & bugs", "alert", `<div class="grid-2">
    ${panel("Blockers", issueList(order(p.blockers), "blocker") + form("blocker", "What's stopping progress?"), { iconName: "lock" })}
    ${panel("Bugs & issues", issueList(order(p.bugs), "bug") + form("bug", "Describe a bug"), { iconName: "bug" })}
  </div>`);
}

function diffs(ai) {
  const prev = ai.previous;
  if (!prev) return [];
  const out = [];
  if (prev.phase !== ai.rawPhase) out.push(`Stage ${prev.phase} → ${ai.rawPhase}`);
  const dh = (ai.health ?? 0) - (prev.health ?? 0);
  if (dh) out.push(`Health ${dh > 0 ? "+" : ""}${dh}`);
  const was = new Set((prev.needs_from_me || []).map((n) => n.title.toLowerCase()));
  const added = ai.needsFromMe.filter((n) => !was.has(n.title.toLowerCase())).length;
  if (added) out.push(`${added} new thing(s) needed from you`);
  return out;
}

function insightsSection(p) {
  const ai = p.ai;
  if (!state.data.settings.claude_found) return section("insights", "AI insights", "sparkles", empty("Install the Claude Code VS Code extension to enable AI analysis.", "sparkles"));
  if (!ai) return section("insights", "AI insights", "sparkles", `<div class="card ai-cta">${icon("sparkles", 26)}<div><h3>Get an AI status report</h3>
    <p>Claude reads this project's code, docs and plans (read-only) and fills in the stage, progress, tasks, milestones, blockers, bugs, what's needed from you and suggested improvements. It takes 1–3 minutes on your Claude login.</p>
    <button class="btn primary" data-act="analyzeOne" data-key="${esc(p.id)}">${icon("sparkles", 15)}Analyze with AI</button> ${jobLine(p.id)}</div></div>`);
  const needs = ai.needsFromMe.slice().sort((a, b) => (PRIO_ORDER[a.priority] ?? 1) - (PRIO_ORDER[b.priority] ?? 1));
  const cl = ai.launchChecklist, clDone = cl.filter((c) => c.done).length;
  const ch = diffs(ai);
  const m = ai.meta || {};
  return section("insights", "AI insights", "sparkles", `
    ${ai.stale ? `<div class="stale">${icon("alert", 15)}This project changed after the report (${esc(ago(ai.createdAt))}). Re-analyze to refresh it.</div>` : ""}
    ${ch.length ? `<div class="changes"><b>Since the last report:</b>${ch.map((c) => `<span class="chip">${esc(c)}</span>`).join("")}</div>` : ""}
    <div class="grid-2">
      ${panel(`Needed from you · ${needs.length}`, needs.length ? `<ul class="ilist">${needs.map((n) => `<li><div class="il-head"><b>${esc(n.title)}</b>${levelChip(n.priority)}</div><div class="il-body"><span class="chip">${esc(n.type)}</span> ${esc(n.detail)}</div></li>`).join("")}</ul>` : empty("Nothing. The AI can carry on alone."), { iconName: "target" })}
      ${panel("Recommended next steps", `<ol class="ilist numbered">${ai.nextSteps.map((n) => `<li><div class="il-head"><b>${esc(n.title)}</b><span class="chip">Effort ${esc(n.effort)}</span></div><div class="il-body">${esc(n.detail)}</div></li>`).join("")}</ol>`, { iconName: "arrowRight" })}
      ${panel("Suggested optimizations", `<ul class="ilist">${ai.optimizations.map((o) => `<li><div class="il-head"><b>${esc(o.title)}</b><span class="nowrap">${levelChip(o.impact, o.impact + " impact")}<span class="chip">Effort ${esc(o.effort)}</span></span></div><div class="il-body"><span class="chip">${esc(o.category)}</span> ${esc(o.detail)}</div></li>`).join("")}</ul>`, { iconName: "zap" })}
      ${panel("Risks", ai.risks.length ? `<ul class="ilist">${ai.risks.map((k) => `<li><div class="il-head"><b>${esc(k.title)}</b>${levelChip(k.severity)}</div><div class="il-body">${esc(k.detail)}</div></li>`).join("")}</ul>` : empty("No major risks found."), { iconName: "alert" })}
      ${panel(`Launch checklist · ${clDone}/${cl.length}`, `<div class="tk-track big" style="margin-bottom:10px"><span class="tk-done" style="width:${cl.length ? (clDone / cl.length) * 100 : 0}%;background:var(--good)"></span></div>
        <ul class="checks">${cl.map((c) => `<li class="${c.done ? "done" : ""}">${icon(c.done ? "checkCircle" : "circle", 16)}<span>${esc(c.item)}</span></li>`).join("")}</ul>`, { iconName: "rocket" })}
      ${panel("Performance", `<p class="prose muted-2">${esc(ai.performance.assessment || "")}</p><div class="metric-grid">${(ai.performance.metrics || []).map((x) => `<div class="metric" title="${esc(x.note)}"><span>${esc(x.label)}</span><b>${esc(x.value)}</b><em>${esc(x.note)}</em></div>`).join("")}</div>`, { iconName: "gauge" })}
    </div>
    <p class="ai-foot">${icon("sparkles", 13)}Analyzed ${esc(ago(ai.createdAt))} by ${esc(m.model || "Claude")} · ${m.duration_s ?? "?"}s · ${m.files_read ?? "?"} files read · confidence ${esc(ai.confidence || "?")}${ai.history.length > 1 ? ` · health trend ${ai.history.map((h) => h.health).join(" → ")}` : ""}${m.cost_usd != null ? ` · ≈$${m.cost_usd.toFixed(2)} API-equivalent (covered by your plan)` : ""}</p>`);
}

function activitySection(p) {
  const f = p.facts;
  return section("activity", "Recent activity", "activity", `<div class="grid-2">
    ${panel("Activity · 30 days", stackedBars(f.activity, { title: p.name + " activity" }), { iconName: "activity" })}
    ${panel("Recent AI sessions", f.recentSessions.length ? `<ul class="feed">${f.recentSessions.map((s) => `
      <li><span class="feed-ico" style="--fc:${TOOL[s.tool]?.color}">${icon("sparkles", 13)}</span><div><div class="feed-text">${esc(s.title || "Untitled session")}</div>
      <div class="feed-meta"><span>${esc(TOOL[s.tool]?.label || s.tool)} · ${esc(ago(s.end))}</span></div>${s.last_prompt ? `<div class="t-detail">“${esc(s.last_prompt)}”</div>` : ""}</div></li>`).join("")}</ul>` : empty("No AI sessions for this project."), { iconName: "sparkles" })}
    ${panel("Recent commits", f.git?.recent_commits?.length ? `<ul class="feed">${f.git.recent_commits.map((c) => `
      <li><span class="feed-ico" style="--fc:var(--s1)">${icon("code", 13)}</span><div><div class="feed-text">${esc(c.subject)}</div><div class="feed-meta"><span class="mono">${esc(c.hash)}</span><span>${esc(ago(c.ts))}</span></div></div></li>`).join("")}</ul>
      <p class="muted small">Branch <span class="mono">${esc(f.git.branch)}</span>${f.git.remote ? "" : " · no remote"}</p>` : empty(f.git ? "No commits yet." : "Not a git repository.", "code"), { iconName: "code" })}
    ${panel("What you asked recently", f.recentPrompts.length ? `<ul class="feed">${f.recentPrompts.slice(0, 6).map((r) => `<li><span class="feed-ico" style="--fc:${TOOL[r.tool]?.color}">${icon("sparkles", 13)}</span><div class="t-detail clamp">${esc(r.text)}</div></li>`).join("")}</ul>` : empty("No prompts found."), { iconName: "note" })}
  </div>`);
}

function codeSection(p) {
  const f = p.facts, files = f.files, g = f.git;
  const langs = Object.entries(files?.loc || {}), maxLoc = Math.max(1, ...langs.map(([, v]) => v));
  const stat = (l, v) => `<div class="metric"><span>${esc(l)}</span><b>${esc(v)}</b></div>`;
  return section("code", "Code & repository", "code", `
    <div class="metric-grid wide">${stat("Lines of code", files ? fmt(files.loc_total) : "–")}${stat("Files", files ? fmt(files.files) : "–")}${stat("Commits", g ? fmt(g.commit_count) : "no git")}${stat("Uncommitted", g ? fmt(g.uncommitted) : "–")}${stat("TODO / FIXME", files ? fmt(files.todos) : "–")}${stat("AI sessions", fmt(Object.values(f.aiTools).reduce((a, t) => a + t.sessions, 0)))}</div>
    <div class="grid-3">
      ${panel("Languages", langs.length ? `<div class="type-bars">${langs.map(([l, v]) => `<div class="tb-row"><span class="tb-label">${esc(l)}</span><span class="tb-track"><span style="width:${(v / maxLoc) * 100}%;background:var(--s1)"></span></span><b>${fmt(v)}</b></div>`).join("")}</div><p class="muted small">Lines per language</p>` : empty("No source files.", "code"), { iconName: "code" })}
      ${panel("Plans & docs", f.docs.length ? `<ul class="feed">${f.docs.slice(0, 8).map((d) => `<li><span class="feed-ico" style="--fc:var(--s7)">${icon("note", 13)}</span><div><div class="feed-text mono">${esc(d.name)}</div><div class="feed-meta"><span>${esc(ago(d.modified))}</span></div></div></li>`).join("")}</ul>` : empty("No plan or README files.", "note"), { iconName: "note" })}
      ${panel("Repository signals", f.signals.length ? `<ul class="ilist">${f.signals.map((s) => `<li><div class="il-head"><b>${esc(s.action)}</b>${levelChip(s.level === "info" ? "low" : s.level === "warning" ? "medium" : "high", s.level)}</div><div class="il-body">${esc(s.text)}</div></li>`).join("")}</ul>` : empty("All clear.", "checkCircle"), { iconName: "alert" })}
    </div>
    ${f.path ? `<p class="muted small mono path-line">${esc(f.path)} · ${esc(f.machine)}</p>` : ""}
    ${f.mergedFrom.length ? `<p class="muted small">Includes merged: ${f.mergedFrom.map((m) => `${esc(m.name)} <button class="btn small" data-act="unmerge" data-key="${esc(m.key)}">split out</button>`).join(" ")}</p>` : ""}`);
}

// ------------------------------------------------------------------ edit dialog

export function editDialog(p) {
  const meta = state.data.meta;
  const d = document.createElement("dialog");
  const opt = (vals, cur, auto) => (auto ? `<option value="">${auto}</option>` : "") + vals.map((v) => `<option ${v === cur ? "selected" : ""}>${esc(v)}</option>`).join("");
  const you = (f) => p.sources[f] === "you";
  d.innerHTML = `<form method="dialog" class="form">
    <h2>Edit ${esc(p.name)}</h2>
    <p class="muted small">Blank or "Auto" fields use the AI analysis or the scan.</p>
    <label class="field">Name<input name="name" value="${esc(p.name)}"></label>
    <div class="row3">
      <label class="field">Type<select name="type">${opt(meta.types, you("type") ? p.type : "", `Auto (${p.type})`)}</select></label>
      <label class="field">Priority<select name="priority">${opt(meta.priorities, you("priority") ? p.priority : "", `Auto (${p.priority})`)}</select></label>
      <label class="field">Status<select name="status">${opt(meta.statuses, you("status") ? p.status : "", `Auto (${p.status})`)}</select></label>
    </div>
    <div class="row3">
      <label class="field">Stage<select name="phase">${opt(meta.phases, you("phase") ? p.phase : "", `Auto (${p.phase})`)}</select></label>
      <label class="field">Progress %<input type="number" name="progress" min="0" max="100" placeholder="Auto (${p.progress})" value="${you("progress") ? p.progress : ""}"></label>
      <label class="field">Target date<input type="date" name="target_date" value="${esc(p.targetDate || "")}"></label>
    </div>
    <label class="field">Description<textarea name="description" placeholder="${esc(p.description || "")}">${you("description") ? esc(p.description) : ""}</textarea></label>
    <label class="field">Live URL<input name="live_url" type="url" placeholder="https://…" value="${esc(p.liveUrl || "")}"></label>
    <label class="field">Preview URL <span class="muted">(optional, e.g. http://localhost:3000 while your dev server runs)</span><input name="preview_url" type="url" value="${esc(p.previewUrl || "")}"></label>
    <label class="field">GitHub URL<input name="github_url" type="url" placeholder="${esc(p.githubUrl || "https://github.com/…")}" value=""></label>
    <div class="dialog-actions"><button class="btn" value="cancel" formnovalidate>Cancel</button><button class="btn primary" value="save">Save</button></div>
  </form>`;
  document.body.appendChild(d);
  d.showModal();
  return new Promise((resolve) => {
    d.addEventListener("close", () => {
      const data = Object.fromEntries(new FormData(d.querySelector("form")));
      if (!data.github_url) delete data.github_url; // keep the remote-derived link unless replaced
      d.remove();
      resolve(d.returnValue === "save" ? data : null);
    });
  });
}
