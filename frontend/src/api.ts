/**
 * Thin typed wrapper around the FastAPI analytics endpoints.
 *
 * Kept intentionally small: no client-side caching, no state machine —
 * the components own that. This file just guarantees the wire types
 * stay in sync with the backend Pydantic schemas.
 */

export interface AnalyticsSummary {
  totalPrograms: number;
  totalProjects: number;
  criticalProjects: number;
  atRiskProjects: number;
  averageBudgetUtilization: number;
  openRisks: number;
}

export interface ProgramRollup {
  program_id: string;
  name: string;
  portfolio: string;
  program_manager: string;
  project_count: number;
  critical_projects: number;
  at_risk_projects: number;
  on_track_projects: number;
  average_budget_utilization: number;
  open_risks: number;
}

export type ProjectHealth = "ON_TRACK" | "AT_RISK" | "CRITICAL";

export interface AtRiskProject {
  project_id: string;
  name: string;
  owner: string;
  status: string;
  program_id: string;
  program_name: string;
  project_health: ProjectHealth;
  budget_utilization_percent: number;
  schedule_variance_days: number;
  open_risk_count: number;
  open_high_severity_risk_count: number;
}

const BASE = import.meta.env.VITE_API_BASE ?? "";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    throw new Error(`${path} failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  summary: () => get<AnalyticsSummary>("/analytics/summary"),
  programs: () => get<ProgramRollup[]>("/analytics/programs"),
  atRiskProjects: () => get<AtRiskProject[]>("/analytics/projects/at-risk"),
  triggerEtl: async () => {
    const res = await fetch(`${BASE}/etl/run`, { method: "POST" });
    if (!res.ok) throw new Error(`ETL trigger failed: ${res.status}`);
    return res.json();
  },
};
