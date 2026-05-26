import type { AtRiskProject } from "../api";

interface Props {
  projects: AtRiskProject[];
}

export default function ProjectTable({ projects }: Props) {
  if (projects.length === 0) {
    return <p className="muted">No projects currently flagged as at-risk or critical.</p>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Project</th>
          <th>Program</th>
          <th>Owner</th>
          <th>Health</th>
          <th className="right">Budget Util %</th>
          <th className="right">Schedule Var (days)</th>
          <th className="right">Open Risks</th>
        </tr>
      </thead>
      <tbody>
        {projects.map((p) => (
          <tr key={p.project_id}>
            <td>
              <div>{p.name}</div>
              <div className="muted" style={{ fontSize: 11 }}>
                {p.project_id}
              </div>
            </td>
            <td>{p.program_name}</td>
            <td>{p.owner}</td>
            <td>
              <span className={`health-pill ${p.project_health}`}>
                {p.project_health.replace("_", " ")}
              </span>
            </td>
            <td className="right">{p.budget_utilization_percent.toFixed(1)}%</td>
            <td className="right">{p.schedule_variance_days}</td>
            <td className="right">
              {p.open_risk_count}
              {p.open_high_severity_risk_count > 0 && (
                <span className="muted"> ({p.open_high_severity_risk_count} high)</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
