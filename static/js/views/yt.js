// YT Dashboard: traffic, money and reviews per site/app. Real data only: a panel with no data shows "N/A".
// Expects state.data.yt = { apps: [{ id, name, color, daily: [{ date: "YYYY-MM-DD", visitors, sessions, pageviews, secs,
//   signups, paid, revAds, revSubs, revSales, spHost, spAi, spAds, spTools }], hourly: [7][24] (avg visitors, Sun first),
//   devices: { Mobile, Desktop, Tablet }, countries: [[name, n]], pages: [[path, n]], sources: [[name, n]],
//   ratings: [five, four, three, two, one], reviews: [{ stars, text, date }] }] }. Any field may be missing.
import { esc, fmt, money, dateLabel, ago } from "../util.js";
import { icon } from "../icons.js";
import { donut, tipAttr, tipRow, niceMax, topRounded } from "../charts.js";
import { panel } from "../components.js";
import { state } from "../state.js";

const RANGES = [7, 30, 90];
const DOW_ORDER = [1, 2, 3, 4, 5, 6, 0];
const DOW_NAME = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const STREAMS = [
  { key: "revAds", label: "Ads", color: "var(--s4)" },
  { key: "revSubs", label: "Subscriptions", color: "var(--s3)" },
  { key: "revSales", label: "One-time sales", color: "var(--s5)" },
];
const SPEND = [
  { key: "spHost", label: "Hosting" },
  { key: "spAi", label: "AI usage" },
  { key: "spAds", label: "Advertising" },
  { key: "spTools", label: "Tools & services" },
];
const DEVICE_COLORS = { Mobile: "var(--s1)", Desktop: "var(--s2)", Tablet: "var(--s3)" };
const REV = STREAMS.map((s) => s.key), SP = SPEND.map((s) => s.key);

const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const lastDays = (n, back = 0) => Array.from({ length: n }, (_, i) => { const d = new Date(); d.setDate(d.getDate() - back - (n - 1 - i)); return ymd(d); });

// Sum `keys` across the selected apps for each date. A date with no reported value is null, never 0.
function agg(sel, keys, dates) {
  const maps = sel.map((a) => new Map((a.daily || []).map((d) => [d.date, d])));
  const values = dates.map((dt) => {
    let t = null;
    for (const m of maps) { const d = m.get(dt); if (d) for (const k of keys) if (d[k] != null) t = (t || 0) + d[k]; }
    return t;
  });
  const seen = values.filter((v) => v != null);
  return { values, total: seen.length ? seen.reduce((a, b) => a + b, 0) : null };
}

const NA = `<span class="na-val">N/A</span>`;
const naPanel = (title, iconName, why = "No data yet") => panel(title, `<div class="na"><b>N/A</b><span>${esc(why)}</span></div>`, { iconName });
const orNA = (v, f) => (v == null ? NA : f(v));

// Merge [[label, n]] lists from several apps.
function mergePairs(sel, field) {
  const m = new Map();
  for (const a of sel) for (const [k, n] of a[field] || []) m.set(k, (m.get(k) || 0) + n);
  return [...m].map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value);
}

// ------------------------------------------------------------------ formatting helpers

const compact = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M" : n >= 1e3 ? (n / 1e3).toFixed(n >= 1e4 ? 0 : 1).replace(/\.0$/, "") + "k" : String(Math.round(n * 10) / 10));
const dur = (s) => `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, "0")}s`;
const pctOf = (a, b) => (b ? ((a / b) * 100).toFixed(a / b < 0.1 ? 1 : 0) + "%" : "–");
const stars = (n) => `<span class="stars" role="img" aria-label="${n} out of 5 stars">${"★".repeat(n)}${"☆".repeat(5 - n)}</span>`;
const dot = (color) => `<i class="dot" style="background:${color}"></i>`;


// ------------------------------------------------------------------ chart pieces (one axis each, thin marks, hover on every mark)

function legendOf(series) {
  return series.length > 1 ? `<ul class="legend">${series.map((s) => `<li><span class="sw" style="background:${s.color}"></span>${esc(s.label)}</li>`).join("")}</ul>` : "";
}

function dataTable(labels, series, f) {
  return `<button class="table-toggle" data-act="toggleTable">Show table</button>
    <table class="data-table" hidden><thead><tr><th>Day</th>${series.map((s) => `<th>${esc(s.label)}</th>`).join("")}</tr></thead><tbody>${
      labels.map((d, i) => `<tr><td>${esc(dateLabel(d))}</td>${series.map((s) => `<td>${esc(f(s.values[i]))}</td>`).join("")}</tr>`).reverse().join("")}</tbody></table>`;
}

function xTicks(labels, x, H) {
  const every = Math.ceil(labels.length / 6);
  let svg = "", last = -999;
  labels.forEach((d, i) => {
    if (i % every === 0 || (i === labels.length - 1 && i - last >= every * 0.6)) {
      svg += `<text class="tick" x="${x(i)}" y="${H - 5}" text-anchor="middle">${dateLabel(d)}</text>`;
      last = i;
    }
  });
  return svg;
}

function multiLine(labels, series, { height = 190, f = fmt, prefix = "", title }) {
  const n = labels.length, W = 720, H = height, L = 46, B = 22, T = 8, plotW = W - L - 8, plotH = H - B - T;
  const max = niceMax(Math.max(1, ...series.flatMap((s) => s.values)));
  const x = (i) => L + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v) => T + plotH - (v / max) * plotH;
  let svg = "";
  for (let i = 0; i <= 4; i++) {
    const v = (max / 4) * i;
    svg += `<line class="${i ? "gridline" : "baseline"}" x1="${L}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text class="tick" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${prefix}${compact(v)}</text>`;
  }
  for (const s of series) svg += `<path d="${s.values.map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1)).join("")}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
  svg += xTicks(labels, x, H);
  const slice = n > 1 ? plotW / (n - 1) : plotW;
  labels.forEach((d, i) => {
    const tip = `<div class="tt-title">${esc(dateLabel(d, true))}</div>` + series.map((s) => tipRow(s.color, s.label, f(s.values[i]))).join("");
    svg += `<rect class="hit" x="${x(i) - slice / 2}" y="${T}" width="${slice}" height="${plotH}" ${tipAttr(tip)}/>`;
  });
  return `<div class="chart">${legendOf(series)}<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)}">${svg}</svg>${dataTable(labels, series, f)}</div>`;
}

function stackedColumns(buckets, series, { height = 190, f = money, prefix = "$", title }) {
  const W = 720, H = height, L = 46, B = 22, T = 6, plotW = W - L, plotH = H - B - T;
  const totals = buckets.map((b) => b.vals.reduce((a, c) => a + c, 0));
  const max = niceMax(Math.max(1, ...totals));
  const step = plotW / buckets.length, bw = Math.max(4, Math.min(34, step * 0.62));
  const y = (v) => T + plotH - (v / max) * plotH;
  let svg = "";
  for (let i = 0; i <= 4; i++) {
    const v = (max / 4) * i;
    svg += `<line class="${i ? "gridline" : "baseline"}" x1="${L}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text class="tick" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${prefix}${compact(v)}</text>`;
  }
  const every = Math.ceil(buckets.length / 7);
  buckets.forEach((b, i) => {
    const x = L + i * step + (step - bw) / 2;
    let acc = 0;
    const segs = series.map((s, k) => ({ s, v: b.vals[k] })).filter((g) => g.v > 0);
    segs.forEach((g, j) => {
      const y1 = y(acc + g.v), h = Math.max(0, y(acc) - y1 - (j ? 2 : 0));
      svg += j === segs.length - 1 ? `<path d="${topRounded(x, y1, bw, h, 4)}" fill="${g.s.color}"/>` : `<rect x="${x}" y="${y1}" width="${bw}" height="${h}" fill="${g.s.color}"/>`;
      acc += g.v;
    });
    if (i % every === 0) svg += `<text class="tick" x="${L + i * step + step / 2}" y="${H - 5}" text-anchor="middle">${esc(b.label)}</text>`;
    const tip = `<div class="tt-title">${esc(b.tipTitle)} · ${f(totals[i])}</div>` + series.map((s, k) => tipRow(s.color, s.label, f(b.vals[k]))).join("");
    svg += `<rect class="hit" x="${L + i * step}" y="${T}" width="${step}" height="${plotH}" ${tipAttr(tip)}/>`;
  });
  const table = `<button class="table-toggle" data-act="toggleTable">Show table</button><table class="data-table" hidden><thead><tr><th>Period</th>${series.map((s) => `<th>${esc(s.label)}</th>`).join("")}<th>Total</th></tr></thead><tbody>${
    buckets.map((b, i) => `<tr><td>${esc(b.tipTitle)}</td>${b.vals.map((v) => `<td>${esc(f(v))}</td>`).join("")}<td>${esc(f(totals[i]))}</td></tr>`).reverse().join("")}</tbody></table>`;
  return `<div class="chart">${legendOf(series)}<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)}">${svg}</svg>${table}</div>`;
}

function hbars(items, { color = "var(--s1)", f = fmt, total = null } = {}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return `<ul class="hbars">${items.map((it) => {
    const tip = `<div class="tt-title">${esc(it.label)}</div>${tipRow(it.color || color, it.tipLabel || "Total", f(it.value))}${total ? `<div class="small muted">${pctOf(it.value, total)} of total</div>` : ""}`;
    return `<li ${tipAttr(tip)}><span class="hb-label">${esc(it.label)}</span><span class="hb-track"><i style="width:${Math.max(2, (it.value / max) * 100)}%;background:${it.color || color}"></i></span><b>${esc(it.text ?? f(it.value))}</b></li>`;
  }).join("")}</ul>`;
}

function heatmap(matrix, counts) {
  const avg = matrix.map((row, d) => row.map((v) => (counts[d] ? v / counts[d] : 0)));
  const max = Math.max(1, ...avg.flat());
  let cells = `<span></span>${Array.from({ length: 24 }, (_, h) => `<span class="hh">${h % 3 === 0 ? (h === 0 ? "12a" : h < 12 ? h + "a" : h === 12 ? "12p" : h - 12 + "p") : ""}</span>`).join("")}`;
  for (const d of DOW_ORDER) {
    cells += `<span class="hl">${DOW_NAME[d]}</span>`;
    for (let h = 0; h < 24; h++) {
      const v = avg[d][h], pct = Math.round(6 + 94 * (v / max));
      const hr = `${String(h).padStart(2, "0")}:00`;
      cells += `<span class="hc" style="background:color-mix(in srgb, var(--s1) ${pct}%, var(--surface-2))" ${tipAttr(`<div class="tt-title">${DOW_NAME[d]} ${hr}</div>${tipRow("var(--s1)", "Avg visitors / hour", fmt(Math.round(v)))}`)}></span>`;
    }
  }
  return `<div class="heat" role="img" aria-label="Average visitors by day of week and hour of day">${cells}</div>
    <div class="heat-key"><span>Fewer</span><i></i><span>More visitors</span></div>`;
}

function funnel(steps) {
  const top = steps[0].value || 1;
  return `<div class="funnel">${steps.map((s, i) => {
    const w = Math.max(3, (s.value / top) * 100);
    const note = i === 0 ? "Everyone who visited" : i === 1 ? `${pctOf(s.value, top)} of visitors` : `${pctOf(s.value, top)} of visitors · ${pctOf(s.value, steps[i - 1].value)} of ${steps[i - 1].label.toLowerCase()}`;
    const tip = `<div class="tt-title">${esc(s.label)}</div>${tipRow(s.color, "People", fmt(s.value))}<div class="small muted">${esc(note)}</div>`;
    return `<div class="fn-step" ${tipAttr(tip)}><div class="fn-head"><span>${esc(s.label)}</span><b>${fmt(s.value)}</b></div>
      <div class="fn-track"><i style="width:${w}%;background:${s.color}"></i></div><div class="fn-note">${esc(note)}</div></div>`;
  }).join("")}</div>`;
}

// ------------------------------------------------------------------ view

const delta = (cur, prev, { invert = false } = {}) => {
  if (cur == null || !prev) return "";
  const p = ((cur - prev) / Math.abs(prev)) * 100, up = p >= 0, good = invert ? !up : up;
  return `<span class="yt-delta ${good ? "good" : "bad"}">${icon(up ? "arrowUp" : "arrowDown", 12)}${Math.abs(Math.round(p))}%</span>`;
};

// Keep only dates where some series reported a value; a series' own gaps on those dates become 0.
function dense(labels, series) {
  const idx = labels.map((_, i) => i).filter((i) => series.some((s) => s.values[i] != null));
  return { labels: idx.map((i) => labels[i]), series: series.map((s) => ({ ...s, values: idx.map((i) => s.values[i] ?? 0) })) };
}

export function ytView() {
  const apps = state.data?.yt?.apps || [];
  const appId = apps.some((a) => a.id === state.ui.ytApp) ? state.ui.ytApp : "all";
  const R = RANGES.includes(+state.ui.ytRange) ? +state.ui.ytRange : 30;
  const sel = appId === "all" ? apps : apps.filter((a) => a.id === appId);
  const cur = lastDays(R), prev = lastDays(R, R);
  const A = (keys, dates = cur, who = sel) => agg(who, keys, dates);
  const color = (a) => a.color || "var(--s1)";

  const visitors = [A(["visitors"]).total, A(["visitors"], prev).total];
  const revenue = [A(REV).total, A(REV, prev).total];
  const spend = [A(SP).total, A(SP, prev).total];
  const profit = revenue[0] != null && spend[0] != null ? [revenue[0] - spend[0], revenue[1] != null && spend[1] != null ? revenue[1] - spend[1] : null] : [null, null];
  const avgSecs = (dates) => { const s = A(["secs"], dates).total, n = A(["sessions"], dates).total; return s != null && n ? s / n : null; };
  const secs = [avgSecs(cur), avgSecs(prev)];
  const starTotals = [0, 1, 2, 3, 4].map((k) => sel.reduce((t, a) => t + (a.ratings?.[k] || 0), 0));
  const nReviews = starTotals.reduce((a, b) => a + b, 0);
  const avgRating = nReviews ? starTotals.reduce((t, c, k) => t + c * (5 - k), 0) / nReviews : null;

  const kpi = (ic, label, value, d, sc, sub) => `<div class="yt-kpi${value == null ? " is-na" : ""}" style="--sc:${sc}"><span class="st-ico">${icon(ic, 18)}</span>
    <span class="st-val">${value ?? "N/A"}</span><span class="st-label">${label}</span>
    <span class="yt-sub">${value == null ? `<em>No data yet</em>` : `${d}<em>${sub ?? (d ? `vs prior ${R} days` : "")}</em>`}</span></div>`;
  const kpis = `<div class="yt-kpis">
    ${kpi("activity", "Visitors", visitors[0] == null ? null : fmt(visitors[0]), delta(...visitors), "var(--s1)")}
    ${kpi("trophy", "Revenue", revenue[0] == null ? null : money(revenue[0]), delta(...revenue), "var(--s3)")}
    ${kpi("store", "Money spent", spend[0] == null ? null : money(spend[0]), delta(...spend, { invert: true }), "var(--s8)")}
    ${kpi("zap", "Profit", profit[0] == null ? null : money(profit[0]), delta(...profit), profit[0] >= 0 ? "var(--s6)" : "var(--s8)")}
    ${kpi("gauge", "Time on site", secs[0] == null ? null : dur(secs[0]), delta(...secs), "var(--s7)")}
    ${kpi("sparkles", "Rating", avgRating == null ? null : avgRating.toFixed(1) + " / 5", "", "var(--s4)", `${fmt(nReviews)} reviews, all time`)}
  </div>`;

  // Daily visitors: one line per app.
  const vLines = sel.map((a) => ({ label: a.name, color: color(a), values: A(["visitors"], cur, [a]).values })).filter((s) => s.values.some((v) => v != null));
  const visitorsPanel = vLines.length
    ? (() => { const d = dense(cur, vLines); return panel("Daily visitors", multiLine(d.labels, d.series, { title: "Daily visitors", f: fmt }), { iconName: "activity" }); })()
    : naPanel("Daily visitors", "activity");

  // Revenue by stream, weekly buckets for the 90-day range.
  const streams = STREAMS.filter((s) => A([s.key]).total != null);
  const size = R > 30 ? 7 : 1, buckets = [];
  for (let end = cur.length; end > 0; end -= size) {
    const days = cur.slice(Math.max(0, end - size), end);
    const vals = streams.map((s) => A([s.key], days).total);
    if (vals.every((v) => v == null)) continue;
    buckets.unshift({ vals: vals.map((v) => v || 0), label: dateLabel(days[0]), tipTitle: size === 1 ? dateLabel(days[0], true) : `${dateLabel(days[0])} – ${dateLabel(days[days.length - 1])}` });
  }
  const revenuePanel = buckets.length ? panel("Revenue", stackedColumns(buckets, streams, { title: "Revenue by stream" }), { iconName: "trophy" }) : naPanel("Revenue", "trophy");

  // Visitors per hour.
  const hourly = sel.filter((a) => a.hourly);
  const matrix = Array.from({ length: 7 }, (_, d) => Array.from({ length: 24 }, (_, h) => hourly.reduce((t, a) => t + (a.hourly[d]?.[h] || 0), 0)));
  const hourPanel = hourly.length ? panel("Visitors per hour", heatmap(matrix, new Array(7).fill(1)), { iconName: "clock" }) : naPanel("Visitors per hour", "clock");

  // Money in vs out on one axis, with the spend breakdown underneath.
  const moneyLines = [
    revenue[0] != null && { label: "Revenue", color: "var(--s3)", values: A(REV).values },
    spend[0] != null && { label: "Money spent", color: "var(--s8)", values: A(SP).values },
  ].filter(Boolean);
  const spendItems = SPEND.map((s) => ({ label: s.label, value: A([s.key]).total })).filter((s) => s.value != null).sort((a, b) => b.value - a.value);
  const moneyPanel = moneyLines.length
    ? (() => {
      const d = dense(cur, moneyLines);
      return panel("Money spent vs revenue", multiLine(d.labels, d.series, { title: "Revenue and spend per day", f: money, prefix: "$" })
        + (spendItems.length ? `<h3 class="yt-sub-h">Where the money went</h3>` + hbars(spendItems, { color: "var(--s8)", f: money, total: spend[0] }) : ""), { iconName: "store" });
    })()
    : naPanel("Money spent vs revenue", "store");

  // Time on site: average session length per day (minutes), per app.
  const tLines = sel.map((a) => {
    const s = A(["secs"], cur, [a]).values, n = A(["sessions"], cur, [a]).values;
    return { label: a.name, color: color(a), values: s.map((v, i) => (v != null && n[i] ? v / n[i] / 60 : null)) };
  }).filter((s) => s.values.some((v) => v != null));
  const sessions = A(["sessions"]).total, pageviews = A(["pageviews"]).total;
  const timePanel = tLines.length
    ? (() => {
      const d = dense(cur, tLines);
      return panel("Time on site", multiLine(d.labels, d.series, { title: "Average session length in minutes", f: (v) => v.toFixed(1) + " min" })
        + `<div class="metric-grid"><div class="metric"><span>Avg session</span><b>${orNA(secs[0], dur)}</b></div>
           <div class="metric"><span>Pages per visit</span><b>${pageviews != null && sessions ? (pageviews / sessions).toFixed(1) : NA}</b></div>
           <div class="metric"><span>Sessions</span><b>${orNA(sessions, fmt)}</b></div></div>`, { iconName: "gauge" });
    })()
    : naPanel("Time on site", "gauge");

  const steps = [
    { label: "Visitors", value: visitors[0], color: "var(--s1)" },
    { label: "Sign-ups", value: A(["signups"]).total, color: "var(--s7)" },
    { label: "Paid", value: A(["paid"]).total, color: "var(--s3)" },
  ].filter((s) => s.value != null);
  const funnelPanel = steps.length > 1 && steps[0].label === "Visitors" ? panel("Conversion funnel", funnel(steps), { iconName: "layers" }) : naPanel("Conversion funnel", "layers");

  const reviews = sel.flatMap((a) => (a.reviews || []).map((r) => ({ ...r, app: a }))).sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 4);
  const reviewsPanel = nReviews ? panel("Reviews & ratings", `<div class="yt-rating"><b>${avgRating.toFixed(1)}</b><div>${stars(Math.round(avgRating))}<div class="muted small">${fmt(nReviews)} reviews · all time</div></div></div>
    ${hbars(starTotals.map((v, k) => ({ label: `${5 - k} star${k === 4 ? "" : "s"}`, value: v, tipLabel: "Reviews" })), { color: "var(--s4)", total: nReviews })}
    ${reviews.length ? `<ul class="yt-reviews">${reviews.map((r) => `<li><div class="rv-head">${stars(r.stars)}<span class="chip">${dot(color(r.app))}${esc(r.app.name)}</span>${r.date ? `<span class="muted small">${esc(ago(r.date))}</span>` : ""}</div><p>${esc(r.text || "")}</p></li>`).join("")}</ul>` : ""}`, { iconName: "sparkles" })
    : naPanel("Reviews & ratings", "sparkles");

  const devices = ["Mobile", "Desktop", "Tablet"].map((name) => ({ label: name, value: sel.reduce((t, a) => t + (a.devices?.[name] || 0), 0), color: DEVICE_COLORS[name] })).filter((d) => d.value);
  const devTotal = devices.reduce((t, d) => t + d.value, 0);
  const top = [...devices].sort((a, b) => b.value - a.value)[0];
  const countries = mergePairs(sel, "countries").slice(0, 6).map((c) => ({ ...c, tipLabel: "Visitors" }));
  const subNA = (h) => `<h3 class="yt-sub-h">${h}</h3><div class="na inline"><b>N/A</b></div>`;
  const audiencePanel = devices.length || countries.length
    ? panel("Devices & countries", (devices.length
      ? `<div class="yt-split">${donut(devices, { size: 150, stroke: 20, center: pctOf(top.value, devTotal), centerSub: `on ${top.label.toLowerCase()}` })}
        <ul class="legend vertical">${devices.map((d) => `<li><span class="sw" style="background:${d.color}"></span>${d.label}<b>${pctOf(d.value, devTotal)}</b></li>`).join("")}</ul></div>`
      : subNA("Devices")) + (countries.length ? `<h3 class="yt-sub-h">Top countries</h3>${hbars(countries, { total: visitors[0] })}` : subNA("Top countries")), { iconName: "website" })
    : naPanel("Devices & countries", "website");

  const pages = mergePairs(sel, "pages").slice(0, 6).map((p) => ({ ...p, tipLabel: "Views" }));
  const sources = mergePairs(sel, "sources").map((s) => ({ ...s, tipLabel: "Visitors" }));
  const srcTotal = sources.reduce((t, s) => t + s.value, 0);
  const pagesPanel = pages.length ? panel("Top pages", hbars(pages), { iconName: "note" }) : naPanel("Top pages", "note");
  const sourcesPanel = sources.length ? panel("Where visitors come from", hbars(sources, { total: srcTotal }), { iconName: "link" }) : naPanel("Where visitors come from", "link");

  const appBtn = (id, label, c) => `<button class="${appId === id ? "on" : ""}" data-act="setUi" data-k="ytApp" data-v="${esc(id)}">${c ? dot(c) : ""}${esc(label)}</button>`;
  return `<div class="page-head"><div><div class="eyebrow">${icon("rocket", 14)}Phase 4</div><h1>YT Dashboard</h1>
      <p>Traffic, money and reviews for your sites and apps, last ${R} days${apps.length ? (appId === "all" && apps.length > 1 ? ` across ${apps.length} apps` : ` for ${esc(sel[0].name)}`) : ""}.</p></div>
    <div class="yt-filters">
      ${apps.length > 1 ? `<div class="seg" role="group" aria-label="App">${appBtn("all", "All apps")}${apps.map((a) => appBtn(a.id, a.name, color(a))).join("")}</div>` : ""}
      <div class="seg" role="group" aria-label="Date range">${RANGES.map((r) => `<button class="${r === R ? "on" : ""}" data-act="setUi" data-k="ytRange" data-v="${r}">${r} days</button>`).join("")}</div>
    </div></div>
  ${sel.length ? "" : `<div class="card yt-banner">${icon("alert", 16)}<div><b>Nothing is connected yet.</b> None of these apps have launched, so there is no traffic to measure and every number shows N/A. Real figures will appear once an app is live and its data is connected.</div></div>`}
  ${kpis}
  <div class="grid-2">${visitorsPanel}${revenuePanel}</div>
  <div class="grid-2 yt-grid">${hourPanel}${moneyPanel}</div>
  <div class="grid-2 yt-grid">${timePanel}${funnelPanel}</div>
  <div class="grid-2 yt-grid">${reviewsPanel}${audiencePanel}</div>
  <div class="grid-2 yt-grid">${pagesPanel}${sourcesPanel}</div>`;
}
