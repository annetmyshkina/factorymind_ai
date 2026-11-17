export type View = "overview" | "equipment" | "incidents" | "knowledge" | "quality";

export interface Equipment {
  id: number;
  code: string;
  name: string;
  equipment_type: string;
  location: string;
  is_active: boolean;
}

export interface Telemetry {
  id: number;
  equipment_id: number;
  measured_at: string;
  temperature_c: number;
  vibration_mm_s: number;
  compressor_running: boolean | null;
}

export type IncidentSeverity = "low" | "medium" | "high" | "critical";
export type IncidentStatus = "open" | "in_progress" | "resolved" | "closed";

export interface Incident {
  id: number;
  equipment_id: number;
  equipment_code: string;
  title: string;
  description: string | null;
  status: IncidentStatus;
  severity: IncidentSeverity;
  assigned_to: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
}

export interface KnowledgeDocument {
  id: number;
  title: string;
  document_type: string;
  description: string | null;
  language: string;
  source_name: string;
  created_at: string;
}

export interface OperationalReport {
  metrics_version: string;
  generated_at: string;
  cohort: {
    analysis_count: number;
    incident_count: number;
    completed_count: number;
    insufficient_count: number;
    analyses_with_feedback: number;
    feedback_coverage_rate: number | null;
  };
  feedback: {
    entry_count: number;
    helpful_count: number;
    unhelpful_count: number;
    incorrect_count: number;
    helpful_rate: number | null;
    incorrect_rate: number | null;
  };
  resolutions: {
    resolution_count: number;
    active_resolution_count: number;
    analyses_with_active_resolution: number;
    active_resolution_analysis_rate: number | null;
    corrected_resolution_count: number;
    ever_revoked_resolution_count: number;
  };
  interpretation_warnings: string[];
}

export interface DashboardData {
  equipment: Equipment[];
  incidents: Incident[];
  documents: KnowledgeDocument[];
  telemetry: Record<number, Telemetry[]>;
  quality: OperationalReport;
}

export type DataMode = "live" | "demo";
