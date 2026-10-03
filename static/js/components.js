// Reusable UI components built on the canonical project model.
import { esc, ago, fmt, enc, initials, domain, dateLabel } from "./util.js";
import { icon } from "./icons.js";
import { ring } from "./charts.js";
import { PHASES, PHASE_COLOR, STATUS_META, PRIORITY_META, typeMeta, typeColor, phaseIndex } from "./model.js";
import { state } from "./state.js";
import { machineTag } from "./views/settings.js";

export const href = (p) => `#/project/${enc(p.id)}`;

export function statusBadge(status) {
  const m = STATUS_META[status] || STATUS_META.Active;
  return `<span class="badge status-${m.cls}">${icon(m.icon, 13)}${esc(status)}</span>`;
}

export function priorityBadge(priority, { short = false } = {}) {
  const m = PRIORITY_META[priority] || PRIORITY_META.Medium;
  return `<span class="badge prio-${m.cls}" title="${esc(priority)} priority">${icon(m.icon, 13)}${short ? esc(priority) : esc(priority) + " priority"}</span>`;
}

export function typeChip(type) {
  return `<span class="type-chip" style="--tc:${typeColor(type)}">${icon(typeMeta(type).icon, 13)}${esc(type)}</span>`;
}

export function levelChip(level, word) {
  return `<span class="lvl-chip lvl-${esc(level)}">${esc(word || level)}</span>`;
}

export function sourceTag(source) {
  if (source === "ai") return `<span class="src-tag" title="Suggested by AI analysis">${icon("sparkles", 11)}AI</span>`;
  if (source === "doc") return `<span class="src-tag" title="From a checklist in the project's docs">${icon("note", 11)}Doc</span>`;
  return "";
}

/** Small "where did this value come from" marker. */
export function sourceHint(src) {
  return { you: "set by you", ai: "AI estimate", estimate: "auto-estimated", scan: "from files" }[src] || "";
}

export function miniStepper(phase) {
  const cur = phaseIndex(phase);
  return `<span class="mini-steps" aria-label="Stage ${cur + 1} of ${PHASES.length}: ${esc(phase)}">${PHASES.map((ph, i) =>
    `<i class="${i < cur ? "past" : i === cur ? "now" : ""}" style="--pc:${PHASE_COLOR[i]}" title="${ph}"></i>`).join("")}</span>`;
}

export function lifecycle(phase, phaseProgress) {
  const cur = phaseIndex(phase);
  return `<ol class="lifecycle" aria-label="Lifecycle: ${esc(phase)}">${PHASES.map((ph, i) => `
    <li class="${i < cur ? "past" : i === cur ? "now" : ""}" style="--pc:${PHASE_COLOR[i]}">
      <span class="lc-node">${i < cur ? icon("check", 14) : i + 1}</span>
      <span class="lc-label">${ph}</span>
      ${i === cur && phaseProgress != null ? `<span class="lc-sub">${phaseProgress}% through</span>` : ""}
    </li>`).join("")}</ol>`;
}

export function placeholder(p) {
  return `<div class="ph" style="--tc:${typeColor(p.type)}">
    <div class="ph-glyph">${icon(typeMeta(p.type).icon, 30)}</div>
    <div class="ph-initials">${esc(initials(p.name))}</div>
    <div class="ph-note">${p.previewError ? "Preview failed" : "No preview yet"}</div></div>`;
}

/** Browser or phone frame around the project's preview image (or a placeholder). */
export function previewFrame(p, { large = false } = {}) {
  const img = p.previewImage
    ? `<img src="${esc(p.previewImage)}" alt="Preview of ${esc(p.name)}" loading="lazy" decoding="async">`
    : placeholder(p);
  const job = state.data?.analysis?.previews?.[p.id];
  const busy = job && job.status !== "error" ? `<div class="pv-busy"><span class="spinner"></span>Capturing preview…</div>` : "";
  if (p.previewDevice === "phone") {
    return `<div class="pv pv-phone ${large ? "large" : ""}" style="--tc:${typeColor(p.type)}"><div class="phone">${img}</div>${busy}</div>`;
  }
  const url = p.liveUrl ? domain(p.liveUrl) : p.previewUrl ? domain(p.previewUrl) : (p.facts.path || p.name).split(/[\\/]/).pop();
  return `<div class="pv pv-browser ${large ? "large" : ""}" style="--tc:${typeColor(p.type)}">
    <div class="browser"><div class="b-bar"><i></i><i></i><i></i><span class="b-url">${icon(p.liveUrl ? "lock" : "code", 10)}${esc(url)}</span></div>
    <div class="b-screen">${img}</div></div>${busy}</div>`;
}

export function jobLine(id) {
  return `<span class="job-slot" data-job="${esc(id)}"></span>`;
}

export function projectCard(p, i = 0) {
  const c = p.taskCounts;
  return `<a class="pcard" href="${href(p)}" style="--i:${i};--tc:${typeColor(p.type)}" aria-label="Open ${esc(p.name)}">
    <div class="pc-preview">${previewFrame(p)}
      <div class="pc-badges">${priorityBadge(p.priority, { short: true })}${statusBadge(p.status)}</div></div>
    <div class="pc-body">
      <div class="pc-head">
        <span class="type-ico">${icon(typeMeta(p.type).icon, 18)}</span>
        <div class="pc-title"><h3>${esc(p.name)}</h3><div class="pc-sub">${esc(p.type)} · ${esc(ago(p.updatedAt))} ${machineTag(p)}</div></div>
      </div>
      <p class="pc-desc">${esc(p.oneLiner || "No description yet. Run AI analysis or add one.")}</p>
      <div class="pc-metrics">
        ${ring(p.progress, { size: 68, stroke: 7, color: p.status === "Completed" ? "var(--good)" : "var(--accent)" })}
        <div class="pc-facts">
          <div class="pc-phase"><span>${esc(p.phase)}</span>${miniStepper(p.phase)}</div>
          <div class="pc-tasks">${icon("checkCircle", 14)}<span><b>${c.done}</b>/${c.total} tasks</span>
            <span class="mini-bar"><span style="width:${c.total ? (c.done / c.total) * 100 : 0}%"></span></span></div>
          <div class="pc-health">${p.health != null ? `${icon("gauge", 14)}Health <b>${p.health}</b>` : `${icon("sparkles", 14)}<span class="muted">Not analyzed</span>`}${p.ai?.stale ? `<span class="muted"> · outdated</span>` : ""}</div>
        </div>
      </div>
    </div>
    <div class="pc-foot">${jobLine(p.id)}<span class="pc-open">Open project ${icon("arrowRight", 14)}</span></div>
  </a>`;
}

export function projectRow(p, i = 0) {
  const c = p.taskCounts;
  return `<a class="prow" href="${href(p)}" style="--i:${i};--tc:${typeColor(p.type)}">
    <div class="pr-thumb">${p.previewImage ? `<img src="${esc(p.previewImage)}" alt="" loading="lazy">` : `<span>${icon(typeMeta(p.type).icon, 18)}</span>`}</div>
    <div class="pr-name"><b>${esc(p.name)} ${machineTag(p)}</b><span>${esc(p.oneLiner || p.type)}</span></div>
    <div class="pr-type">${typeChip(p.type)}</div>
    <div class="pr-phase"><span>${esc(p.phase)}</span>${miniStepper(p.phase)}</div>
    <div class="pr-progress"><span class="bar"><span style="width:${p.progress}%"></span></span><b>${p.progress}%</b></div>
    <div class="pr-tasks">${c.done}/${c.total}</div>
    <div class="pr-badges">${priorityBadge(p.priority, { short: true })}${statusBadge(p.status)}</div>
    <div class="pr-updated">${esc(ago(p.updatedAt))}${jobLine(p.id)}</div>
  </a>`;
}

export function statTile({ icon: ic, label, value, sub = "", color = "var(--accent)", act = "", tip = "" }) {
  const tag = act ? "button" : "div";
  return `<${tag} class="stat-tile" style="--sc:${color}" ${act} ${tip ? `title="${esc(tip)}"` : ""}>
    <span class="st-ico">${icon(ic, 18)}</span>
    <span class="st-val">${esc(typeof value === "number" ? fmt(value) : value)}</span>
    <span class="st-label">${esc(label)}</span>${sub ? `<span class="st-sub">${esc(sub)}</span>` : ""}
  </${tag}>`;
}

export function projectChip(p) {
  return `<a class="proj-chip" href="${href(p)}" style="--tc:${typeColor(p.type)}">${icon(typeMeta(p.type).icon, 12)}${esc(p.name)}</a>`;
}

export function panel(title, body, { iconName = "", action = "", cls = "" } = {}) {
  return `<section class="card panel ${cls}"><header class="panel-head"><h2>${iconName ? icon(iconName, 18) : ""}${esc(title)}</h2>${action}</header>${body}</section>`;
}

export function empty(text, iconName = "sparkles") {
  return `<div class="empty-state">${icon(iconName, 22)}<span>${esc(text)}</span></div>`;
}

export function dueLabel(day) {
  if (!day) return `<span class="muted">No date</span>`;
  const d = Math.round((new Date(day + "T12:00:00") - Date.now()) / 86400000);
  const rel = d < 0 ? `${-d}d overdue` : d === 0 ? "today" : `in ${d}d`;
  return `<span class="${d < 0 ? "overdue" : d <= 7 ? "soon" : ""}">${esc(dateLabel(day))} · ${rel}</span>`;
}
