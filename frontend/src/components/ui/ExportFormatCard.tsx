type Format = "gusto" | "adp" | "square";

const META: Record<Format, { name: string; desc: string; icon: string }> = {
  gusto:  { name: "Gusto",   desc: "CSV · Regular + OT columns", icon: "G" },
  adp:    { name: "ADP Run", desc: "CSV · Employee ID required",  icon: "A" },
  square: { name: "Square",  desc: "CSV · Payroll compatible",    icon: "S" },
};

interface Props {
  format: Format;
  selected: boolean;
  onSelect: () => void;
  preview?: string;
}

export function ExportFormatCard({ format, selected, onSelect, preview }: Props) {
  const m = META[format];
  return (
    <button
      onClick={onSelect}
      className={`relative flex flex-col items-start gap-1 rounded-card border p-4 text-left transition-colors w-full
        ${selected
          ? "border-accent bg-accent/5 shadow-glow"
          : "border-border bg-bg-surface hover:border-accent/40"
        }`}
    >
      {selected && (
        <span className="absolute right-3 top-3 flex h-5 w-5 items-center justify-center rounded-full bg-accent text-bg text-xs font-bold">
          ✓
        </span>
      )}
      <div className="flex h-8 w-8 items-center justify-center rounded bg-bg-elevated font-bold text-text-primary text-sm">
        {m.icon}
      </div>
      <div className="mt-1 font-semibold text-text-primary text-sm">{m.name}</div>
      <div className="text-xs text-text-secondary">{m.desc}</div>
      {preview && (
        <div className="mt-1 font-mono text-xs text-text-muted">{preview}</div>
      )}
    </button>
  );
}
