import { useCallback, useEffect, useState } from "react";
import { fetchProfiles, fetchSchedule, saveSchedule } from "../services/api";
import type { Profile, WeeklySchedule, ScheduleDay } from "../types";

// ─── constants ───────────────────────────────────────────────────────────────

const DAYS = [
  { key: "mon", label: "Mon", long: "Monday" },
  { key: "tue", label: "Tue", long: "Tuesday" },
  { key: "wed", label: "Wed", long: "Wednesday" },
  { key: "thu", label: "Thu", long: "Thursday" },
  { key: "fri", label: "Fri", long: "Friday" },
  { key: "sat", label: "Sat", long: "Saturday" },
  { key: "sun", label: "Sun", long: "Sunday" },
];

function emptyDays(): Record<string, ScheduleDay> {
  return Object.fromEntries(
    DAYS.map((d) => [d.key, { working: false, start: null, end: null }])
  );
}

function defaultSchedule(employeeId: string, name: string): WeeklySchedule {
  return { employee_id: employeeId, name, timezone: "America/Chicago", days: emptyDays() };
}

// ─── sub-components ──────────────────────────────────────────────────────────

function TimeInput({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <input
      type="time"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-[78px] rounded border border-border/60 bg-bg px-1.5 py-0.5 text-[11px] font-mono text-text-primary outline-none focus:border-accent"
    />
  );
}

function DayCell({
  day,
  onChange,
}: {
  day: ScheduleDay;
  onChange: (d: ScheduleDay) => void;
}) {
  return (
    <td className="px-1.5 py-2 text-center align-middle">
      {day.working ? (
        <div className="flex flex-col items-center gap-0.5">
          <TimeInput
            value={day.start ?? "09:00"}
            onChange={(v) => onChange({ ...day, start: v })}
          />
          <span className="text-[9px] text-text-muted">to</span>
          <TimeInput
            value={day.end ?? "17:00"}
            onChange={(v) => onChange({ ...day, end: v })}
          />
          <button
            type="button"
            onClick={() => onChange({ working: false, start: null, end: null })}
            className="mt-0.5 text-[9px] text-text-muted hover:text-danger transition-colors"
          >
            off
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => onChange({ working: true, start: "09:00", end: "17:00" })}
          className="h-10 w-full rounded border border-dashed border-border/40 text-[10px] text-text-muted hover:border-accent/60 hover:text-accent transition-colors"
        >
          +
        </button>
      )}
    </td>
  );
}

// ─── main page ────────────────────────────────────────────────────────────────

type EmployeeSchedule = WeeklySchedule & { profileId: string };

export function SchedulePage() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [schedules, setSchedules] = useState<Record<string, EmployeeSchedule>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchProfiles().then(async (profs) => {
      if (cancelled) return;
      setProfiles(profs);
      const map: Record<string, EmployeeSchedule> = {};
      await Promise.all(
        profs.map(async (p) => {
          const id = (p.id ?? p.name).trim();
          try {
            const s = await fetchSchedule(id);
            map[id] = { ...s, profileId: id };
          } catch {
            map[id] = { ...defaultSchedule(id, p.name), profileId: id };
          }
        })
      );
      if (!cancelled) { setSchedules(map); setLoading(false); }
    }).catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const setDay = useCallback((profileId: string, dayKey: string, day: ScheduleDay) => {
    setSchedules((prev) => ({
      ...prev,
      [profileId]: { ...prev[profileId], days: { ...prev[profileId].days, [dayKey]: day } },
    }));
  }, []);

  const applyWeekdays = (profileId: string) => {
    setSchedules((prev) => {
      const curr = prev[profileId];
      const days = { ...curr.days };
      for (const { key } of DAYS.slice(0, 5)) days[key] = { working: true, start: "09:00", end: "17:00" };
      for (const { key } of DAYS.slice(5)) days[key] = { working: false, start: null, end: null };
      return { ...prev, [profileId]: { ...curr, days } };
    });
  };

  const clearEmployee = (profileId: string) => {
    setSchedules((prev) => ({
      ...prev,
      [profileId]: { ...prev[profileId], days: emptyDays() },
    }));
  };

  const handleSave = async (profileId: string) => {
    setSaving((p) => ({ ...p, [profileId]: true }));
    setErrors((p) => ({ ...p, [profileId]: "" }));
    try {
      await saveSchedule(profileId, schedules[profileId]);
      setSaved((p) => ({ ...p, [profileId]: true }));
      setTimeout(() => setSaved((p) => ({ ...p, [profileId]: false })), 2000);
    } catch {
      setErrors((p) => ({ ...p, [profileId]: "Save failed" }));
    } finally {
      setSaving((p) => ({ ...p, [profileId]: false }));
    }
  };

  const handleSaveAll = async () => {
    await Promise.all(Object.keys(schedules).map(handleSave));
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="skeleton h-8 w-48" />
        <div className="skeleton h-64 w-full" />
      </div>
    );
  }

  if (!profiles.length) {
    return (
      <div className="card p-8 text-center text-text-muted text-sm">
        No employees enrolled yet. Add employees first from the Employees page.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-text-primary">Schedules</h1>
          <p className="text-sm text-text-muted mt-0.5">Set weekly working hours for each employee.</p>
        </div>
        <button type="button" onClick={handleSaveAll} className="btn-primary text-sm">
          Save All
        </button>
      </div>

      {/* Grid */}
      <div className="card overflow-x-auto p-0">
        <table className="w-full min-w-[700px] text-sm">
          <thead>
            <tr className="border-b border-border bg-bg-elevated">
              <th className="px-4 py-3 text-left text-xs font-semibold text-text-muted w-40">Employee</th>
              {DAYS.map((d) => (
                <th key={d.key} className="px-1.5 py-3 text-center text-xs font-semibold text-text-muted w-24">
                  {d.label}
                </th>
              ))}
              <th className="px-3 py-3 text-center text-xs font-semibold text-text-muted w-28">Actions</th>
            </tr>
          </thead>
          <tbody>
            {profiles.map((profile) => {
              const id = (profile.id ?? profile.name).trim();
              const sched = schedules[id];
              if (!sched) return null;
              return (
                <tr key={id} className="border-b border-border/40 last:border-0 hover:bg-bg-elevated/40 transition-colors">
                  <td className="px-4 py-2 align-middle">
                    <span className="font-medium text-text-primary text-sm truncate block max-w-[140px]">
                      {profile.name}
                    </span>
                    <div className="flex gap-2 mt-1">
                      <button
                        type="button"
                        onClick={() => applyWeekdays(id)}
                        className="text-[10px] text-accent hover:underline"
                      >
                        M–F 9–5
                      </button>
                      <button
                        type="button"
                        onClick={() => clearEmployee(id)}
                        className="text-[10px] text-text-muted hover:text-danger hover:underline"
                      >
                        clear
                      </button>
                    </div>
                  </td>
                  {DAYS.map(({ key }) => (
                    <DayCell
                      key={key}
                      day={sched.days[key] ?? { working: false, start: null, end: null }}
                      onChange={(d) => setDay(id, key, d)}
                    />
                  ))}
                  <td className="px-3 py-2 text-center align-middle">
                    <button
                      type="button"
                      onClick={() => handleSave(id)}
                      disabled={saving[id]}
                      className="rounded-full border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs font-semibold text-accent hover:bg-accent/20 transition-colors disabled:opacity-50"
                    >
                      {saving[id] ? "…" : saved[id] ? "Saved ✓" : "Save"}
                    </button>
                    {errors[id] && <p className="mt-1 text-[10px] text-danger">{errors[id]}</p>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
