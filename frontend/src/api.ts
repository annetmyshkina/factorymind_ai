import { demoData } from "./demo";
import type { DashboardData, DataMode, Equipment, Incident, KnowledgeDocument, OperationalReport, Telemetry } from "./types";

const STORAGE_KEY = "factorymind-api-base";

export function getApiBase(): string {
  return localStorage.getItem(STORAGE_KEY)?.replace(/\/$/, "") ?? "";
}

export function saveApiBase(value: string): void {
  const normalized = value.trim().replace(/\/$/, "");
  if (normalized) localStorage.setItem(STORAGE_KEY, normalized);
  else localStorage.removeItem(STORAGE_KEY);
}

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${getApiBase()}${path}`, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

export async function loadDashboard(signal?: AbortSignal): Promise<{ data: DashboardData; mode: DataMode; error?: string }> {
  try {
    await request<{ status: string }>("/health", signal);
    const [equipment, incidents, documents, quality] = await Promise.all([
      request<Equipment[]>("/equipment", signal),
      request<Incident[]>("/incidents", signal),
      request<KnowledgeDocument[]>("/knowledge/documents", signal),
      request<OperationalReport>("/evaluations/operational/incident-analyses", signal),
    ]);
    const telemetryEntries = await Promise.all(
      equipment.slice(0, 12).map(async (item) => {
        try {
          return [item.id, await request<Telemetry[]>(`/equipment/${item.id}/telemetry?limit=24`, signal)] as const;
        } catch {
          return [item.id, []] as const;
        }
      }),
    );
    return {
      data: { equipment, incidents, documents, quality, telemetry: Object.fromEntries(telemetryEntries) },
      mode: "live",
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    return {
      data: demoData,
      mode: "demo",
      error: error instanceof Error ? error.message : "API недоступен",
    };
  }
}
