import { useSyncExternalStore } from "react";

import type { View } from "./types";

export type IncidentFilter = "active" | "all";

interface NavigationState {
  view: View;
  filter: IncidentFilter;
  incidentId: number | null;
}

const views: View[] = ["overview", "equipment", "incidents", "knowledge", "quality"];

function parseHash(hash: string): NavigationState {
  const [section, query] = hash.replace(/^#/, "").split("?");
  const params = new URLSearchParams(query);
  const id = Number(params.get("incident"));
  return {
    view: views.includes(section as View) ? section as View : "overview",
    filter: params.get("filter") === "all" ? "all" : "active",
    incidentId: Number.isSafeInteger(id) && id > 0 ? id : null,
  };
}

function subscribe(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  window.addEventListener("popstate", onChange);
  return () => {
    window.removeEventListener("hashchange", onChange);
    window.removeEventListener("popstate", onChange);
  };
}

const getSnapshot = () => window.location.hash;

function navigate(change: Partial<NavigationState>) {
  const next = { ...parseHash(window.location.hash), ...change };
  const params = new URLSearchParams();
  if (next.filter === "all") params.set("filter", "all");
  if (next.incidentId !== null) params.set("incident", String(next.incidentId));
  const query = params.toString();
  const nextHash = `#${next.view}${query ? `?${query}` : ""}`;
  if (nextHash !== window.location.hash) {
    window.history.pushState(null, "", nextHash);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  }
}

// Hash-маршрут работает и на Vite, и в статической сборке под /ui/.
export function useNavigation() {
  const hash = useSyncExternalStore(subscribe, getSnapshot);
  const state = parseHash(hash);
  return { ...state, navigate };
}
