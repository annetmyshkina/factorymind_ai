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

export interface IncidentEvent {
  id: number;
  event_type: string;
  payload: Record<string, unknown> | null;
  created_at: string;
}

export interface IncidentDetail extends Incident {
  deviation_ids: number[];
  events: IncidentEvent[];
}

export interface Deviation {
  id: number;
  equipment_id: number;
  telemetry_id: number | null;
  rule_id: number | null;
  metric_name: string;
  observed_value: number;
  threshold_value: number;
  message: string;
  detected_at: string;
  is_resolved: boolean;
}

export interface AnalysisCitedItem {
  text: string;
  source_chunk_ids: number[];
  resolution_ids: number[];
}

export interface IncidentAnalysis {
  id: number;
  incident_id: number;
  llm_call_id: number | null;
  query: string;
  prompt_version: string;
  status: "completed" | "insufficient";
  result: {
    observed_facts: string[];
    possible_causes: AnalysisCitedItem[];
    required_checks: AnalysisCitedItem[];
    recommendations: AnalysisCitedItem[];
    insufficient_data: string[];
    warnings: string[];
  };
  sources: Array<{
    rank: number;
    score: number;
    chunk_id: number;
    content: string;
    document_title: string;
    document_version: string;
    page_start: number | null;
    page_end: number | null;
    citation: string;
  }>;
  experiences: Array<{
    rank: number;
    resolution_id: number;
    incident_id: number;
    incident_title: string;
    equipment_code: string;
    confirmed_cause: string | null;
    actions_taken: string[];
    outcome: string;
    citation: string;
  }>;
  created_at: string;
}

export type FeedbackRating = "helpful" | "unhelpful" | "incorrect";

export interface AnalysisFeedback {
  id: number;
  analysis_id: number;
  rating: FeedbackRating;
  comment: string | null;
  actor: string;
  actor_verified: boolean;
  created_at: string;
}

export interface IncidentResolution {
  id: number;
  incident_id: number;
  analysis_id: number | null;
  checks_performed: string[];
  confirmed_cause: string | null;
  actions_taken: string[];
  outcome: string;
  actor: string;
  actor_verified: boolean;
  is_active: boolean;
  revision: number;
  confirmed_at: string;
  updated_at: string;
  revoked_at: string | null;
}

export interface IncidentWorkspace {
  detail: IncidentDetail;
  deviations: Deviation[];
  analyses: IncidentAnalysis[];
  resolution: IncidentResolution | null;
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

export type UserRole = "viewer" | "operator" | "engineer" | "admin";

export interface CurrentUser {
  id: number;
  username: string;
  full_name: string | null;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}
