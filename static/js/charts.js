// Chart primitives. Each returns an HTML/SVG string. Hover targets carry data-tip="<escaped html>",
// which the single global tooltip handler (initTooltips) renders, so every chart gets tooltips for free.
import { esc, fmt, dateLabel } from "./util.js";

export const SOURCES = [
  { key: "commits", label: "Git commits", color: "var(--s1)" },
  { key: "claude", label: "Claude Code", color: "var(--s2)" },
  { key: "codex", label: "Codex", color: "var(--s3)" },
  { key: "copilot", label: "Copilot", color: "var(--s4)" },
  { key: "vscode", label: "VS Code Chat", color: "var(--s5)" },
];
export const TOOL = Object.fromEntries(SOURCES.map((s) => [s.key, s]));

export const tipAttr = (html) => `data-tip="${esc(html)}"`;
export const tipRow = (color, label, value) =>
  `<div class="tt-row"><span><i class="sw" style="background:${color}"></i>${esc(label)}</span><b>${esc(value)}</b></div>`;

export function initTooltips() {
  const tip = document.getElementById("tooltip");
  let cur = null;
  document.addEventListener("mouseover", (e) => {
    const el = e.target.closest?.("[data-tip]");
    if (el === cur) return;
    document.querySelectorAll(".tip-on").forEach((x) => x.classList.remove("tip-on"));
    cur = el;
    if (!el) { tip.hidden = true; return; }
    el.classList.add("tip-on");
    tip.innerHTML = el.dataset.tip;
    tip.hidden = false;
  });
  document.addEventListener("mousemove", (e) => {
    if (tip.hidden) return;
    const pad = 14, r = tip.getBoundingClientRect();
    let x = e.clientX + pad, y = e.clientY + pad;
    if (x + r.width > innerWidth - 8) x = e.clientX - r.width - pad;
    if (y + r.height > innerHeight - 8) y = e.clientY - r.height - pad;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  });
  document.addEventListener("scroll", () => { tip.hidden = true; cur = null; }, { passive: true });
}

/** Circular progress ring. value 0-100. Animates in when the page container has .animate-in. */
export function ring(value, { size = 72, stroke = 7, color = "var(--accent)", label = null, sub = null, tip = null } = {}) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, v = Math.max(0, Math.min(100, value || 0));
  const off = c * (1 - v / 100);
  const fs = Math.round(size * (label ? 0.24 : 0.26));
  return `<div class="ring" style="width:${size}px;height:${size}px" role="img" aria-label="${esc((label || "Progress") + " " + Math.round(v) + "%")}" ${tip ? tipAttr(tip) : ""}>
    <svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--ring-track)" stroke-width="${stroke}"/>
      <circle class="ring-val" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${color}" stroke-width="${stroke}"
        stroke-linecap="round" stroke-dasharray="${c.toFixed(2)}" stroke-dashoffset="${off.toFixed(2)}" style="--c:${c.toFixed(2)};--o:${off.toFixed(2)}"
        transform="rotate(-90 ${size / 2} ${size / 2})"/>
    </svg>
    <div class="ring-center"><b style="font-size:${fs}px">${Math.round(v)}<small>%</small></b>${label ? `<span>${esc(label)}</span>` : ""}${sub ? `<em>${esc(sub)}</em>` : ""}</div>
  </div>`;
}

/** Donut of categorical/status segments: [{label, value, color}]. 2px surface gap between segments. */
export function donut(segments, { size = 168, stroke = 22, center = "", centerSub = "" } = {}) {
  const total = segments.reduce((a, s) => a + s.value, 0);
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, cx = size / 2;
  let acc = 0, arcs = "";
  const gap = total && segments.filter((s) => s.value).length > 1 ? 2 : 0;
  for (const s of segments) {
    if (!s.value) continue;
    const len = (s.value / total) * c;
    arcs += `<circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="${s.color}" stroke-width="${stroke}"
      stroke-dasharray="${Math.max(0, len - gap).toFixed(2)} ${(c - len + gap).toFixed(2)}" stroke-dashoffset="${(-acc).toFixed(2)}"
      transform="rotate(-90 ${cx} ${cx})" class="donut-seg" ${tipAttr(tipRow(s.color, s.label, `${s.value} (${Math.round((s.value / total) * 100)}%)`))}/>`;
    acc += len;
  }
  if (!total) arcs = `<circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="var(--ring-track)" stroke-width="${stroke}"/>`;
  return `<div class="donut" style="width:${size}px;height:${size}px">
    <svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-label="${esc(segments.map((s) => `${s.label} ${s.value}`).join(", "))}">${arcs}</svg>
    <div class="ring-center"><b style="font-size:${Math.round(size * 0.2)}px">${esc(center)}</b><span>${esc(centerSub)}</span></div></div>`;
}

/** Vertical columns, one per ordered stage: [{label, value, color, tip}] */
export function columns(items, { height = 150 } = {}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return `<div class="cols" style="--h:${height}px">${items.map((it) => `
    <div class="col" ${tipAttr(it.tip || tipRow(it.color, it.label, it.value))}>
      <div class="col-val">${it.value}</div>
      <div class="col-track"><div class="col-bar" style="height:${it.value ? Math.max(6, (it.value / max) * 100) : 0}%;background:${it.color}"></div></div>
      <div class="col-label">${esc(it.label)}</div>
    </div>`).join("")}</div>`;
}

export function niceMax(v) {
  if (v <= 4) return 4;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return v;
}

export function topRounded(x, y, w, h, r) {
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

/** Stacked daily bars by activity source. activity: {day: {source: n}} */
export function stackedBars(activity, { height = 190, title = "Daily activity, last 30 days" } = {}) {
  const days = Object.keys(activity).sort();
  if (!days.length) return `<div class="empty small">No activity data yet.</div>`;
  const present = SOURCES.filter((s) => days.some((d) => activity[d][s.key]));
  const series = present.length ? present : SOURCES.slice(0, 1);
  const totals = days.map((d) => series.reduce((a, s) => a + (activity[d][s.key] || 0), 0));
  const max = niceMax(Math.max(1, ...totals));
  const W = 720, H = height, L = 28, B = 22, T = 6, plotW = W - L, plotH = H - B - T;
  const step = plotW / days.length, bw = Math.max(3, step * 0.62);
  const y = (v) => T + plotH - (v / max) * plotH;
  let svg = "";
  for (let i = 0; i <= 4; i++) {
    const v = (max / 4) * i, yy = y(v);
    svg += `<line class="${i ? "gridline" : "baseline"}" x1="${L}" x2="${W}" y1="${yy}" y2="${yy}"/><text class="tick" x="${L - 6}" y="${yy + 4}" text-anchor="end">${fmt(v)}</text>`;
  }
  days.forEach((d, i) => {
    const x = L + i * step + (step - bw) / 2;
    let acc = 0;
    const segs = series.map((s) => ({ s, v: activity[d][s.key] || 0 })).filter((g) => g.v);
    segs.forEach((g, j) => {
      const y0 = y(acc), y1 = y(acc + g.v), h = Math.max(0, y0 - y1 - (j ? 2 : 0));
      svg += j === segs.length - 1 ? `<path d="${topRounded(x, y1, bw, h, 4)}" fill="${g.s.color}"/>` : `<rect x="${x}" y="${y1}" width="${bw}" height="${h}" fill="${g.s.color}"/>`;
      acc += g.v;
    });
    if (i % Math.ceil(days.length / 6) === 0 || i === days.length - 1)
      svg += `<text class="tick" x="${L + i * step + step / 2}" y="${H - 5}" text-anchor="middle">${dateLabel(d)}</text>`;
    const tip = `<div class="tt-title">${dateLabel(d)} · ${totals[i]} total</div>` + series.map((s) => tipRow(s.color, s.label, activity[d][s.key] || 0)).join("");
    svg += `<rect class="hit" x="${L + i * step}" y="${T}" width="${step}" height="${plotH}" ${tipAttr(tip)}/>`;
  });
  const legend = series.length > 1 ? `<ul class="legend">${series.map((s) => `<li><span class="sw" style="background:${s.color}"></span>${s.label}</li>`).join("")}</ul>` : "";
  const rows = days.slice().reverse().map((d) => [d, totals[days.indexOf(d)]]).filter(([, t]) => t);
  const table = `<table class="data-table" hidden><thead><tr><th>Day</th>${series.map((s) => `<th>${s.label}</th>`).join("")}<th>Total</th></tr></thead><tbody>${
    rows.map(([d, t]) => `<tr><td>${dateLabel(d)}</td>${series.map((s) => `<td>${activity[d][s.key] || 0}</td>`).join("")}<td>${t}</td></tr>`).join("") || `<tr><td colspan="9">No activity</td></tr>`}</tbody></table>`;
  return `<div class="chart">${legend}<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)}">${svg}</svg>
    <button class="table-toggle" data-act="toggleTable">Show table</button>${table}</div>`;
}

export function sparkline(activity, color, { height = 34 } = {}) {
  const days = Object.keys(activity || {}).sort();
  const vals = days.map((d) => Object.values(activity[d]).reduce((a, b) => a + b, 0));
  if (!vals.length) return "";
  const max = Math.max(1, ...vals), W = 240, H = height;
  const pts = vals.map((v, i) => [(i / Math.max(1, vals.length - 1)) * W, H - 3 - (v / max) * (H - 6)]);
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join("");
  const total = vals.reduce((a, b) => a + b, 0);
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${total} activity events in 30 days">
    <path d="${line}L${W},${H}L0,${H}Z" fill="${color}" opacity=".13"/><path d="${line}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>`;
}

export function lineChart(points, { color = "var(--s1)", height = 180, suffix = "%", maxY = 100 } = {}) {
  const W = 720, H = height, L = 34, B = 22, T = 8, plotW = W - L - 8, plotH = H - B - T;
  const x = (i) => L + (points.length === 1 ? plotW / 2 : (i / (points.length - 1)) * plotW);
  const y = (v) => T + plotH - (v / maxY) * plotH;
  let svg = "";
  for (let i = 0; i <= 4; i++) {
    const v = (maxY / 4) * i;
    svg += `<line class="${i ? "gridline" : "baseline"}" x1="${L}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text class="tick" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}${suffix}</text>`;
  }
  svg += `<path d="${points.map((p, i) => (i ? "L" : "M") + x(i) + "," + y(p.v)).join("")}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>`;
  const slice = points.length > 1 ? plotW / (points.length - 1) : plotW;
  points.forEach((p, i) => {
    svg += `<circle cx="${x(i)}" cy="${y(p.v)}" r="4" fill="${color}" stroke="var(--surface)" stroke-width="2"/>`;
    if (i === 0 || i === points.length - 1 || points.length < 7) svg += `<text class="tick" x="${x(i)}" y="${H - 5}" text-anchor="middle">${esc(p.label)}</text>`;
    const tip = `<div class="tt-title">${esc(p.label)}</div>${tipRow(color, "Progress", p.v + suffix)}${p.note ? `<div class="small muted" style="max-width:240px">${esc(p.note)}</div>` : ""}`;
    svg += `<rect class="hit" x="${x(i) - slice / 2}" y="${T}" width="${slice}" height="${plotH}" ${tipAttr(tip)}/>`;
  });
  return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Progress over time">${svg}</svg></div>`;
}
