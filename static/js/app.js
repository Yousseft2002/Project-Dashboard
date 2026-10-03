// App shell: routing, data loading, background-job polling and all user actions.
import { api, toast, store, esc, ago } from "./util.js";
import { icon } from "./icons.js";
import { initTooltips } from "./charts.js";
import { state, saveUi, project } from "./state.js";
import { dashboardView } from "./views/dashboard.js";
import { projectView, editDialog } from "./views/project.js";
import { physicalView, physicalDetail, physicalDialog } from "./views/physical.js";
import { ytView } from "./views/yt.js";
import { historyView } from "./views/planner.js";
import { settingsActions, machineLabel } from "./views/settings.js";

const $app = document.getElementById("app");

// ------------------------------------------------------------------ routing

const ROUTES = [
  [/^#\/project\/(.+)$/, (m) => projectView(decodeURIComponent(m[1])), "dashboard"],
  [/^#\/digital\/(.+)$/, (m) => { location.replace("#/project/" + m[1]); return ""; }, "dashboard"],
  [/^#\/physical\/(\d+)$/, (m) => physicalDetail(+m[1]), "physical"],
  [/^#\/physical$/, () => physicalView(), "physical"],
  [/^#\/yt$/, () => ytView(), "yt"],
  [/^#\/history$/, () => historyView(), "dashboard"],
  [/.*/, () => dashboardView(), "dashboard"],
];

let lastRoute = null, pendingRender = false;

function render() {
  if (!state.data) return;
  const hash = location.hash || "#/";
  const routeChanged = hash !== lastRoute;
  state.animate = routeChanged;
  const [re, view, tab] = ROUTES.find(([r]) => r.test(hash));
  const m = hash.match(re);
  document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
  const y = window.scrollY;
  $app.innerHTML = view(m);
  $app.classList.toggle("animate-in", routeChanged && !matchMedia("(prefers-reduced-motion: reduce)").matches);
  if (routeChanged) { clearTimeout(render._t); render._t = setTimeout(() => $app.classList.remove("animate-in"), 1400); }
  updateJobs();
  window.scrollTo({ top: routeChanged ? 0 : y });
  lastRoute = hash;
  pendingRender = false;
  if (routeChanged && hash === "#/history") loadHistory();
}

async function loadHistory() {
  state.history = (await api("GET", "/api/planner/history")).days;
  if (location.hash === "#/history") render();
}
window.addEventListener("hashchange", render);

const typing = () => {
  const a = document.activeElement;
  return a && $app.contains(a) && (a.tagName === "TEXTAREA" || (a.tagName === "INPUT" && !["checkbox", "radio", "range", "file"].includes(a.type)));
};
// A quiet reload (from a finished background job) never wipes something being typed.
document.addEventListener("focusout", () => setTimeout(() => { if (pendingRender && !typing()) render(); }, 50));

async function load({ quiet = false } = {}) {
  state.data = await api("GET", "/api/state");
  document.body.classList.toggle("remote", !!state.data.access?.remote);
  updateScanStatus(state.data.scan);
  if (quiet && typing()) { pendingRender = true; return; }
  render();
  if (jobsActive() && !jobTimer) jobTimer = setTimeout(pollJobs, 1500);
}

// ------------------------------------------------------------------ scan

const scanBtn = document.getElementById("scanBtn");
scanBtn.addEventListener("click", async () => { await api("POST", "/api/scan"); pollScan(); });

function updateScanStatus(s) {
  const el = document.getElementById("scanStatus");
  const machines = state.data?.digital?.machines || [];
  scanBtn.disabled = !!s.running;
  scanBtn.innerHTML = `${icon("refresh", 15, s.running ? "spin" : "")}<span>${s.running ? "Scanning…" : "Rescan"}</span>`;
  el.textContent = s.running ? s.message || "Scanning…" : s.error ? "Scan failed: " + s.error
    : machines.length ? "Scanned · " + machines.map((m) => `${machineLabel(m.machine)} ${ago(m.scanned_at)}`).join(" · ") : "";
}

async function pollScan() {
  const s = await api("GET", "/api/scan");
  updateScanStatus(s);
  if (s.running) setTimeout(pollScan, 700);
  else { await load(); toast(s.error ? "Scan failed" : s.message); }
}

// ------------------------------------------------------------------ background jobs (AI analysis + previews)

let jobTimer = null;
function jobsActive() {
  const a = state.data?.analysis;
  return !!(a && (a.current || a.queue.length || a.planner?.status === "running" || Object.values(a.previews || {}).some((j) => j.status !== "error")));
}
async function pollJobs() {
  jobTimer = null;
  const before = state.data.analysis;
  const a = await api("GET", "/api/analysis").catch(() => before);
  state.data.analysis = a;
  const changed = (x, y) => Object.keys(x || {}).some((k) => !y?.[k] || y[k].status !== x[k].status);
  const planDone = before.planner?.status === "running" && a.planner?.status !== "running";
  if (changed(before.jobs, a.jobs) || changed(before.previews, a.previews) || planDone) await load({ quiet: true });
  else updateJobs();
  if (jobsActive()) jobTimer = setTimeout(pollJobs, 1500);
}
function startPolling() { if (!jobTimer) jobTimer = setTimeout(pollJobs, 800); }

const elapsed = (iso) => {
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
};
function jobHtml(id) {
  const j = state.data.analysis?.jobs?.[id];
  if (!j) return "";
  if (j.status === "queued") return `<span class="job">${icon("clock", 13)}Queued for analysis</span>`;
  if (j.status === "running") return `<span class="job running"><span class="spinner"></span>${esc(j.message || "Analyzing")} · ${elapsed(j.started_at)}</span>`;
  if (j.status === "error") return `<span class="job error">${icon("alert", 13)}Analysis failed: ${esc(j.error || "")}</span>`;
  return "";
}
function updateJobs() {
  document.querySelectorAll("[data-job]").forEach((el) => (el.innerHTML = jobHtml(el.dataset.job)));
  document.querySelectorAll("[data-plan-job]").forEach((el) => (el.textContent = state.data.analysis?.planner?.message || "Working"));
  const q = document.getElementById("queueStatus");
  if (q) {
    const a = state.data.analysis;
    const cur = a.current && project(a.current);
    const j = a.current && a.jobs[a.current];
    const shots = Object.values(a.previews || {}).filter((x) => x.status !== "error").length;
    q.innerHTML = [
      a.current ? `<span><span class="spinner"></span>Analyzing <b>${esc(cur?.name || "")}</b>${j?.message ? " · " + esc(j.message) : ""}${a.queue.length ? ` · ${a.queue.length} queued` : ""}</span>` : "",
      shots ? `<span><span class="spinner"></span>Capturing ${shots} preview(s)</span>` : "",
    ].filter(Boolean).join("");
  }
  document.querySelectorAll("[data-when-active]").forEach((el) => (el.hidden = !(state.data.analysis.current || state.data.analysis.queue.length)));
}
async function queueAnalysis(body) {
  const r = await api("POST", "/api/analyze", body);
  state.data.analysis = { ...state.data.analysis, jobs: r.jobs, queue: r.queue, current: r.current };
  toast(r.queued ? `Queued ${r.queued} project(s) for AI analysis` : "Already up to date");
  updateJobs();
  startPolling();
}

// ------------------------------------------------------------------ actions

const meta = (key, body) => api("POST", "/api/project/meta", { key, ...body });

async function planCall(method, url, body) {
  const r = await api(method, url, body);
  if (r.planner) state.data.planner = r.planner;
  if (r.projects) state.data.projects = r.projects;
  render();
  return r;
}

async function startPlannerJob(url, body) {
  const r = await api("POST", url, body);
  state.data.analysis = { ...state.data.analysis, planner: r.job };
  if (!r.started) toast("The planner is already working on something");
  render();
  startPolling();
}

const ACTIONS = {
  ...settingsActions,
  // dashboard filters
  setUi(el) { state.ui[el.dataset.k] = el.dataset.v; saveUi(); render(); },
  setUiSelect(el) { state.ui[el.dataset.k] = el.value; saveUi(); render(); },
  quickFilter(el) {
    Object.assign(state.ui, { status: el.dataset.v, type: "all", q: "" });
    saveUi(); render();
    document.getElementById("projects")?.scrollIntoView({ behavior: "smooth" });
  },
  jump(el) { document.getElementById(el.dataset.target)?.scrollIntoView({ behavior: "smooth" }); },
  toggleTable(el) {
    const t = el.nextElementSibling;
    t.hidden = !t.hidden;
    el.textContent = t.hidden ? "Show table" : "Hide table";
  },

  // daily planner
  async planTask(el) {
    const act = el.dataset.do;
    await planCall("POST", "/api/planner/tasks/" + el.dataset.tid + "/" + act);
    const msg = { complete: "Marked complete", move: "Moved to tomorrow's plan", accept: "Accepted. The planner will favour it.", delete: "Removed" }[act];
    if (msg) toast(msg);
  },
  async planPriority(el) { await planCall("POST", "/api/planner/tasks/" + el.dataset.tid + "/priority", { priority: el.value }); toast("Priority set to " + el.value); },
  planSkipOpen(el) {
    state.planUi.skipFor = +el.dataset.tid; render();
    document.querySelector(".pt-skip input")?.focus();
  },
  planSkipCancel() { state.planUi.skipFor = null; render(); },
  async planSkipConfirm(form) {
    state.planUi.skipFor = null;
    await planCall("POST", "/api/planner/tasks/" + form.dataset.tid + "/skip", { reason: form.reason.value });
    toast("Skipped. The planner won't push it today.");
  },
  planDetails(el) { const o = state.planUi.open; o[el.dataset.tid] = !o[el.dataset.tid]; render(); },
  planAddToggle() { state.planUi.addOpen = !state.planUi.addOpen; render(); document.querySelector(".pt-add input")?.focus(); },
  async planAdd(form) {
    const d = Object.fromEntries(new FormData(form));
    await planCall("POST", "/api/planner/tasks", { ...d, est_minutes: +d.est_minutes || 60 });
    state.planUi.addOpen = false; render(); toast("Added to today");
  },
  async planPick(el) { await planCall("POST", "/api/planner/pick", { cid: el.dataset.cid }); toast("Added to today's list"); },
  planExample(el) {
    state.planUi.draft = el.dataset.text; render();
    const t = document.getElementById("planText"); t?.focus(); t?.setSelectionRange(t.value.length, t.value.length);
  },
  planDismissReply() { state.planUi.dismissed = state.data.analysis.planner.reply; render(); },
  async planEndDirective(el) { await planCall("DELETE", "/api/planner/directives/" + el.dataset.id); toast("Instruction ended. Regenerate to re-plan."); },
  async planInstruction(form) {
    const text = form.text.value.trim();
    if (!text) { toast("Write what changed first"); return; }
    await startPlannerJob("/api/planner/instruction", { text });
    state.planUi.draft = "";
    render();
  },
  async planRegenerate() { await startPlannerJob("/api/planner/regenerate", {}); },

  // AI
  analyzeOne(el) { queueAnalysis({ keys: [el.dataset.key] }); },
  analyzeChanged() { queueAnalysis({ mode: "changed" }); },
  async stopAnalysis() { state.data.analysis = await api("POST", "/api/analyze/stop"); await load({ quiet: true }); toast("Analysis stopped"); },
  async setModel(el) { await api("POST", "/api/settings", { model: el.value }); state.data.settings.model = el.value; toast("AI model: " + el.options[el.selectedIndex].text); },

  // previews
  async generatePreviews() {
    const r = await api("POST", "/api/previews", {});
    toast(r.queued ? `Capturing ${r.queued} preview(s)` : "No projects with a web page or URL to capture. Add a live URL in Edit details.");
    await load({ quiet: true }); startPolling();
  },
  async refreshPreview(el) { await api("POST", "/api/previews", { keys: [el.dataset.key] }); toast("Capturing preview…"); await load({ quiet: true }); startPolling(); },
  async uploadPreview(el) {
    const file = el.files[0];
    if (!file) return;
    const dataUrl = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); });
    await api("POST", "/api/project/preview-upload", { key: el.dataset.key, dataUrl });
    await load(); toast("Preview image updated");
  },
  async clearUpload(el) { await meta(el.dataset.key, { preview_image: null }); await load(); toast("Upload removed"); },

  // project meta
  async editProject(el) {
    const p = project(el.dataset.key);
    const data = await editDialog(p);
    if (!data) return;
    if (data.name === p.name) delete data.name;
    await meta(p.id, data);
    await load(); toast("Saved");
    startPolling();
  },
  async saveNotes(el) { await meta(el.dataset.key, { note: el.value }); toast("Notes saved"); },
  async hide(el) { await meta(el.dataset.key, { hidden: 1 }); location.hash = "#/"; await load(); toast("Hidden. Restore it at the bottom of the project list."); },
  async unhide(el) { await meta(el.dataset.key, { hidden: 0 }); await load(); toast("Restored"); },
  async merge(el) {
    if (!el.value) return;
    await meta(el.dataset.key, { merge_into: el.value });
    location.hash = "#/project/" + encodeURIComponent(el.value); await load(); toast("Merged");
  },
  async unmerge(el) { await meta(el.dataset.key, { merge_into: null }); await load(); toast("Split out"); },
  async openCode(el) { await api("POST", "/api/project/open", { key: el.dataset.key, app: "code" }).catch((e) => toast(e.message)); },
  async openFolder(el) { await api("POST", "/api/project/open", { key: el.dataset.key, app: "folder" }).catch((e) => toast(e.message)); },

  // items: tasks, milestones, blockers, bugs, goals
  async addItem(form) {
    const data = Object.fromEntries(new FormData(form));
    await api("POST", "/api/items", { key: form.dataset.key, kind: form.dataset.kind, ...data });
    await load();
    document.querySelector(`form[data-kind="${form.dataset.kind}"] input[name=title]`)?.focus();
  },
  async cycleTask(el) {
    const next = { todo: "doing", doing: "done", done: "todo" }[el.dataset.status];
    await api("PATCH", "/api/items/" + el.dataset.id, { status: next });
    await load();
  },
  async toggleMilestone(el) { await api("PATCH", "/api/items/" + el.dataset.id, { status: el.dataset.done === "true" ? "todo" : "done" }); await load(); },
  async toggleIssue(el) { await api("PATCH", "/api/items/" + el.dataset.id, { status: el.dataset.status === "resolved" ? "open" : "resolved" }); await load(); },
  async deleteItem(el) { await api("DELETE", "/api/items/" + el.dataset.id); await load(); },

  // physical
  async newPhysical() {
    const data = await physicalDialog(null);
    if (!data) return;
    const { id } = await api("POST", "/api/physical", data);
    location.hash = "#/physical/" + id; await load();
  },
  async editPhysical(el) {
    const p = state.data.physical.find((x) => x.id === +el.dataset.id);
    const data = await physicalDialog(p);
    if (!data) return;
    await api("PATCH", "/api/physical/" + p.id, data); await load(); toast("Saved");
  },
  async deletePhysical(el) {
    const p = state.data.physical.find((x) => x.id === +el.dataset.id);
    if (!confirm(`Delete "${p.name}" and all its updates? This can't be undone.`)) return;
    await api("DELETE", "/api/physical/" + p.id); location.hash = "#/physical"; await load(); toast("Deleted");
  },
  async addUpdate(form) { await api("POST", `/api/physical/${form.dataset.id}/updates`, Object.fromEntries(new FormData(form))); await load(); toast("Update logged"); },
  async deleteUpdate(el) { if (confirm("Delete this log entry?")) { await api("DELETE", "/api/updates/" + el.dataset.id); await load(); } },
  async addPhysMilestone(form) { await api("POST", `/api/physical/${form.dataset.id}/milestones`, { title: form.title.value }); await load(); },
  async togglePhysMilestone(el) { await api("PATCH", "/api/milestones/" + el.dataset.id, { done: el.dataset.done !== "1" }); await load(); },
  async deletePhysMilestone(el) { await api("DELETE", "/api/milestones/" + el.dataset.id); await load(); },
};

// One delegated listener per event type; elements opt in with data-act.
function run(name, el, e) {
  const fn = ACTIONS[name];
  if (!fn) return;
  Promise.resolve(fn(el, e)).catch((err) => toast(err.message || "Something went wrong"));
}
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-act]");
  if (!el || el.tagName === "FORM" || el.tagName === "SELECT" || el.tagName === "TEXTAREA" || el.tagName === "INPUT") return;
  e.preventDefault();
  run(el.dataset.act, el, e);
});
document.addEventListener("change", (e) => {
  const el = e.target;
  if (el.matches("select[data-act], input[type=file][data-act]")) run(el.dataset.act, el, e);
});
document.addEventListener("focusout", (e) => {
  const el = e.target;
  if (el.matches("textarea[data-act]") && el.value !== el.defaultValue) { el.defaultValue = el.value; run(el.dataset.act, el, e); }
});
document.addEventListener("submit", (e) => {
  const form = e.target.closest("form[data-act]");
  if (!form) return;
  e.preventDefault();
  run(form.dataset.act, form, e);
});
document.addEventListener("input", (e) => {
  const el = e.target;
  if (el.matches(".search")) {
    clearTimeout(ACTIONS._s);
    ACTIONS._s = setTimeout(() => {
      state.ui.q = el.value;
      const pos = el.selectionStart;
      render();
      const s = $app.querySelector(".search");
      if (s) { s.focus(); s.setSelectionRange(pos, pos); }
    }, 180);
  } else if (el.matches("[data-draft]")) {
    state.planUi.draft = el.value;
  } else if (el.matches("[data-live-output]")) {
    el.parentElement.querySelector("output").textContent = el.value + "%";
  }
});

// ------------------------------------------------------------------ theme & boot

(function initTheme() {
  const saved = store.get("pt-theme");
  if (saved) document.documentElement.dataset.theme = saved;
  document.getElementById("themeBtn").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    store.set("pt-theme", next);
  });
})();

initTooltips();
load()
  .then(() => { if (state.data.scan.running) pollScan(); if (jobsActive()) startPolling(); })
  .catch((e) => { $app.innerHTML = `<div class="empty-state">Couldn't reach the Project Tracker server: ${esc(e.message)}</div>`; });
