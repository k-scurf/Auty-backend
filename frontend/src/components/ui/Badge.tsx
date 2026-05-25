type Variant =
  | "known"
  | "unknown"
  | "alert"
  | "neutral"
  | "ontime"
  | "late"
  | "complete"
  | "missing"
  | "clocked_in";

const styles: Record<Variant, string> = {
  known:      "bg-accent/15 text-accent border-accent/30",
  unknown:    "bg-warning/15 text-warning border-warning/30",
  alert:      "bg-danger/15 text-danger border-danger/30",
  neutral:    "bg-text-muted/20 text-text-secondary border-border",
  ontime:     "bg-accent/15 text-accent border-accent/30",
  late:       "bg-warning/15 text-warning border-warning/30",
  complete:   "bg-bg-elevated text-text-secondary border-border",
  missing:    "bg-danger/15 text-danger border-danger/30",
  clocked_in: "bg-accent/15 text-accent border-accent/30",
};

interface Props {
  label: string;
  variant?: Variant;
  className?: string;
}

export function Badge({ label, variant = "neutral", className = "" }: Props) {
  const isPulse = variant === "clocked_in";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium font-mono ${styles[variant]} ${className}`}
    >
      {isPulse && (
        <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
      )}
      {label}
    </span>
  );
}
