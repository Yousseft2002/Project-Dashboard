// Main dashboard: Portfolio Overview -> focus panels -> project grid -> activity & physical.
import { esc, ago, fmt } from "../util.js";
import { icon } from "../icons.js";
import { ring, donut, columns, stackedBars, tipRow, TOOL } from "../charts.js";
import {
  PHASE_COLOR, STATUS_META, TYPE_META, typeColor, portfolioStats, nextUp, attention,
  almostDone, upcomingMilestones, recentActivity, recentlyCompleted, sumActivity, filterSort, SORTS, STATUS_FILTERS,
} from "../model.js";
import {
  projectCard, projectRow, statTile, projectChip, panel, empty, href, levelChip, sourceTag, dueLabel,
} from "../components.js";
import { state } from "../state.js";
import { physicalMini } from "./physical.js";
import { plannerBlock } from "./planner.js";

export function dashboardView() {
  const projects = state.data.projects;
  const s = portfolioStats(projects);
  return `
  <div class="page-head">
    <div><div class="eyebrow">${icon("layers", 14)}Command center</div><h1>What you're building</h1>
      <p>${s.total} digital projects · ${s.active} active · ${fmt(s.openTasks)} open tasks${s.analyzed < s.total ? ` · ${s.total - s.analyzed} not yet analyzed by AI` : ""}</p></div>
  </div>
  ${plannerBlock()}
  ${portfolioOverview(projects, s)}
  ${focusRow(projects)}
  ${projectsSection(projects)}
  ${bottomRow(projects)}`;
}

// ------------------------------------------------------------------ portfolio overview

function portfolioOverview(projects, s) {
  const statusSegs = s.byStatus.map((x) => ({ label: x.key, value: x.count, color: STATUS_META[x.key].color }));
  const filter = (v) => `data-act="quickFilter" data-v="${v}"`;
  return `<section class="hero card" aria-label="Portfolio overview">
    <div class="hero-grid">
      <div class="hero-ring">
        ${ring(s.overall, { size: 196, stroke: 16, label: "Portfolio complete", sub: `avg of ${s.overallBase} projects`,
          tip: `<div class="tt-title">Portfolio completion</div>Average progress of ${s.overallBase} projects (paused ones excluded).` })}
        <div class="hero-ring-foot">
          <span>${icon("gauge", 14)}Avg health <b>${s.avgHealth ?? "–"}</b></span>
          <span>${icon("sparkles", 14)}<b>${s.analyzed}</b>/${s.total} analyzed</span>
        </div>
      </div>
      <div class="hero-tiles">
        ${statTile({ icon: "layers", label: "Active projects", value: s.active, color: "var(--s1)", act: filter("active") })}
        ${statTile({ icon: "code", label: "In development", value: s.inDevelopment, color: "var(--s7)", act: filter("all"), tip: "Design, Development, Testing or Deployment" })}
        ${statTile({ icon: "rocket", label: "Almost done", value: s.closeToDone, sub: "≥75% complete", color: "var(--s3)", act: filter("close") })}
        ${statTile({ icon: "lock", label: "Blocked", value: s.blocked, color: "var(--critical)", act: filter("blocked") })}
        ${statTile({ icon: "trophy", label: "Completed", value: s.completed, color: "var(--good)", act: filter("completed") })}
        ${statTile({ icon: "list", label: "Open tasks", value: s.openTasks, color: "var(--s4)" })}
        ${statTile({ icon: "checkCircle", label: "Tasks done", value: s.doneTasks, sub: s.totalTasks ? `${Math.round((s.doneTasks / s.totalTasks) * 100)}% of ${fmt(s.totalTasks)}` : "", color: "var(--s6)" })}
        ${statTile({ icon: "zap", label: "High-priority tasks", value: s.highTasks, color: "var(--serious)" })}
      </div>
      <div class="hero-donut">
        <h3>Project status</h3>
        ${donut(statusSegs, { size: 156, stroke: 20, center: String(s.total), centerSub: "projects" })}
        <ul class="legend vertical">${s.byStatus.map((x) => `<li><span class="sw" style="background:${STATUS_META[x.key].color}"></span>${icon(STATUS_META[x.key].icon, 13)}${x.key}<b>${x.count}</b></li>`).join("")}</ul>
      </div>
    </div>
    <div class="hero-lower">
      <div class="hl-block">
        <h3>Lifecycle stage</h3>
        ${columns(s.byPhase.map((x, i) => ({
          label: x.key, value: x.items.length, color: PHASE_COLOR[i],
          tip: `<div class="tt-title">${x.key} · ${x.items.length}</div>${x.items.slice(0, 8).map((p) => `<div class="small">${esc(p.name)} · ${p.progress}%</div>`).join("") || '<div class="small muted">No projects</div>'}`,
        })), { height: 120 })}
      </div>
      <div class="hl-block">
        <h3>Task completion by project</h3>
        ${taskBars(projects)}
      </div>
      <div class="hl-block">
        <h3>Project types</h3>
        <div class="type-bars">${s.byType.map((t) => `<div class="tb-row" data-tip="${esc(tipRow(typeColor(t.key), t.key, t.count))}">
          <span class="tb-label">${icon(TYPE_META[t.key].icon, 14)}${esc(t.key)}</span>
          <span class="tb-track"><span style="width:${(t.count / s.total) * 100}%;background:${typeColor(t.key)}"></span></span><b>${t.count}</b></div>`).join("")}</div>
      </div>
    </div>
  </section>`;
}

function taskBars(projects) {
  const rows = projects.filter((p) => p.taskCounts.total).sort((a, b) => b.taskCounts.total - a.taskCounts.total).slice(0, 6);
  if (!rows.length) return empty("Tasks appear here after AI analysis or when you add them on a project.", "list");
  return `<div class="task-bars">${rows.map((p) => {
    const c = p.taskCounts, done = (c.done / c.total) * 100, doing = (c.doing / c.total) * 100;
    return `<a class="tk-row" href="${href(p)}" data-tip="${esc(`<div class="tt-title">${esc(p.name)}</div>${tipRow("var(--s1)", "Done", c.done)}${tipRow("var(--s4)", "In progress", c.doing)}${tipRow("var(--ring-track)", "To do", c.todo)}`)}">
      <span class="tk-name">${esc(p.name)}</span>
      <span class="tk-track"><span class="tk-done" style="width:${done}%"></span><span class="tk-doing" style="width:${doing}%"></span></span>
      <span class="tk-num">${c.done}/${c.total}</span></a>`;
  }).join("")}
  <ul class="legend small-legend"><li><span class="sw" style="background:var(--s1)"></span>Done</li><li><span class="sw" style="background:var(--s4)"></span>In progress</li><li><span class="sw" style="background:var(--ring-track)"></span>To do</li></ul></div>`;
}

// ------------------------------------------------------------------ focus panels

function focusRow(projects) {
  const next = nextUp(projects, 6);
  const att = attention(projects).slice(0, 7);
  const almost = almostDone(projects, 4);
  const miles = upcomingMilestones(projects).slice(0, 5);
  return `<div class="focus-grid">
    ${panel("Work on next", next.length ? `<ol class="next-list">${next.map((n, i) => `
      <li><span class="nl-num">${i + 1}</span><div class="nl-body"><div class="nl-title">${esc(n.title)}${n.doing ? `<span class="doing-tag">In progress</span>` : ""}</div>
        <div class="nl-meta">${projectChip(n.project)}${levelChip(n.priority)}${sourceTag(n.source)}</div></div></li>`).join("")}</ol>`
      : empty("Analyze your projects or add tasks to get suggestions.", "target"), { iconName: "target" })}
    ${panel("Needs attention", att.length ? `<ul class="att-list">${att.map((a) => `
      <li class="att-${a.level}"><span class="att-ico">${icon(a.level === "critical" ? "lock" : "alert", 15)}</span>
        <div><div class="att-title">${esc(a.title)}</div><div class="att-meta">${projectChip(a.project)}<span class="att-tag">${esc(a.tag)}</span></div></div></li>`).join("")}</ul>`
      : empty("Nothing needs you right now.", "checkCircle"), { iconName: "alert" })}
    <div class="focus-stack">
      ${panel("Almost finished", almost.length ? `<ul class="almost">${almost.map((p) => `
        <li><a href="${href(p)}"><span class="al-name">${esc(p.name)}</span><span class="al-bar"><span style="width:${p.progress}%"></span></span><b>${p.progress}%</b></a></li>`).join("")}</ul>`
        : empty("No project is past 60% yet.", "rocket"), { iconName: "rocket" })}
      ${panel("Upcoming milestones", miles.length ? `<ul class="miles">${miles.map((m) => `
        <li>${icon(m.kind === "target" ? "flag" : "target", 14)}<div><div class="ms-title">${esc(m.title)}</div><div class="ms-meta">${projectChip(m.project)}${dueLabel(m.due)}</div></div></li>`).join("")}</ul>`
        : empty("No milestones yet.", "flag"), { iconName: "flag" })}
    </div>
  </div>`;
}

// ------------------------------------------------------------------ project grid

function projectsSection(projects) {
  const ui = state.ui;
  const list = filterSort(projects, ui);
  const types = [...new Set(projects.map((p) => p.type))].sort();
  const counts = Object.fromEntries(Object.entries(STATUS_FILTERS).map(([k, f]) => [k, projects.filter(f.fn).length]));
  const settings = state.data.settings;
  const pending = projects.filter((p) => !p.ai || p.ai.stale).length;
  return `<section class="section" id="projects">
    <div class="section-title"><h2>${icon("grid", 18)}Digital projects <span class="count">${list.length}</span></h2>
      <div class="ai-bar">
        ${settings.claude_found ? `
        <label class="ai-model" title="Model used for AI analysis">${icon("sparkles", 14)}<select data-act="setModel" aria-label="AI model">${Object.entries(settings.models).map(([k, v]) => `<option value="${k}" ${k === settings.model ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
        <button class="btn primary" data-act="analyzeChanged" ${pending ? "" : "disabled"}>${icon("sparkles", 15)}Analyze new & changed (${pending})</button>
        <button class="btn danger" data-act="stopAnalysis" data-when-active hidden>${icon("x", 15)}Stop</button>` : `<span class="muted small">Install the Claude Code VS Code extension to enable AI analysis.</span>`}
        ${state.data.meta.browser ? `<button class="btn" data-act="generatePreviews" title="Capture screenshots for projects with a live URL or local web page">${icon("image", 15)}Previews</button>` : ""}
      </div>
    </div>
    <div class="queue-line" id="queueStatus"></div>
    <div class="toolbar">
      <div class="search-box">${icon("search", 16)}<input type="search" class="search" placeholder="Search projects, tech, phase…" value="${esc(ui.q)}" aria-label="Search projects"></div>
      <div class="seg" role="group" aria-label="Filter by status">${Object.entries(STATUS_FILTERS).map(([k, f]) =>
        `<button class="${ui.status === k ? "on" : ""}" data-act="setUi" data-k="status" data-v="${k}">${f.label}<span>${counts[k]}</span></button>`).join("")}</div>
      <select data-act="setUiSelect" data-k="type" aria-label="Filter by type"><option value="all">All types</option>${types.map((t) => `<option ${ui.type === t ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
      <select data-act="setUiSelect" data-k="sort" aria-label="Sort projects">${Object.entries(SORTS).map(([k, s]) => `<option value="${k}" ${ui.sort === k ? "selected" : ""}>Sort: ${s.label}</option>`).join("")}</select>
      <div class="seg icons" role="group" aria-label="View">
        <button class="${ui.view === "grid" ? "on" : ""}" data-act="setUi" data-k="view" data-v="grid" aria-label="Grid view">${icon("grid", 16)}</button>
        <button class="${ui.view === "list" ? "on" : ""}" data-act="setUi" data-k="view" data-v="list" aria-label="List view">${icon("list", 16)}</button>
      </div>
    </div>
    ${list.length ? (ui.view === "list"
      ? `<div class="plist"><div class="prow head"><span></span><span>Project</span><span>Type</span><span>Stage</span><span>Progress</span><span>Tasks</span><span>Priority · Status</span><span>Updated</span></div>${list.map(projectRow).join("")}</div>`
      : `<div class="pgrid">${list.map(projectCard).join("")}</div>`)
      : empty("No projects match these filters.", "search")}
    ${hiddenStrip()}
  </section>`;
}

function hiddenStrip() {
  const hidden = state.data.digital.hidden;
  if (!hidden.length) return "";
  return `<details class="hidden-strip"><summary>${icon("eyeOff", 14)}${hidden.length} hidden project(s)</summary>
    <div class="chips">${hidden.map((h) => `<button class="btn small" data-act="unhide" data-key="${esc(h.key)}">${esc(h.name)} ${icon("refresh", 12)}</button>`).join("")}</div></details>`;
}

// ------------------------------------------------------------------ bottom row

const KIND_ICON = { commit: "code", task: "checkCircle", claude: "sparkles", codex: "sparkles", copilot: "sparkles", vscode: "sparkles" };

function bottomRow(projects) {
  const act = recentActivity(projects, 10);
  const done = recentlyCompleted(projects, 8);
  const phys = state.data.physical;
  return `<div class="bottom-grid">
    ${panel("Activity · 30 days", stackedBars(sumActivity(projects), { height: 170 }), { iconName: "activity", cls: "span-2" })}
    ${panel("Recent activity", act.length ? `<ul class="feed">${act.map((e) => `
      <li><span class="feed-ico" style="--fc:${e.kind === "commit" ? "var(--s1)" : TOOL[e.kind]?.color || "var(--good)"}">${icon(KIND_ICON[e.kind] || "activity", 13)}</span>
        <div><div class="feed-text">${esc(e.text)}</div><div class="feed-meta">${projectChip(e.project)}<span>${esc(e.kind === "commit" ? "Commit" : TOOL[e.kind]?.label || "Task done")} · ${esc(ago(e.ts))}</span></div></div></li>`).join("")}</ul>`
      : empty("No recent activity."), { iconName: "clock" })}
    ${panel("Recently completed", done.length ? `<ul class="feed">${done.map((d) => `
      <li><span class="feed-ico" style="--fc:var(--good)">${icon("check", 13)}</span><div><div class="feed-text">${esc(d.title)}</div>
        <div class="feed-meta">${projectChip(d.project)}${sourceTag(d.source)}${d.ts ? `<span>${esc(ago(d.ts))}</span>` : ""}</div></div></li>`).join("")}</ul>`
      : empty("Completed tasks show up here.", "trophy"), { iconName: "trophy" })}
    ${panel("Physical builds", phys.length ? `<div class="phys-mini">${phys.map(physicalMini).join("")}</div>` : empty("No physical projects."), {
      iconName: "tool", action: `<a class="btn small" href="#/physical">All builds</a>`, cls: "span-2" })}
  </div>`;
}
