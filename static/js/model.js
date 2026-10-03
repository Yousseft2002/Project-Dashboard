// Domain constants and pure derivations over the canonical project model (see tracker/projects.py).
// Nothing here knows about specific projects; every number on the dashboard is computed from the list.

export const PHASES = ["Idea", "Planning", "Design", "Development", "Testing", "Deployment", "Maintenance"];
// Ordinal blue ramp, light -> dark, one step per lifecycle stage (lightest still clears 2:1 on both surfaces).
export const PHASE_COLOR = ["#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#1c5cab", "#184f95"];
export const STATUSES = ["Active", "Blocked", "Paused", "Completed"];
export const STATUS_META = {
  Active: { icon: "play", color: "var(--info)", cls: "active" },
  Blocked: { icon: "lock", color: "var(--critical)", cls: "blocked" },
  Paused: { icon: "pause", color: "var(--muted)", cls: "paused" },
  Completed: { icon: "checkCircle", color: "var(--good)", cls: "completed" },
};
export const PRIORITIES = ["High", "Medium", "Low"];
export const PRIORITY_META = {
  High: { icon: "arrowUp", cls: "high", rank: 0 },
  Medium: { icon: "minus", cls: "medium", rank: 1 },
  Low: { icon: "arrowDown", cls: "low", rank: 2 },
};
// Each project type keeps one categorical slot everywhere (color follows the entity).
export const TYPE_META = {
  App: { icon: "app", slot: 1 },
  Website: { icon: "website", slot: 3 },
  SaaS: { icon: "saas", slot: 7 },
  "Internal Tool": { icon: "tool", slot: 4 },
  "E-commerce": { icon: "store", slot: 2 },
  Automation: { icon: "automation", slot: 5 },
  Game: { icon: "game", slot: 8 },
  Library: { icon: "library", slot: 6 },
  Other: { icon: "other", slot: 0 },
};
export const typeMeta = (t) => TYPE_META[t] || TYPE_META.Other;
export const typeColor = (t) => (typeMeta(t).slot ? `var(--s${typeMeta(t).slot})` : "var(--muted)");
export const phaseIndex = (ph) => Math.max(0, PHASES.indexOf(ph));
export const CLOSE_TO_DONE = 75;
const TASK_RANK = { high: 0, medium: 1, low: 2 };

export const isOpenStatus = (p) => p.status === "Active" || p.status === "Blocked";
export const isCloseToDone = (p) => p.status !== "Completed" && p.progress >= CLOSE_TO_DONE;

export function portfolioStats(projects) {
  const live = projects.filter((p) => p.status !== "Paused");
  const sum = (f) => projects.reduce((a, p) => a + f(p), 0);
  const milestones = upcomingMilestones(projects);
  return {
    total: projects.length,
    active: projects.filter(isOpenStatus).length,
    overall: live.length ? Math.round(live.reduce((a, p) => a + p.progress, 0) / live.length) : 0,
    overallBase: live.length,
    completed: projects.filter((p) => p.status === "Completed").length,
    inDevelopment: projects.filter((p) => isOpenStatus(p) && ["Design", "Development", "Testing", "Deployment"].includes(p.phase)).length,
    blocked: projects.filter((p) => p.status === "Blocked").length,
    paused: projects.filter((p) => p.status === "Paused").length,
    closeToDone: projects.filter(isCloseToDone).length,
    openTasks: sum((p) => p.taskCounts.open),
    doneTasks: sum((p) => p.taskCounts.done),
    totalTasks: sum((p) => p.taskCounts.total),
    highTasks: sum((p) => p.taskCounts.highOpen),
    upcomingMilestones: milestones.length,
    analyzed: projects.filter((p) => p.ai).length,
    avgHealth: (() => {
      const h = projects.filter((p) => p.health != null);
      return h.length ? Math.round(h.reduce((a, p) => a + p.health, 0) / h.length) : null;
    })(),
    byStatus: STATUSES.map((s) => ({ key: s, count: projects.filter((p) => p.status === s).length })),
    byPhase: PHASES.map((ph) => ({ key: ph, items: projects.filter((p) => p.phase === ph) })),
    byType: Object.keys(TYPE_META).map((t) => ({ key: t, count: projects.filter((p) => p.type === t).length })).filter((x) => x.count),
  };
}

/** What to work on next: open tasks (in-progress first) weighted by project priority and nearness to done. */
export function nextUp(projects, n = 6) {
  const out = [];
  for (const p of projects.filter(isOpenStatus)) {
    const pw = 3 - PRIORITY_META[p.priority].rank;
    const open = p.tasks.filter((t) => t.status !== "done");
    for (const t of open) {
      const score = pw * 10 + (t.status === "doing" ? 6 : 0) + (2 - (TASK_RANK[t.priority] ?? 1)) * 2 + p.progress / 25;
      out.push({ project: p, title: t.title, detail: t.detail, priority: t.priority, doing: t.status === "doing", source: t.source, score });
    }
    if (!open.length && p.ai?.nextSteps?.length) {
      const s = p.ai.nextSteps[0];
      out.push({ project: p, title: s.title, detail: s.detail, priority: "medium", doing: false, source: "ai", score: pw * 10 + p.progress / 25 });
    }
  }
  out.sort((a, b) => b.score - a.score);
  // At most two suggestions per project so one busy project doesn't fill the list.
  const per = {};
  return out.filter((x) => (per[x.project.id] = (per[x.project.id] || 0) + 1) <= 2).slice(0, n);
}

export function attention(projects) {
  const items = [];
  for (const p of projects) {
    for (const b of p.blockers.filter((b) => b.status === "open"))
      items.push({ level: "critical", project: p, title: b.title, text: b.detail || "Blocker", tag: "Blocked" });
    for (const nd of p.ai?.needsFromMe || [])
      if (nd.priority === "high") items.push({ level: "serious", project: p, title: nd.title, text: nd.detail, tag: "Needs you" });
    for (const s of p.facts.signals)
      if (s.level === "serious" || s.level === "warning") items.push({ level: s.level, project: p, title: s.action, text: s.text, tag: "Repo" });
    for (const b of p.bugs.filter((b) => b.status === "open" && b.priority === "high"))
      items.push({ level: "serious", project: p, title: b.title, text: b.detail, tag: "Bug" });
  }
  const rank = { critical: 0, serious: 1, warning: 2, info: 3 };
  return items.sort((a, b) => rank[a.level] - rank[b.level] || PRIORITY_META[a.project.priority].rank - PRIORITY_META[b.project.priority].rank);
}

export function almostDone(projects, n = 5) {
  return projects.filter((p) => p.status !== "Completed" && p.status !== "Paused" && p.progress >= 60)
    .sort((a, b) => b.progress - a.progress).slice(0, n);
}

export function upcomingMilestones(projects) {
  const out = [];
  for (const p of projects) {
    for (const m of p.milestones.filter((m) => m.status !== "done"))
      out.push({ project: p, title: m.title, due: m.due, kind: "milestone" });
    if (p.targetDate && p.status !== "Completed") out.push({ project: p, title: "Target completion", due: p.targetDate, kind: "target" });
  }
  return out.sort((a, b) => (a.due || "9999").localeCompare(b.due || "9999"));
}

export function recentActivity(projects, n = 12) {
  const ev = [];
  for (const p of projects) {
    for (const c of p.facts.git?.recent_commits || []) ev.push({ ts: c.ts, project: p, kind: "commit", text: c.subject });
    for (const s of p.facts.recentSessions) ev.push({ ts: s.end, project: p, kind: s.tool, text: s.title || s.last_prompt || "AI session" });
    for (const t of p.tasks) if (t.status === "done" && t.updatedAt && t.source === "user") ev.push({ ts: t.updatedAt, project: p, kind: "task", text: t.title });
  }
  return ev.filter((e) => e.ts).sort((a, b) => b.ts.localeCompare(a.ts)).slice(0, n);
}

export function recentlyCompleted(projects, n = 8) {
  const out = [];
  for (const p of projects)
    for (const t of p.tasks.filter((t) => t.status === "done"))
      out.push({ project: p, title: t.title, ts: t.updatedAt, source: t.source });
  return out.sort((a, b) => (b.ts || "").localeCompare(a.ts || "")).slice(0, n);
}

export function sumActivity(projects) {
  const out = {};
  for (const p of projects) for (const [d, counts] of Object.entries(p.facts.activity || {})) {
    out[d] ||= {};
    for (const [k, v] of Object.entries(counts)) out[d][k] = (out[d][k] || 0) + v;
  }
  return out;
}

export const SORTS = {
  updated: { label: "Recently updated", fn: (a, b) => (b.updatedAt || "").localeCompare(a.updatedAt || "") },
  progress: { label: "Progress", fn: (a, b) => b.progress - a.progress },
  priority: { label: "Priority", fn: (a, b) => PRIORITY_META[a.priority].rank - PRIORITY_META[b.priority].rank || b.progress - a.progress },
  health: { label: "Health", fn: (a, b) => (b.health ?? -1) - (a.health ?? -1) },
  phase: { label: "Lifecycle stage", fn: (a, b) => phaseIndex(b.phase) - phaseIndex(a.phase) },
  name: { label: "Name", fn: (a, b) => a.name.localeCompare(b.name) },
};

export const STATUS_FILTERS = {
  all: { label: "All", fn: () => true },
  active: { label: "Active", fn: (p) => p.status === "Active" },
  blocked: { label: "Blocked", fn: (p) => p.status === "Blocked" },
  close: { label: "Almost done", fn: isCloseToDone },
  paused: { label: "Paused", fn: (p) => p.status === "Paused" },
  completed: { label: "Completed", fn: (p) => p.status === "Completed" },
};

export function filterSort(projects, { q = "", status = "all", type = "all", sort = "updated" } = {}) {
  const needle = q.trim().toLowerCase();
  return projects
    .filter(STATUS_FILTERS[status]?.fn || (() => true))
    .filter((p) => type === "all" || p.type === type)
    .filter((p) => !needle || [p.name, p.oneLiner, p.type, p.phase, ...(p.technologies || [])].join(" ").toLowerCase().includes(needle))
    .sort(SORTS[sort]?.fn || SORTS.updated.fn);
}
