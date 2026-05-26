interface Props {
  label: string;
  value: string | number;
  tone?: "critical" | "at-risk" | "on-track";
}

export default function KpiCard({ label, value, tone }: Props) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value${tone ? ` ${tone}` : ""}`}>{value}</div>
    </div>
  );
}
