type Variant = "warning" | "danger" | "info";

const CONFIG: Record<Variant, { bg: string; border: string; text: string; icon: string }> = {
  warning: {
    bg: "bg-warning/10",
    border: "border-warning/30",
    text: "text-warning",
    icon: "⚠",
  },
  danger: {
    bg: "bg-danger/10",
    border: "border-danger/30",
    text: "text-danger",
    icon: "✕",
  },
  info: {
    bg: "bg-accent-blue/10",
    border: "border-accent-blue/30",
    text: "text-accent-blue",
    icon: "ℹ",
  },
};

interface Props {
  variant?: Variant;
  message: string;
  action?: { label: string; onClick: () => void };
  onDismiss?: () => void;
  className?: string;
}

export function AlertBanner({ variant = "warning", message, action, onDismiss, className = "" }: Props) {
  const cfg = CONFIG[variant];
  return (
    <div
      className={`flex items-center gap-3 rounded-card border px-4 py-3 text-sm ${cfg.bg} ${cfg.border} ${className}`}
    >
      <span className={`shrink-0 text-base font-bold ${cfg.text}`}>{cfg.icon}</span>
      <span className="flex-1 text-text-primary">{message}</span>
      {action && (
        <button
          onClick={action.onClick}
          className={`shrink-0 font-medium underline-offset-2 hover:underline ${cfg.text}`}
        >
          {action.label}
        </button>
      )}
      {onDismiss && (
        <button
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 text-text-muted hover:text-text-secondary transition-colors"
        >
          ✕
        </button>
      )}
    </div>
  );
}
