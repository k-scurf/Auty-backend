type Variant = "ontime" | "late" | "complete" | "missing" | "clocked_in" | "neutral";

const CONFIG: Record<Variant, { label: string; classes: string; pulse?: boolean }> = {
  ontime:     { label: "On time",     classes: "bg-accent/15 text-accent border-accent/30" },
  late:       { label: "Late",        classes: "bg-warning/15 text-warning border-warning/30" },
  complete:   { label: "Done",        classes: "bg-bg-elevated text-text-secondary border-border" },
  missing:    { label: "Missing",     classes: "bg-danger/15 text-danger border-danger/30" },
  clocked_in: { label: "Clocked In",  classes: "bg-accent/15 text-accent border-accent/30", pulse: true },
  neutral:    { label: "Neutral",     classes: "bg-bg-elevated text-text-secondary border-border" },
};

interface Props {
  variant: Variant;
  label?: string;
  className?: string;
}

export function AttendanceBadge({ variant, label, className = "" }: Props) {
  const cfg = CONFIG[variant];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-xs font-medium ${cfg.classes} ${className}`}
    >
      {cfg.pulse && (
        <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
      )}
      {label ?? cfg.label}
    </span>
  );
}
