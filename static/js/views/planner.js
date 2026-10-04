// AI Daily Planner: the dashboard block (Today's Focus, Priority Queue, Today's Tasks, AI Context) and the Daily History view.
import { esc, dateLabel, enc } from "../util.js";
import { icon } from "../icons.js";
import { ring, tipAttr, tipRow } from "../charts.js";
import { panel, empty } from "../components.js";
import { typeColor } from "../model.js";
import { state } from "../state.js";

const LEVELS = ["Critical", "High", "Medium", "Low"];
const STATUS_STEPS = [["todo", "Not started", "reopen"], ["doing", "In progress", "start"], ["done", "Complete", "complete"]];
const EXAMPLES = [
  "My boss wants MaterialOS QR codes prioritized.",
  "Pause work on Kindling this week.",
  "I only have two hours available today.",
  "Focus on backend work today.",
  "Do not work on Palma Guerro today.",
  "I finished the QR generator yesterday.",
];
const KIND_ICON = { focus: "target", pause: "pause", avoid_today: "eyeOff", deadline: "flag", time_limit: "clock", focus_area: "layers", blocker: "alert", completed: "checkCircle", note: "note", release: "refresh" };
const SOURCE_WORD = { me: "You", manager: "Your manager", client: "A client", collaborator: "A collaborator" };

export const dur = (m) => {
  if (m == null) return "N/A";
  m = Math.round(m);
  return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h${m % 60 ? ` ${m % 60}m` : ""}`;
};
const dayTitle = (day) => new Date(day + "T12:00:00").toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
const projLink = (key, name) => key
  ? `<a class="proj-chip" href="#/project/${enc(key)}" style="--tc:${typeColor(state.data.projects.find((p) => p.id === key)?.type)}">${esc(name)}</a>`
  : name ? `<span class="proj-chip" style="--tc:var(--muted)">${esc(name)}</span>` : "";
const prioChip = (p) => `<span class="pl-chip pl-${esc(p)}" title="${esc(p)} priority">${esc(p)}</span>`;
const job = () => state.data.analysis?.planner || { status: "idle" };
const busy = () => job().status === "running";

// ------------------------------------------------------------------ dashboard block

export function plannerBlock() {
  const pl = state.data.planner;
  if (!pl) return "";
  return `<section class="plan" aria-label="Daily planner">
    ${focusHero(pl)}
    <div class="plan-grid">
      <div class="plan-main">${tasksPanel(pl)}</div>
      <div class="plan-side">${contextPanel(pl)}${queuePanel(pl)}</div>
    </div>
  </section>`;
}

function timeMeter(pl) {
  const s = pl.summary, avail = pl.availableMin;
  if (!s.planned) return `<div class="tm"><div class="tm-head"><b>Time</b><span>N/A</span></div></div>`;
  const total = Math.max(avail, s.plannedMin), left = Math.max(0, s.plannedMin - s.doneMin);
  const over = s.plannedMin > avail;
  const tip = tipRow("var(--accent)", "Done", dur(s.doneMin)) + tipRow("color-mix(in srgb, var(--accent) 38%, transparent)", "Still to do", dur(left))
    + tipRow("var(--surface-3)", "Free", dur(Math.max(0, avail - s.plannedMin))) + tipRow("var(--text-2)", "Available today", dur(avail));
  return `<div class="tm">
    <div class="tm-head"><b>Time</b><span class="${over ? "over" : ""}">${dur(s.plannedMin)} planned of ${dur(avail)}${over ? " (over)" : ""}</span></div>
    <div class="tm-bar" ${tipAttr(tip)} role="img" aria-label="${dur(s.plannedMin)} planned of ${dur(avail)} available">
      <i class="done" style="width:${(s.doneMin / total) * 100}%"></i><i class="todo" style="width:${(left / total) * 100}%"></i>
      ${over ? `<em style="left:${(avail / total) * 100}%" title="Available time ends here"></em>` : ""}
    </div></div>`;
}

function focusHero(pl) {
  const p = pl.plan, s = pl.summary, j = job();
  const cloud = state.data.access?.cloud;
  const done = s.planned ? Math.round((s.done / s.planned) * 100) : 0;
  const chip = !p ? "" : p.source === "ai"
    ? `<span class="ai-chip" title="Written by the AI from the ranked candidates">${icon("sparkles", 12)}AI plan</span>`
    : `<span class="ai-chip rules" title="Built from the scoring rules without the AI. Press Regenerate for an AI-written plan.">${icon("gauge", 12)}Rules-based</span>`;
  const running = busy() ? `<div class="plan-job"><span class="spinner"></span><span data-plan-job>${esc(j.message || "Working")}</span></div>` : "";
  const warn = !busy() && j.warning ? `<div class="plan-warn">${icon("alert", 14)}${esc(j.warning)}</div>` : "";
  const err = !busy() && j.status === "error" ? `<div class="plan-warn">${icon("alert", 14)}Planner failed: ${esc(j.error || "")}</div>` : "";
  return `<div class="focus-hero card">
    <div class="fh-main">
      <div class="eyebrow">${icon("target", 14)}Today's focus · ${esc(dayTitle(pl.day))} ${chip}</div>
      ${p ? `<h2 class="fh-title">${esc(p.headline || "N/A")}</h2><p class="fh-text">${esc(p.focus || "")}</p>`
        : `<h2 class="fh-title muted">N/A</h2><p class="fh-text">No open tasks to plan yet. Add tasks to a project, or tell the AI what you're working on.</p>`}
      ${running}${warn}${err}
      <div class="fh-actions">
        <button class="btn primary" data-act="planRegenerate" ${busy() ? "disabled" : ""} title="${cloud ? "Rebuild from saved tasks, priorities and instructions" : ""}">${icon("refresh", 15, busy() ? "spin" : "")}Regenerate plan</button>
        <a class="btn" href="#/history">${icon("calendar", 15)}Daily history</a>
        ${p?.generatedAt ? `<span class="muted fh-when">Planned ${new Date(p.generatedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>` : ""}
      </div>
    </div>
    <div class="fh-side">
      ${ring(done, { size: 112, stroke: 11, label: "done", tip: `${s.done} of ${s.planned} tasks complete` })}
      <div class="fh-stats">
        <div><b>${s.planned}</b><span>planned</span></div><div><b>${s.doing}</b><span>in progress</span></div><div><b>${s.done}</b><span>complete</span></div>
      </div>
      ${timeMeter(pl)}
    </div>
  </div>`;
}

// ------------------------------------------------------------------ today's tasks

function taskCard(t, i, pl) {
  const ui = state.planUi, open = ui.open[t.id], idx = STATUS_STEPS.findIndex(([s]) => s === t.status);
  const bk = t.breakdown || [];
  const blocked = /waiting|blocked by|needs/i.test(t.blocker_status || "");
  return `<article class="ptask st-${t.status} ${blocked ? "is-blocked" : ""}" data-tid="${t.id}">
    <button class="pt-check" data-act="planTask" data-tid="${t.id}" data-do="${t.status === "done" ? "reopen" : "complete"}"
      aria-label="${t.status === "done" ? "Mark not done" : "Mark complete"}: ${esc(t.title)}">${icon(t.status === "done" ? "checkCircle" : t.status === "doing" ? "half" : "circle", 22)}</button>
    <div class="pt-body">
      <div class="pt-top"><span class="pt-rank">${i + 1}</span><h3 class="pt-title">${esc(t.title)}</h3>${prioChip(t.priority)}
        ${t.origin === "manual" ? `<span class="chip" title="You added or chose this">${icon("edit", 11)}Yours</span>` : ""}
        ${t.accepted && t.origin !== "manual" ? `<span class="chip" title="You accepted this recommendation">${icon("check", 11)}Accepted</span>` : ""}</div>
      <div class="pt-meta">${projLink(t.project_key, t.project_name)}
        <span class="pt-est" title="Estimated time">${icon("clock", 13)}${dur(t.est_minutes)}</span>
        ${t.impact ? `<span class="pt-impact" title="Expected impact">${icon("zap", 13)}${esc(t.impact)}</span>` : ""}</div>
      ${t.reason ? `<p class="pt-reason">${icon("sparkles", 13)}<span>${esc(t.reason)}</span></p>` : ""}
      ${t.blocker_status ? `<p class="pt-block ${blocked ? "warn" : ""}">${icon(blocked ? "lock" : "checkCircle", 13)}<span>${esc(t.blocker_status)}</span></p>` : ""}
      <div class="pt-track" role="group" aria-label="Status">${STATUS_STEPS.map(([s, label, act], k) =>
        `<button class="pt-step ${k < idx ? "past" : ""} ${k === idx ? "on" : ""}" data-act="planTask" data-tid="${t.id}" data-do="${act}" aria-pressed="${k === idx}">${label}</button>`).join("")}</div>
      <div class="pt-actions">
        ${t.accepted || t.origin === "manual" ? "" : `<button class="btn small" data-act="planTask" data-tid="${t.id}" data-do="accept" title="Tell the planner this is a good pick">${icon("check", 13)}Accept</button>`}
        <button class="btn small" data-act="planSkipOpen" data-tid="${t.id}">${icon("x", 13)}Skip</button>
        <button class="btn small" data-act="planTask" data-tid="${t.id}" data-do="move" title="Move to tomorrow's plan">${icon("calendar", 13)}Tomorrow</button>
        <label class="pt-sel" title="Change priority">${icon("flag", 13)}<select data-act="planPriority" data-tid="${t.id}" aria-label="Priority">${LEVELS.map((l) => `<option ${l === t.priority ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <button class="btn small ghost" data-act="planTask" data-tid="${t.id}" data-do="up" aria-label="Move up" ${i === 0 ? "disabled" : ""}>${icon("arrowUp", 13)}</button>
        <button class="btn small ghost" data-act="planTask" data-tid="${t.id}" data-do="down" aria-label="Move down">${icon("arrowDown", 13)}</button>
        ${bk.length ? `<button class="btn small ghost" data-act="planDetails" data-tid="${t.id}" aria-expanded="${!!open}">Why this?</button>` : ""}
        ${t.origin === "manual" && !t.item_id ? `<button class="btn small ghost danger" data-act="planTask" data-tid="${t.id}" data-do="delete">Remove</button>` : ""}
      </div>
      ${ui.skipFor === t.id ? `<form class="pt-skip" data-act="planSkipConfirm" data-tid="${t.id}">
        <input name="reason" type="text" placeholder="Why skip it? (optional, the planner learns from this)" autocomplete="off" maxlength="200">
        <button class="btn small primary" type="submit">Skip task</button><button class="btn small ghost" type="button" data-act="planSkipCancel">Cancel</button></form>` : ""}
      ${open && bk.length ? `<ul class="pt-why">${bk.map((b) => `<li><span>${esc(b.label)}</span><b class="${b.pts < 0 ? "neg" : ""}">${b.pts > 0 ? "+" : ""}${Math.round(b.pts)}</b></li>`).join("")}
        <li class="total"><span>Priority score</span><b>${Math.round(t.score || 0)}</b></li></ul>` : ""}
    </div>
  </article>`;
}

function tasksPanel(pl) {
  const live = pl.tasks.filter((t) => t.status !== "skipped" && t.status !== "moved");
  const parked = pl.tasks.filter((t) => t.status === "skipped" || t.status === "moved");
  const ui = state.planUi;
  const projects = state.data.projects;
  const addForm = ui.addOpen ? `<form class="pt-add" data-act="planAdd">
      <input name="title" type="text" placeholder="Task name" required autocomplete="off" maxlength="200">
      <select name="project_key" aria-label="Project"><option value="">No project</option>${projects.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("")}</select>
      <select name="priority" aria-label="Priority">${LEVELS.map((l) => `<option ${l === "Medium" ? "selected" : ""}>${l}</option>`).join("")}</select>
      <input name="est_minutes" type="number" min="5" max="600" step="5" value="60" aria-label="Minutes" title="Estimated minutes">
      <button class="btn primary small" type="submit">Add to today</button><button class="btn ghost small" type="button" data-act="planAddToggle">Cancel</button></form>` : "";
  const body = (live.length ? `<div class="ptasks">${live.map((t, i) => taskCard(t, i, pl)).join("")}</div>`
    : empty("No tasks on today's list. Regenerate the plan, add one by hand, or tell the AI what you're working on.", "list"))
    + addForm
    + (parked.length ? `<details class="parked"><summary>${parked.length} skipped or moved</summary><ul>${parked.map((t) => `<li>
        <span class="muted">${t.status === "moved" ? "Moved to tomorrow" : "Skipped"}</span><b>${esc(t.title)}</b>${t.project_name ? `<span class="muted"> · ${esc(t.project_name)}</span>` : ""}
        ${t.skip_reason ? `<em class="muted">“${esc(t.skip_reason)}”</em>` : ""}
        <button class="btn small ghost" data-act="planTask" data-tid="${t.id}" data-do="reopen">Put back</button></li>`).join("")}</ul></details>` : "");
  return panel("Today's tasks", body, {
    iconName: "checkCircle", cls: "plan-tasks",
    action: `<button class="btn small" data-act="planAddToggle">${icon("plus", 14)}Add task</button>`,
  });
}

// ------------------------------------------------------------------ priority queue

function queuePanel(pl) {
  const live = pl.tasks.filter((t) => t.status === "todo" || t.status === "doing");
  const all = [...live.map((t) => ({ ...t, on: true, label: t.priority, title: t.title, project: t.project_name, pid: t.project_key })),
    ...pl.next.map((n) => ({ ...n, on: false }))];
  const max = Math.max(60, ...all.map((x) => x.score || 0));
  const row = (x, i) => {
    const bk = (x.breakdown || []).map((b) => tipRow(b.pts < 0 ? "var(--critical)" : "var(--accent)", b.label, (b.pts > 0 ? "+" : "") + Math.round(b.pts))).join("");
    const tip = `<div class="tt-title">${esc(x.title)}</div>${bk}${tipRow("var(--text-2)", "Score", Math.round(x.score || 0))}`;
    return `<li class="${x.on ? "on" : ""}">
      <span class="pq-n">${i + 1}</span>
      <div class="pq-main"><div class="pq-t">${esc(x.title)}</div>
        <div class="pq-s">${projLink(x.pid, x.project)}${prioChip(x.label)}${x.waiting_on ? `<span class="muted">waiting on another step</span>` : ""}</div>
        <div class="pq-bar" ${tipAttr(tip)} role="img" aria-label="Score ${Math.round(x.score || 0)}"><i style="width:${Math.max(3, ((x.score || 0) / max) * 100)}%"></i></div></div>
      ${x.on ? `<span class="pq-tag">Today</span>` : `<button class="btn small" data-act="planPick" data-cid="${esc(x.cid)}" title="Put on today's list">${icon("plus", 13)}Add</button>`}
    </li>`;
  };
  const body = all.length
    ? `<ol class="pq">${all.map(row).join("")}</ol><p class="pq-note muted">Bars show the planner's score: directives, blockers, deadlines, project and task priority, idle time, effort and readiness. Hover a bar for the breakdown.</p>`
    : empty("Nothing ranked yet.", "layers");
  return panel("Priority queue", body, { iconName: "layers", cls: "plan-queue" });
}

// ------------------------------------------------------------------ AI context

function directiveLine(d) {
  const until = d.persist === "until_milestone" ? `until ${d.until_condition || "done"}` : d.persist === "today" ? "today only"
    : d.persist === "this_week" ? `through ${dateLabel(d.until_date)}` : d.persist === "until_date" ? `until ${dateLabel(d.until_date)}` : "until you change it";
  return `<li>
    <span class="dir-ico">${icon(KIND_ICON[d.kind] || "note", 15)}</span>
    <div class="dir-body"><div>${esc(d.summary || d.text)}</div>
      <div class="dir-meta">${esc(SOURCE_WORD[d.source] || "You")}${d.project_name ? ` · ${esc(d.project_name)}` : ""} · ${esc(until)}${d.tracked ? ` · ${d.tracked} steps tracked` : ""}</div></div>
    <button class="icon-x always" data-act="planEndDirective" data-id="${d.id}" title="End this instruction" aria-label="End this instruction">${icon("x", 14)}</button>
  </li>`;
}

function contextPanel(pl) {
  const ui = state.planUi, j = job();
  if (state.data.access?.cloud) {
    return panel("AI context", `<p class="muted">AI-generated instructions require the Claude Code CLI on the local computer. The cloud deployment still supports the deterministic task shortlist and manual task tracking.</p>`, { iconName: "sparkles", cls: "plan-ctx" });
  }
  const reply = j.reply && j.reply !== ui.dismissed ? `<div class="ai-reply">${icon("sparkles", 15)}<p>${esc(j.reply)}</p>
      <button class="icon-x always" data-act="planDismissReply" aria-label="Dismiss">${icon("x", 14)}</button></div>` : "";
  const body = `<form class="ctx-form" data-act="planInstruction">
      <label class="sr-only" for="planText">Tell the AI what changed</label>
      <textarea id="planText" name="text" data-draft rows="3" placeholder="Tell the AI what changed. For example: “My boss told me to continue the MaterialOS QR system.”" ${busy() ? "disabled" : ""}>${esc(ui.draft)}</textarea>
      <div class="ctx-row"><button class="btn primary" type="submit" ${busy() ? "disabled" : ""}>${icon("sparkles", 15)}Update today's priorities</button>
        ${busy() && j.what === "instruction" ? `<span class="plan-job"><span class="spinner"></span><span data-plan-job>${esc(j.message || "Working")}</span></span>` : ""}</div>
      <div class="chips ctx-ex">${EXAMPLES.map((e) => `<button type="button" class="chip ex" data-act="planExample" data-text="${esc(e)}">${esc(e)}</button>`).join("")}</div>
    </form>${reply}
    <h3 class="sub-h">Active instructions</h3>
    ${pl.directives.length ? `<ul class="dirs">${pl.directives.map(directiveLine).join("")}</ul>`
      : empty("No standing instructions. Your project priorities are used as they are.", "note")}
    <p class="pq-note muted">Instructions steer today's plan. They never rewrite your project priorities, and they last until the work is done or you end them.</p>`;
  return panel("AI context", body, { iconName: "sparkles", cls: "plan-ctx" });
}

// ------------------------------------------------------------------ daily history

export function historyView() {
  const days = state.history;
  const head = (sub) => `<div class="page-head"><div><div class="eyebrow">${icon("calendar", 14)}Daily planner</div><h1>Daily history</h1><p>${sub}</p></div>
    <a class="btn" href="#/">${icon("arrowLeft", 15)}Back to dashboard</a></div>`;
  if (!days) return head("Loading…");
  if (!days.length) return head("Each day's plan is saved here.") + panel("No plans yet", empty("N/A. A day shows up here once its plan has been made.", "calendar"));
  const doneAll = days.reduce((a, d) => a + d.done, 0), plannedAll = days.reduce((a, d) => a + d.planned, 0);
  return `${head(`${days.length} day${days.length === 1 ? "" : "s"} planned · ${doneAll} of ${plannedAll} planned tasks completed`)}
    ${panel("Planned vs completed", historyChart(days), { iconName: "activity" })}
    <div class="hist-list">${days.map((d, i) => dayCard(d, i === 0)).join("")}</div>`;
}

function historyChart(days) {
  const shown = days.slice(0, 14).reverse();
  const max = Math.max(1, ...shown.map((d) => d.planned));
  const cols = shown.map((d) => {
    const tip = `<div class="tt-title">${esc(dayTitle(d.day))}</div>${tipRow("var(--s1)", "Completed", d.done)}${tipRow("var(--s2)", "Unfinished", d.unfinished)}${d.skipped + d.moved ? tipRow("var(--muted)", "Skipped or moved", d.skipped + d.moved) : ""}`;
    return `<div class="hc" ${tipAttr(tip)}>
      <div class="hc-track"><div class="hc-stack" style="height:${(d.planned / max) * 100}%">
        ${d.unfinished ? `<i class="u" style="flex:${d.unfinished}"></i>` : ""}${d.done ? `<i class="d" style="flex:${d.done}"></i>` : ""}</div></div>
      <div class="hc-n">${d.done}/${d.planned}</div><div class="hc-l">${esc(dateLabel(d.day))}</div></div>`;
  }).join("");
  const rows = shown.slice().reverse().map((d) => `<tr><td>${esc(dateLabel(d.day))}</td><td>${d.planned}</td><td>${d.done}</td><td>${d.unfinished}</td></tr>`).join("");
  return `<ul class="legend"><li><span class="sw" style="background:var(--s1)"></span>Completed</li><li><span class="sw" style="background:var(--s2)"></span>Unfinished</li></ul>
    <div class="hcols" role="img" aria-label="Tasks planned, completed and unfinished per day">${cols}</div>
    <button class="table-toggle" data-act="toggleTable">Show table</button>
    <table class="data-table" hidden><thead><tr><th>Day</th><th>Planned</th><th>Completed</th><th>Unfinished</th></tr></thead><tbody>${rows}</tbody></table>`;
}

const STATUS_ICON = { done: "checkCircle", doing: "half", todo: "circle", skipped: "x", moved: "calendar" };
const STATUS_WORD = { done: "Complete", doing: "In progress", todo: "Not started", skipped: "Skipped", moved: "Moved to tomorrow" };

function dayCard(d, open) {
  const dirs = (d.directives || []).map((x) => (typeof x === "string" ? x : x.summary || x.text)).filter(Boolean);
  const rate = d.planned ? Math.round((d.done / d.planned) * 100) : null;
  return `<details class="card hday" ${open ? "open" : ""}>
    <summary><div class="hd-date"><b>${esc(dayTitle(d.day))}</b><span class="muted">${esc(d.headline || "N/A")}</span></div>
      <div class="hd-stats"><span class="chip">Planned <b>${d.planned}</b></span><span class="chip good">Completed <b>${d.done}</b></span>
        <span class="chip ${d.unfinished ? "warn" : ""}">Unfinished <b>${d.unfinished}</b></span>${rate != null ? `<span class="muted">${rate}%</span>` : ""}</div></summary>
    <div class="hd-body">
      ${d.focus ? `<div class="hd-sec"><h3>Focus summary</h3><p class="prose">${esc(d.focus)}</p></div>` : ""}
      <div class="hd-sec"><h3>Projects worked on</h3>${d.projects.length ? `<div class="chips">${d.projects.map((p) => `<span class="chip">${esc(p)}</span>`).join("")}</div>` : `<span class="muted">N/A. No task was started or completed.</span>`}</div>
      <div class="hd-sec"><h3>Directives that day</h3>${dirs.length ? `<ul class="hd-dirs">${dirs.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<span class="muted">None</span>`}</div>
      <div class="hd-sec wide"><h3>Tasks</h3>${d.tasks.length ? `<ul class="hd-tasks">${d.tasks.map((t) => `<li class="st-${t.status}">${icon(STATUS_ICON[t.status] || "circle", 16)}
        <span class="hd-tt">${esc(t.title)}</span>${t.project_name ? `<span class="muted"> · ${esc(t.project_name)}</span>` : ""}
        <span class="hd-st">${STATUS_WORD[t.status] || t.status}${t.skip_reason ? `: ${esc(t.skip_reason)}` : ""}</span></li>`).join("")}</ul>` : `<span class="muted">N/A</span>`}</div>
    </div>
  </details>`;
}
