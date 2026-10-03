// Physical builds (manual progress).
import { esc, fmt, money, dateLabel } from "../util.js";
import { icon } from "../icons.js";
import { ring, lineChart } from "../charts.js";
import { empty } from "../components.js";
import { state } from "../state.js";

export const PHYS_CATEGORIES = ["Drone", "Car", "3D Printing", "Electronics", "Woodworking", "Home", "Other"];
export const PHYS_STATUS = ["planning", "active", "paused", "done"];
const STATUS_LABEL = { planning: "Planning", active: "Active", paused: "Paused", done: "Done" };
const STATUS_CLS = { planning: "paused", active: "active", paused: "paused", done: "completed" };
const STATUS_ICON = { planning: "note", active: "play", paused: "pause", done: "checkCircle" };

const physBadge = (s) => `<span class="badge status-${STATUS_CLS[s]}">${icon(STATUS_ICON[s], 13)}${STATUS_LABEL[s]}</span>`;

export function physicalMini(p) {
  return `<a class="phys-chip" href="#/physical/${p.id}" style="--tc:var(--s${p.color})">
    ${ring(p.progress, { size: 52, stroke: 6, color: `var(--s${p.color})` })}
    <div><b>${esc(p.name)}</b><span>${esc(p.category)} · ${p.milestones.filter((m) => m.done).length}/${p.milestones.length} milestones</span></div></a>`;
}

function physicalCard(p, i) {
  const c = `var(--s${p.color})`;
  return `<a class="card phcard" href="#/physical/${p.id}" style="--tc:${c};--i:${i}">
    <div class="phc-top">${ring(p.progress, { size: 84, stroke: 8, color: c })}
      <div><h3>${esc(p.name)}</h3><div class="pc-sub">${esc(p.category)} · ${p.last_update ? "updated " + esc(dateLabel(p.last_update)) : "no updates yet"}</div>
      <div style="margin-top:8px">${physBadge(p.status)}</div></div></div>
    <div class="phc-stats">
      <span>${icon("flag", 14)}<b>${p.milestones.filter((m) => m.done).length}/${p.milestones.length}</b> milestones</span>
      <span>${icon("clock", 14)}<b>${fmt(p.hours)}</b> h</span>
      <span>${icon("store", 14)}<b>${money(p.spent)}</b>${p.budget ? ` / ${money(p.budget)}` : ""}</span>
    </div></a>`;
}

export function physicalView() {
  const phys = state.data.physical;
  return `<div class="page-head"><div><div class="eyebrow">${icon("tool", 14)}Workshop</div><h1>Physical builds</h1>
      <p>Builds and repairs you log by hand: progress, milestones, hours and money.</p></div>
    <button class="btn primary" data-act="newPhysical">${icon("plus", 15)}New build</button></div>
  <div class="phgrid">${phys.map(physicalCard).join("") || empty("No physical projects yet.")}</div>`;
}

export function physicalDetail(id) {
  const p = state.data.physical.find((x) => x.id === id);
  if (!p) return `<a class="back" href="#/physical">${icon("arrowLeft", 15)}Physical builds</a>${empty("Build not found.")}`;
  const c = `var(--s${p.color})`;
  const today = new Date().toISOString().slice(0, 10);
  const prog = p.updates.filter((u) => u.progress != null).slice().reverse().map((u) => ({ label: dateLabel(u.day), v: u.progress, note: u.note }));
  const sig = p.signals.length ? `<ul class="att-list">${p.signals.map((s) => `<li class="att-${s.level}"><span class="att-ico">${icon("alert", 15)}</span><div><div class="att-title">${esc(s.action)}</div><div class="t-detail">${esc(s.text)}</div></div></li>`).join("")}</ul>` : "";
  return `<a class="back" href="#/physical">${icon("arrowLeft", 15)}Physical builds</a>
  <section class="card phero phys-hero" style="--tc:${c}">
    <div class="phys-ring">${ring(p.progress, { size: 150, stroke: 13, label: "complete", color: c })}</div>
    <div class="phero-info">
      <div class="badges-row"><span class="type-chip" style="--tc:${c}">${icon("tool", 13)}${esc(p.category)}</span>${physBadge(p.status)}</div>
      <h1>${esc(p.name)}</h1><p class="phero-one">${esc(p.description || "")}</p>
      <div class="metric-grid wide">
        <div class="metric"><span>Milestones</span><b>${p.milestones.filter((m) => m.done).length}/${p.milestones.length}</b></div>
        <div class="metric"><span>Hours logged</span><b>${fmt(p.hours)}</b></div>
        <div class="metric"><span>Spent</span><b>${money(p.spent)}</b></div>
        <div class="metric"><span>Budget left</span><b>${p.budget ? money(p.budget - p.spent) : "–"}</b></div>
        <div class="metric"><span>Target</span><b>${p.target_date ? esc(dateLabel(p.target_date)) : "–"}</b></div>
      </div>
      <div class="phero-actions"><button class="btn" data-act="editPhysical" data-id="${p.id}">${icon("edit", 15)}Edit</button>
        <button class="btn ghost danger" data-act="deletePhysical" data-id="${p.id}">${icon("x", 15)}Delete</button></div>
      ${sig}
    </div>
  </section>
  <div class="grid-2 section">
    <section class="card panel"><header class="panel-head"><h2>${icon("edit", 18)}Log progress</h2></header>
      <form class="form" data-act="addUpdate" data-id="${p.id}">
        <label class="field">How far along is it now?
          <div class="range-row"><input type="range" name="progress" min="0" max="100" step="5" value="${p.progress}" data-live-output><output>${p.progress}%</output></div></label>
        <label class="field">What did you do?<textarea name="note" placeholder="e.g. Mounted motors, soldered ESC leads, first bench test" required></textarea></label>
        <div class="row3">
          <label class="field">Date<input type="date" name="day" value="${today}"></label>
          <label class="field">Hours<input type="number" name="hours" min="0" step="0.25" placeholder="0"></label>
          <label class="field">Cost ($)<input type="number" name="cost" min="0" step="0.01" placeholder="0"></label>
        </div>
        <div><button class="btn primary">${icon("check", 15)}Save update</button></div>
      </form></section>
    <section class="card panel"><header class="panel-head"><h2>${icon("flag", 18)}Milestones</h2></header>
      ${p.milestones.length ? `<ul class="tlist">${p.milestones.map((m) => `
        <li class="titem ${m.done ? "done" : ""}"><button class="tstat tstat-${m.done ? "done" : "todo"}" data-act="togglePhysMilestone" data-id="${m.id}" data-done="${m.done ? 1 : 0}" aria-label="Toggle milestone">${icon(m.done ? "checkCircle" : "circle", 18)}</button>
          <div class="t-body"><div class="t-title">${esc(m.title)}</div></div>
          <button class="icon-x" data-act="deletePhysMilestone" data-id="${m.id}" aria-label="Delete milestone">${icon("x", 13)}</button></li>`).join("")}</ul>` : empty("No milestones yet.", "flag")}
      <form class="inline-add" data-act="addPhysMilestone" data-id="${p.id}"><input name="title" placeholder="Add a milestone" required><button class="btn">Add</button></form>
    </section>
  </div>
  <div class="grid-2 section">
    <section class="card panel"><header class="panel-head"><h2>${icon("activity", 18)}Progress over time</h2></header>${prog.length ? lineChart(prog, { color: c }) : empty("Log your first update to see the curve.", "activity")}</section>
    <section class="card panel"><header class="panel-head"><h2>${icon("clock", 18)}Build log</h2></header>${p.updates.length ? `<ul class="mtimeline">${p.updates.map((u) => `
      <li class="done"><span class="m-node" style="background:${c};border-color:${c}"></span><div class="m-body"><div class="m-title">${esc(u.note)}</div>
        <div class="m-due">${esc(dateLabel(u.day))}${u.progress != null ? ` · ${u.progress}%` : ""}${u.hours ? ` · ${fmt(u.hours)} h` : ""}${u.cost ? ` · ${money(u.cost)}` : ""}</div></div>
        <button class="icon-x" data-act="deleteUpdate" data-id="${u.id}" aria-label="Delete entry">${icon("x", 13)}</button></li>`).join("")}</ul>` : empty("Nothing logged yet.", "clock")}</section>
  </div>`;
}

export function physicalDialog(p) {
  const d = document.createElement("dialog");
  const v = p || { name: "", category: "Other", status: "planning", description: "", budget: "", target_date: "", color: (state.data.physical.length % 8) + 1 };
  d.innerHTML = `<form method="dialog" class="form">
    <h2>${p ? "Edit build" : "New physical build"}</h2>
    <label class="field">Name<input name="name" value="${esc(v.name)}" required></label>
    <div class="row2">
      <label class="field">Category<select name="category">${PHYS_CATEGORIES.map((c) => `<option ${c === v.category ? "selected" : ""}>${c}</option>`).join("")}</select></label>
      <label class="field">Status<select name="status">${PHYS_STATUS.map((s) => `<option value="${s}" ${s === v.status ? "selected" : ""}>${STATUS_LABEL[s]}</option>`).join("")}</select></label>
    </div>
    <label class="field">Description<textarea name="description">${esc(v.description)}</textarea></label>
    <div class="row2">
      <label class="field">Budget ($)<input type="number" name="budget" min="0" step="1" value="${v.budget ?? ""}"></label>
      <label class="field">Target date<input type="date" name="target_date" value="${esc(v.target_date || "")}"></label>
    </div>
    <div class="field">Color<div class="swatches">${[1, 2, 3, 4, 5, 6, 7, 8].map((s) => `<input type="radio" name="color" value="${s}" id="sw${s}" ${s == v.color ? "checked" : ""}><label for="sw${s}" style="background:var(--s${s})" title="Color ${s}"></label>`).join("")}</div></div>
    <div class="dialog-actions"><button class="btn" value="cancel" formnovalidate>Cancel</button><button class="btn primary" value="save">Save</button></div>
  </form>`;
  document.body.appendChild(d);
  d.showModal();
  return new Promise((resolve) => d.addEventListener("close", () => {
    const data = Object.fromEntries(new FormData(d.querySelector("form")));
    d.remove();
    resolve(d.returnValue === "save" ? data : null);
  }));
}
