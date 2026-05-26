import { useCallback, useEffect, useState } from "react";
import {
  api,
  type AnalyticsSummary,
  type AtRiskProject,
  type ProgramRollup,
} from "./api";
import KpiCard from "./components/KpiCard";
import ProjectTable from "./components/ProjectTable";
import RiskSummary from "./components/RiskSummary";

interface DashboardData {
  summary: AnalyticsSummary;
  programs: ProgramRollup[];
  atRisk: AtRiskProject[];
}

export default function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloading, setReloading] = useState(false);

  const fetchAll = useCallback(async () => {
    setError(null);
    try {
      const [summary, programs, atRisk] = await Promise.all([
        api.summary(),
        api.programs(),
        api.atRiskProjects(),
      ]);
      setData({ summary, programs, atRisk });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
      setReloading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const handleEtl = async () => {
    setReloading(true);
    try {
      await api.triggerEtl();
      await fetchAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setReloading(false);
    }
  };

  if (loading) {
    return (
      <div className="app">
        <p className="muted">Loading program analytics…</p>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="page-header">
        <div>
          <h1>Program Analytics</h1>
          <p>Enterprise PMO health derived from the latest ETL load.</p>
        </div>
        <button className="refresh" disabled={reloading} onClick={handleEtl}>
          {reloading ? "Running ETL…" : "Re-run ETL"}
        </button>
      </header>

      {error && <div className="error">{error}</div>}

      {data && (
        <>
          <section className="kpi-grid">
            <KpiCard label="Programs" value={data.summary.totalPrograms} />
            <KpiCard label="Projects" value={data.summary.totalProjects} />
            <KpiCard
              label="Critical projects"
              value={data.summary.criticalProjects}
              tone="critical"
            />
            <KpiCard
              label="At-risk projects"
              value={data.summary.atRiskProjects}
              tone="at-risk"
            />
            <KpiCard
              label="Avg budget utilization"
              value={`${data.summary.averageBudgetUtilization.toFixed(1)}%`}
            />
            <KpiCard label="Open risks" value={data.summary.openRisks} />
          </section>

          <section className="section">
            <h2>Projects requiring attention</h2>
            <ProjectTable projects={data.atRisk} />
          </section>

          <section className="section">
            <h2>Program rollup</h2>
            <RiskSummary programs={data.programs} />
          </section>
        </>
      )}
    </div>
  );
}
