type Variant = "time" | "duration" | "date" | "datetime";

function fmt(ts: number, variant: Variant): string {
  const d = new Date(ts);
  switch (variant) {
    case "time":
      return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
    case "duration": {
      const secs = Math.max(0, Math.floor(ts));
      const h = Math.floor(secs / 3600);
      const m = Math.floor((secs % 3600) / 60);
      return h > 0 ? `${h}h ${m}m` : `${m}m`;
    }
    case "date":
      return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
    case "datetime":
      return (
        d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) +
        " · " +
        d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })
      );
    default:
      return "";
  }
}

interface Props {
  ts?: number;
  variant?: Variant;
  className?: string;
}

export function TimeDisplay({ ts, variant = "time", className = "" }: Props) {
  if (ts === undefined) return <span className={`font-mono ${className}`}>—</span>;
  return (
    <span className={`font-mono ${className}`}>
      {fmt(ts, variant)}
    </span>
  );
}
