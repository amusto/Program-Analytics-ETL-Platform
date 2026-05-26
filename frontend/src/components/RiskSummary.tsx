import type { ProgramRollup } from "../api";

interface Props {
  programs: ProgramRollup[];
}

export default function RiskSummary({ programs }: Props) {
  return (
    <table>
      <thead>
        <tr>
          <th>Program</th>
          <th>Portfolio</th>
          <th>Owner</th>
          <th className="right">Projects</th>
          <th className="right">Critical</th>
          <th className="right">At Risk</th>
          <th className="right">On Track</th>
          <th className="right">Avg Util %</th>
          <th className="right">Open Risks</th>
        </tr>
      </thead>
      <tbody>
        {programs.map((p) => (
          <tr key={p.program_id}>
            <td>
              <div>{p.name}</div>
              <div className="muted" style={{ fontSize: 11 }}>
                {p.program_id}
              </div>
            </td>
            <td>{p.portfolio}</td>
            <td>{p.program_manager}</td>
            <td className="right">{p.project_count}</td>
            <td className="right" style={{ color: "var(--critical)" }}>
              {p.critical_projects || ""}
            </td>
            <td className="right" style={{ color: "var(--at-risk)" }}>
              {p.at_risk_projects || ""}
            </td>
            <td className="right" style={{ color: "var(--on-track)" }}>
              {p.on_track_projects || ""}
            </td>
            <td className="right">{p.average_budget_utilization.toFixed(1)}%</td>
            <td className="right">{p.open_risks}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
