import { useEffect, useState } from "react";
import { fetchSchedule, saveSchedule } from "../../services/api";
import type { ScheduleDay, WeeklySchedule } from "../../types";

const DAYS = [
  { key: "mon", label: "Mon" },
  { key: "tue", label: "Tue" },
  { key: "wed", label: "Wed" },
  { key: "thu", label: "Thu" },
  { key: "fri", label: "Fri" },
  { key: "sat", label: "Sat" },
  { key: "sun", label: "Sun" },
];

const TIMEZONES = [
  { value: "America/New_York", label: "Eastern" },
  { value: "America/Chicago", label: "Central" },
  { value: "America/Denver", label: "Mountain" },
  { value: "America/Los_Angeles", label: "Pacific" },
];

function detectTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "America/Chicago";
  } catch {
    return "America/Chicago";
  }
}

function timezoneOptions(current: string) {
  const options = [...TIMEZONES];
  const seen = new Set(options.map((tz) => tz.value));
  const detected = detectTimezone();
  for (const value of [detected, current]) {
    if (value && !seen.has(value)) {
      options.push({
        value,
        label: value === detected ? "Detected timezone" : value,
      });
      seen.add(value);
    }
  }
  return options;
}

function emptyDays(): Record<string, ScheduleDay> {
  return Object.fromEntries(
    DAYS.map((d) => [d.key, { working: false, start: null, end: null }])
  );
}

function defaultSchedule(employeeId: string, employeeName: string): WeeklySchedule {
  return {
    employee_id: employeeId,
    name: employeeName,
    timezone: detectTimezone(),
    days: emptyDays(),
  };
}

function errorMessage(err: unknown): string {
  if (err && typeof err === "object" && "response" in err) {
    const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      return String((detail as { message?: unknown }).message);
    }
  }
  return "Could not save schedule. Please try again.";
}

interface Props {
  employeeId: string;
  employeeName: string;
  onSaved?: () => void;
  onClose?: () => void;
}

export function ScheduleEditor({ employeeId, employeeName, onSaved, onClose }: Props) {
  const [schedule, setSchedule] = useState<WeeklySchedule>(() =>
    defaultSchedule(employeeId, employeeName)
  );
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchSchedule(employeeId)
      .then((data) => {
        if (!cancelled) {
          setSchedule({
            ...defaultSchedule(employeeId, employeeName),
            ...data,
            days: { ...emptyDays(), ...(data.days ?? {}) },
          });
        }
      })
      .catch(() => {
        if (!cancelled) setSchedule(defaultSchedule(employeeId, employeeName));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [employeeId, employeeName]);

  const setDay = (key: string, day: ScheduleDay) => {
    setSchedule((prev) => ({
      ...prev,
      days: { ...prev.days, [key]: day },
    }));
  };

  const applyWeekdays = () => {
    const next = emptyDays();
    for (const key of ["mon", "tue", "wed", "thu", "fri"]) {
      next[key] = { working: true, start: "09:00", end: "17:00" };
    }
    setSchedule((prev) => ({ ...prev, days: next }));
  };

  const clearAll = () => {
    setSchedule((prev) => ({ ...prev, days: emptyDays() }));
  };

  const handleSave = async () => {
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const result = await saveSchedule(employeeId, {
        ...schedule,
        employee_id: employeeId,
        name: employeeName,
      });
      setSchedule(result);
      setSaved(true);
      onSaved?.();
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card p-4 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">Edit Schedule</h3>
          <p className="text-xs text-text-muted mt-0.5">{employeeName}</p>
        </div>
        {onClose && (
          <button type="button" onClick={onClose} className="btn-ghost px-2 py-1 text-xs">
            Close
          </button>
        )}
      </div>

      {loading ? (
        <div className="skeleton h-44" />
      ) : (
        <div className="space-y-2">
          {DAYS.map(({ key, label }) => {
            const day = schedule.days[key] ?? { working: false, start: null, end: null };
            return (
              <div
                key={key}
                className="flex flex-wrap items-center gap-3 rounded-xl border border-border/60 bg-bg-elevated px-3 py-2.5"
              >
                <span className="w-9 font-mono text-xs font-semibold text-text-secondary">{label}</span>
                <button
                  type="button"
                  onClick={() =>
                    setDay(
                      key,
                      day.working
                        ? { working: false, start: null, end: null }
                        : { working: true, start: day.start ?? "09:00", end: day.end ?? "17:00" }
                    )
                  }
                  className="grid grid-cols-2 rounded-full border border-border bg-bg-surface p-0.5 text-[11px] font-semibold transition-colors"
                  aria-label={`${label} working toggle`}
                >
                  <span className={`rounded-full px-2 py-1 transition-colors ${
                    day.working ? "bg-accent text-bg" : "text-text-muted"
                  }`}>
                    Working
                  </span>
                  <span className={`rounded-full px-2 py-1 transition-colors ${
                    !day.working ? "bg-bg-elevated text-text-primary" : "text-text-muted"
                  }`}>
                    Off
                  </span>
                </button>
                {day.working ? (
                  <div className="flex flex-1 items-center gap-2 rounded-full border border-border/70 bg-bg-surface px-2 py-1 min-w-[210px]">
                    <input
                      type="time"
                      value={day.start ?? "09:00"}
                      onChange={(e) => setDay(key, { ...day, start: e.target.value })}
                      className="min-w-[80px] rounded-full border border-transparent bg-bg-elevated px-2 py-1 text-xs font-mono text-text-primary outline-none transition-colors focus:border-accent"
                    />
                    <span className="text-xs text-text-muted">→</span>
                    <input
                      type="time"
                      value={day.end ?? "17:00"}
                      onChange={(e) => setDay(key, { ...day, end: e.target.value })}
                      className="min-w-[80px] rounded-full border border-transparent bg-bg-elevated px-2 py-1 text-xs font-mono text-text-primary outline-none transition-colors focus:border-accent"
                    />
                  </div>
                ) : (
                  <span className="flex-1 rounded-full border border-border/40 bg-bg-surface px-3 py-1.5 text-xs text-text-muted">
                    Day off
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={applyWeekdays}
          className="rounded-full border border-accent/30 bg-accent/10 px-3 py-1.5 text-xs font-semibold text-accent transition-colors hover:bg-accent/15"
        >
          Apply Mon-Fri 9-5
        </button>
        <button
          type="button"
          onClick={clearAll}
          className="rounded-full border border-border bg-bg-elevated px-3 py-1.5 text-xs font-semibold text-text-secondary transition-colors hover:border-danger/40 hover:text-danger"
        >
          Clear all
        </button>
      </div>

      <label className="block space-y-1">
        <span className="text-xs font-medium text-text-secondary">Timezone</span>
        <select
          className="input w-full"
          value={schedule.timezone}
          onChange={(e) => setSchedule((prev) => ({ ...prev, timezone: e.target.value }))}
        >
          {timezoneOptions(schedule.timezone).map((tz) => (
            <option key={tz.value} value={tz.value}>
              {tz.label} ({tz.value})
            </option>
          ))}
        </select>
      </label>

      {error && <p className="text-sm text-danger">{error}</p>}
      {saved && <p className="text-sm text-accent">Saved</p>}

      <button type="button" onClick={handleSave} disabled={saving || loading} className="btn-primary w-full">
        {saving ? "Saving..." : "Save Schedule"}
      </button>
    </div>
  );
}
