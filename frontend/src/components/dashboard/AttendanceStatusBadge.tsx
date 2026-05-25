import type { AttendanceStatusValue } from "../../types";

const STATUS_CONFIG: Record<
  AttendanceStatusValue,
  { label: string; bg: string; text: string; border: string }
> = {
  on_time: {
    label: "On time",
    bg: "var(--color-background-success, var(--color-bg-success))",
    text: "var(--color-text-success, var(--color-accent))",
    border: "rgba(0, 212, 170, 0.3)",
  },
  late: {
    label: "Late",
    bg: "var(--color-background-warning, rgba(255, 176, 32, 0.12))",
    text: "var(--color-text-warning, var(--color-warning))",
    border: "rgba(255, 176, 32, 0.35)",
  },
  absent: {
    label: "Absent",
    bg: "var(--color-background-danger, rgba(255, 91, 91, 0.12))",
    text: "var(--color-text-danger, var(--color-danger))",
    border: "rgba(255, 91, 91, 0.35)",
  },
  complete: {
    label: "Complete",
    bg: "var(--color-background-secondary, var(--color-bg-elevated))",
    text: "var(--color-text-secondary)",
    border: "var(--color-border)",
  },
  missing_clockout: {
    label: "Still in",
    bg: "var(--color-background-warning, rgba(255, 176, 32, 0.12))",
    text: "var(--color-text-warning, var(--color-warning))",
    border: "rgba(255, 176, 32, 0.35)",
  },
  no_schedule: {
    label: "No schedule",
    bg: "var(--color-background-secondary, var(--color-bg-elevated))",
    text: "var(--color-text-secondary)",
    border: "var(--color-border)",
  },
  day_off: {
    label: "Day off",
    bg: "var(--color-background-secondary, var(--color-bg-elevated))",
    text: "var(--color-text-secondary)",
    border: "var(--color-border)",
  },
};

export function AttendanceStatusBadge({ status }: { status: AttendanceStatusValue }) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.no_schedule;
  return (
    <span
      className="inline-flex items-center rounded-full border px-2.5 py-1 text-[12px] font-semibold leading-none shadow-sm"
      style={{ background: cfg.bg, color: cfg.text, borderColor: cfg.border }}
    >
      {cfg.label}
    </span>
  );
}
