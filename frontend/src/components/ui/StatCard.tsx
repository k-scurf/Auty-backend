interface Trend {
  direction: "up" | "down";
  pct: number;
}

interface Props {
  value: string | number;
  label: string;
  color?: string;
  trend?: Trend;
  className?: string;
}

export function StatCard({ value, label, color = "#00D4AA", trend, className = "" }: Props) {
  return (
    <div
      className={`card relative overflow-hidden pl-4 py-4 pr-5 ${className}`}
      style={{ borderLeft: `3px solid ${color}` }}
    >
      <div className="text-[48px] font-bold leading-none text-text-primary font-sans">{value}</div>
      <div className="mt-1 text-sm text-text-secondary">{label}</div>
      {trend && (
        <div className="mt-1 text-xs text-text-secondary">
          <span>{trend.direction === "up" ? "↑" : "↓"}</span>
          <span className="ml-0.5">{trend.pct}%</span>
        </div>
      )}
    </div>
  );
}
