type Variant = "known" | "unknown" | "alert" | "neutral";

const styles: Record<Variant, string> = {
  known: "bg-accent/20 text-accent border-accent/40",
  unknown: "bg-amber-500/20 text-amber-300 border-amber-500/40",
  alert: "bg-red-500/20 text-red-300 border-red-500/40",
  neutral: "bg-slate-500/20 text-slate-300 border-slate-500/40",
};

interface Props {
  label: string;
  variant?: Variant;
}

export function Badge({ label, variant = "neutral" }: Props) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${styles[variant]}`}
    >
      {label}
    </span>
  );
}
