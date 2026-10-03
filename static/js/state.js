// Shared app state. `data` is the last /api/state payload; `ui` holds per-viewer view preferences.
import { store } from "./util.js";

const UI_DEFAULTS = { q: "", status: "all", type: "all", sort: "updated", view: "grid", ytApp: "all", ytRange: "30" };

export const state = {
  data: null,
  ui: { ...UI_DEFAULTS, ...store.get("pt-ui", {}), q: "" },
  animate: false,          // true for the first render of a route (entrance animations)
  // Transient planner UI (not saved): which cards are expanded, the open skip form, the AI-context draft.
  planUi: { open: {}, skipFor: null, addOpen: false, draft: "", dismissed: null },
  history: null,           // /api/planner/history days, loaded when the history route opens
};

export function saveUi() {
  const { q, ...rest } = state.ui;
  store.set("pt-ui", rest);
}

export const project = (id) => state.data?.projects.find((p) => p.id === id);
