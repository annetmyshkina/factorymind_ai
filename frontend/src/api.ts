import { demoData } from "./demo";
import type { AnalysisFeedback, CreatedEquipmentApiKey, CurrentUser, DashboardData, DataMode, Deviation, Equipment, EquipmentApiKey, FeedbackRating, Incident, IncidentAnalysis, IncidentDetail, IncidentResolution, IncidentStatus, IncidentWorkspace, KnowledgeDocument, OperationalReport, Telemetry } from "./types";

const STORAGE_KEY = "factorymind-api-base";
const TOKEN_KEY = "factorymind-access-token";
export const AUTH_EXPIRED_EVENT = "factorymind-auth-expired";

export function getApiBase(): string {
  return localStorage.getItem(STORAGE_KEY)?.replace(/\/$/, "") ?? "";
}

export function saveApiBase(value: string): void {
  const normalized = value.trim().replace(/\/$/, "");
  if (normalized) localStorage.setItem(STORAGE_KEY, normalized);
  else localStorage.removeItem(STORAGE_KEY);
}

export function getAccessToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

function saveAccessToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function logout(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const token = getAccessToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${getApiBase()}${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/token") {
      logout();
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    }
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json() as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail && typeof body.detail === "object" && "message" in body.detail) message = String(body.detail.message);
    } catch {
      // Ответ без JSON оставляет стандартное HTTP-сообщение.
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function login(username: string, password: string): Promise<CurrentUser> {
  const form = new URLSearchParams({ username, password });
  const response = await apiRequest<{ access_token: string }>("/auth/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
  });
  saveAccessToken(response.access_token);
  return loadCurrentUser();
}

export function loadCurrentUser(signal?: AbortSignal): Promise<CurrentUser> {
  return apiRequest<CurrentUser>("/auth/me", { signal });
}

export function loadEquipmentApiKeys(equipmentId: number, signal?: AbortSignal): Promise<EquipmentApiKey[]> {
  return get(`/equipment/${equipmentId}/api-keys`, signal);
}

export function createEquipmentApiKey(
  equipmentId: number,
  payload: { name: string; expires_at: string | null },
): Promise<CreatedEquipmentApiKey> {
  return apiRequest(`/equipment/${equipmentId}/api-keys`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function revokeEquipmentApiKey(equipmentId: number, keyId: number): Promise<EquipmentApiKey> {
  return apiRequest(`/equipment/${equipmentId}/api-keys/${keyId}/revoke`, {
    method: "POST",
  });
}

function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  return apiRequest<T>(path, { signal });
}

export async function loadDashboard(signal?: AbortSignal): Promise<{ data: DashboardData; mode: DataMode; error?: string }> {
  try {
    await get<{ status: string }>("/health", signal);
    const [equipment, incidents, documents, quality] = await Promise.all([
      get<Equipment[]>("/equipment", signal),
      get<Incident[]>("/incidents", signal),
      get<KnowledgeDocument[]>("/knowledge/documents", signal),
      get<OperationalReport>("/evaluations/operational/incident-analyses", signal),
    ]);
    const telemetryEntries = await Promise.all(
      equipment.slice(0, 12).map(async (item) => {
        try {
          return [item.id, await get<Telemetry[]>(`/equipment/${item.id}/telemetry?limit=24`, signal)] as const;
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

export async function loadIncidentWorkspace(incidentId: number, signal?: AbortSignal): Promise<IncidentWorkspace> {
  const detail = await get<IncidentDetail>(`/incidents/${incidentId}`, signal);
  const [allDeviations, analyses, resolution] = await Promise.all([
    get<Deviation[]>(`/equipment/${detail.equipment_id}/deviations`, signal),
    get<IncidentAnalysis[]>(`/incidents/${incidentId}/analyses`, signal),
    get<IncidentResolution>(`/incidents/${incidentId}/resolution`, signal).catch((error) => {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }),
  ]);
  const deviationIds = new Set(detail.deviation_ids);
  return {
    detail,
    deviations: allDeviations.filter((item) => deviationIds.has(item.id)),
    analyses,
    resolution,
  };
}

export function updateIncident(
  incidentId: number,
  payload: { status?: IncidentStatus; assigned_to?: string | null; severity?: Incident["severity"] },
): Promise<Incident> {
  return apiRequest(`/incidents/${incidentId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function createIncidentAnalysis(
  incidentId: number,
  payload: { query: string; provider: "ollama" | "compatible"; model: string | null; max_sources: number; max_experiences: number },
): Promise<IncidentAnalysis> {
  return apiRequest(`/incidents/${incidentId}/analyses`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function loadAnalysisFeedback(incidentId: number, analysisId: number): Promise<AnalysisFeedback[]> {
  return get(`/incidents/${incidentId}/analyses/${analysisId}/feedback`);
}

export function addAnalysisFeedback(
  incidentId: number,
  analysisId: number,
  payload: { rating: FeedbackRating; comment: string | null },
): Promise<AnalysisFeedback> {
  return apiRequest(`/incidents/${incidentId}/analyses/${analysisId}/feedback`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function confirmIncidentResolution(
  incidentId: number,
  payload: { analysis_id: number | null; checks_performed: string[]; confirmed_cause: string | null; actions_taken: string[]; outcome: string; reason?: string },
): Promise<IncidentResolution> {
  return apiRequest(`/incidents/${incidentId}/resolution`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
