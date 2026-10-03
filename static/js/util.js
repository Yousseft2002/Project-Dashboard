// Small shared helpers: escaping, formatting, API calls, storage.

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const fmt = (n) => (n == null ? "–" : Number(n).toLocaleString());
export const money = (n) => (n == null ? "–" : "$" + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 }));
export const pct = (n) => `${Math.round(n || 0)}%`;
export const enc = encodeURIComponent;

export function ago(iso) {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  const d = Math.floor(s / 86400);
  if (d < 30) return d + "d ago";
  return dateLabel(iso);
}

export function dateLabel(isoOrDay, withYear = false) {
  if (!isoOrDay) return "–";
  const d = isoOrDay.length === 10 ? new Date(isoOrDay + "T12:00:00") : new Date(isoOrDay);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", ...(withYear ? { year: "numeric" } : {}) });
}

export function daysUntil(day) {
  if (!day) return null;
  const t = new Date(day + "T12:00:00").getTime();
  return Math.round((t - Date.now()) / 86400000);
}

export function hashSlot(key, slots = 8) {
  let h = 0;
  for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return (h % slots) + 1;
}

export function initials(name) {
  const words = String(name).replace(/[^A-Za-z0-9 ]+/g, " ").trim().split(/\s+/);
  return ((words[0]?.[0] || "?") + (words[1]?.[0] || words[0]?.[1] || "")).toUpperCase();
}

export function domain(url) {
  try { return new URL(url).host; } catch { return url || ""; }
}

export async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.error || res.statusText);
  return json;
}

export function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 2800);
}

// localStorage can be unavailable (private window, blocked site data); every access is guarded.
export const store = {
  get(k, fallback = null) {
    try { const v = localStorage.getItem(k); return v == null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* not persisted */ } },
};
