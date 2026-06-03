import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { EnrollModal } from "../components/dashboard/EnrollModal";
import { EnrollmentWizard } from "../components/dashboard/EnrollmentWizard";
import { ExportPanel } from "../components/dashboard/ExportPanel";
import { AttendanceStatusBadge } from "../components/dashboard/AttendanceStatusBadge";
import { ScheduleEditor } from "../components/dashboard/ScheduleEditor";
import { EmployeeAvatar } from "../components/ui/EmployeeAvatar";
import { StatCard } from "../components/ui/StatCard";
import { TimeDisplay } from "../components/ui/TimeDisplay";
import { AlertBanner } from "../components/ui/AlertBanner";
import { Skeleton } from "../components/ui/Skeleton";
import { useFrameContext } from "../context/FrameContext";
import { useSystemStatus } from "../hooks/useSystemStatus";
import {
  fetchSettings,
  fetchAttendanceActive,
  fetchAttendanceEvents,
  fetchTodayAttendanceStatus,
} from "../services/api";
import type { AttendanceEvent } from "../types";
import type { AttendanceStatus, TodayAttendanceStatus, TodayAttendanceRow } from "../types";

type Tab = "live" | "today" | "reports" | "export";

function fmtTime(ts: number) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
function fmtDuration(s: number) {
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  return h > 0 ? `${h}h ${m % 60}m` : `${m}m`;
}

// ── Mobile tab segment control (shown inside page on mobile) ──────────────────
function MobileTabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  const tabs: { id: Tab; label: string }[] = [
    { id: "live",    label: "Live" },
    { id: "today",   label: "Today" },
    { id: "reports", label: "Reports" },
    { id: "export",  label: "Export" },
  ];
  return (
    <div className="flex md:hidden gap-1 rounded-lg border border-border bg-bg-surface p-1 w-full mb-4">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={`flex-1 rounded-md py-1.5 text-xs font-medium transition-colors ${
            active === t.id ? "bg-accent/20 text-accent" : "text-text-secondary hover:text-text-primary"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ── Live Tab ─────────────────────────────────────────────────────────────────
function LiveTab({
  attendance,
  engineReady,
}: {
  attendance: AttendanceStatus | null;
  engineReady: boolean;
}) {
  const { frame } = useFrameContext();
  const [enrollDismissed, setEnrollDismissed] = useState(false);
  const [guidedEnroll, setGuidedEnroll] = useState(true);

  useEffect(() => {
    if (!engineReady) return;
    fetchSettings()
      .then((s) => setGuidedEnroll(s.guided_enrollment_enabled !== false))
      .catch(() => {});
  }, [engineReady]);

  const enrollment = frame?.enrollment;
  const progress = frame?.enrollment_progress;
  const legacyReady = Boolean(enrollment?.ready) && Boolean(enrollment?.image_b64);
  const guidedCapturing = Boolean(progress?.active);
  const guidedReady = Boolean(progress?.ready_to_save);
  const autoCommitted = Boolean(progress?.auto_committed);

  const showLegacyModal = !guidedEnroll && legacyReady && !enrollDismissed;
  const showWizard = guidedEnroll && !enrollDismissed &&
    (guidedCapturing || guidedReady || autoCommitted || legacyReady);

  useEffect(() => {
    if (guidedCapturing || guidedReady || legacyReady) setEnrollDismissed(false);
  }, [guidedCapturing, guidedReady, legacyReady]);

  const alerts = attendance?.alerts ?? [];

  return (
    <div className="space-y-4">
      {/* Alert banners */}
      {alerts.map((a, i) => (
        <AlertBanner key={i} variant="warning" message={`${a.name} — ${a.detail}`} />
      ))}

      {/* Last event */}
      {attendance && attendance.recent_events.length > 0 && (() => {
        const ev = attendance.recent_events[0];
        return (
          <div className="card flex items-center gap-3 p-3">
            <EmployeeAvatar name={ev.name} size="lg" status={ev.event === "CLOCK_IN" ? "in" : "out"} />
            <div>
              <div className="font-semibold text-text-primary text-sm">{ev.name}</div>
              <div className="text-xs text-text-secondary">
                {ev.event === "CLOCK_IN" ? "Clocked in" : "Clocked out"} at{" "}
                <TimeDisplay ts={ev.timestamp_ts * 1000} variant="time" />
              </div>
            </div>
          </div>
        );
      })()}

      {/* Who's in now */}
      <div className="card p-4 space-y-3">
        <h3 className="text-sm font-semibold text-text-primary">Who's In Now</h3>
        {!attendance ? (
          <div className="space-y-2">
            <Skeleton className="h-8" />
            <Skeleton className="h-8" />
            <Skeleton className="h-8" />
          </div>
        ) : attendance.clocked_in.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-6 text-center">
            <div className="text-2xl">🏢</div>
            <p className="text-xs text-text-muted">No one clocked in yet</p>
          </div>
        ) : (
          <ul className="space-y-1">
            {attendance.clocked_in.map((e) => (
              <li
                key={e.employee_id}
                className="flex items-center gap-2.5 rounded-md border-l-[3px] border-accent bg-bg-elevated px-3 py-2"
              >
                <EmployeeAvatar name={e.name} size="sm" status="in" />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium text-text-primary truncate">{e.name}</div>
                  <div className="text-[10px] text-text-muted">In since {fmtTime(e.clock_in_ts)}</div>
                </div>
                <span className="font-mono text-[10px] text-accent">{fmtDuration(e.duration_seconds)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Enrollment modals */}
      <EnrollModal
        open={showLegacyModal}
        imageB64={enrollment?.image_b64}
        onClose={() => setEnrollDismissed(true)}
      />
      {showWizard && (
        <EnrollmentWizard
          progress={progress}
          legacyImageB64={enrollment?.image_b64}
          onDone={() => setEnrollDismissed(true)}
        />
      )}
    </div>
  );
}

// ── Today Tab ────────────────────────────────────────────────────────────────
function shiftLabel(row: TodayAttendanceRow) {
  if (!row.has_schedule) return "—";
  if (row.day_off) return "Day off";
  if (row.shift_start && row.shift_end) return `${row.shift_start} – ${row.shift_end}`;
  return "—";
}

function TodayTab({
  todayStatus,
  onScheduleSaved,
}: {
  todayStatus: TodayAttendanceStatus | null;
  onScheduleSaved: () => void;
}) {
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null);

  if (!todayStatus) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-28" />)}
        </div>
        <Skeleton className="h-64" />
      </div>
    );
  }

  const rows = todayStatus.rows;
  const clockIns = rows.filter((row) => row.clock_in_ts != null).length;
  const completed = rows.filter((row) => row.status === "complete").length;
  const stillIn = rows.filter((row) => row.clock_in_ts != null && row.clock_out_ts == null).length;
  const alerts = rows.filter((row) => row.alert);

  return (
    <div className="space-y-6">
      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard value={clockIns}  label="Clock Ins"    color="#00D4AA" />
        <StatCard value={completed} label="Complete"     color="#8BA3BB" />
        <StatCard value={stillIn}   label="Still In"     color="#3B9EFF" />
        <StatCard value={alerts.length} label="Alerts" color="#FFB020" />
      </div>

      {/* Alerts */}
      {alerts.map((row) => (
        <AlertBanner key={`${row.employee_id}-${row.status}`} variant="warning" message={row.alert ?? ""} />
      ))}

      {editing && (
        <ScheduleEditor
          employeeId={editing.id}
          employeeName={editing.name}
          onSaved={onScheduleSaved}
          onClose={() => setEditing(null)}
        />
      )}

      {/* Activity table */}
      <div className="card overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <h3 className="text-sm font-semibold text-text-primary">Today's Attendance</h3>
          <span className="font-mono text-[10px] text-text-muted">{todayStatus.date}</span>
        </div>
        {rows.length === 0 ? (
          <div className="py-12 text-center text-text-muted text-sm">No employees to show</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left">
                  <th className="px-4 py-2.5 text-xs font-medium text-text-secondary">Employee</th>
                  <th className="px-4 py-2.5 text-xs font-medium text-text-secondary">Shift</th>
                  <th className="px-4 py-2.5 text-xs font-medium text-text-secondary">Clock In</th>
                  <th className="px-4 py-2.5 text-xs font-medium text-text-secondary">Clock Out</th>
                  <th className="px-4 py-2.5 text-xs font-medium text-text-secondary">Hours</th>
                  <th className="px-4 py-2.5 text-xs font-medium text-text-secondary">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr
                    key={row.employee_id}
                    className={`border-b border-border/50 ${i % 2 === 0 ? "bg-bg-surface" : "bg-bg-elevated/50"}`}
                  >
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2.5">
                        <EmployeeAvatar
                          name={row.name}
                          size="sm"
                          status={row.clock_in_ts && !row.clock_out_ts ? "in" : "out"}
                        />
                        <span className="font-medium text-text-primary text-xs">{row.name}</span>
                        {row.status === "no_schedule" && (
                          <button
                            type="button"
                            onClick={() => setEditing({ id: row.employee_id, name: row.name })}
                            className="rounded p-1 text-text-muted hover:bg-bg-elevated hover:text-accent"
                            title="Edit schedule"
                          >
                            <svg width="14" height="14" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                              <rect x="3" y="4" width="14" height="13" rx="2" stroke="currentColor" strokeWidth="1.6" />
                              <path d="M6 2.5v3M14 2.5v3M3 8h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                            </svg>
                          </button>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-text-secondary">{shiftLabel(row)}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-text-secondary">
                      {row.clock_in_time ?? "—"}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs">
                      {row.clock_out_time ? (
                        <span className="text-text-secondary">{row.clock_out_time}</span>
                      ) : row.clock_in_ts ? (
                        <span className="text-warning">Still in</span>
                      ) : (
                        <span className="text-text-muted">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-text-secondary">
                      {row.hours != null ? `${row.hours.toFixed(1)}h` : "—"}
                    </td>
                    <td className="px-4 py-2.5">
                      <AttendanceStatusBadge status={row.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Reports Tab ──────────────────────────────────────────────────────────────
// ---------------------------------------------------------------------------
// ReportsTab helpers
// ---------------------------------------------------------------------------

function toDateStr(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function todayDateStr(): string {
  return toDateStr(new Date());
}

/** Most-recent (or current) occurrence of dayOfWeek (0=Sun…6=Sat). */
function mostRecentWeekday(dow: number): Date {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - ((d.getDay() - dow + 7) % 7));
  return d;
}

/** Pair raw CLOCK_IN / CLOCK_OUT events into completed shifts per employee. */
function pairShifts(events: AttendanceEvent[]) {
  const byEmployee: Record<string, { name: string; evs: AttendanceEvent[] }> = {};
  for (const ev of events) {
    const key = ev.employee_id || ev.name;
    if (!byEmployee[key]) byEmployee[key] = { name: ev.name, evs: [] };
    byEmployee[key].evs.push(ev);
  }
  return Object.values(byEmployee).map(({ name, evs }) => {
    const sorted = [...evs].sort((a, b) => a.timestamp_ts - b.timestamp_ts);
    let hours = 0;
    const days = new Set<string>();
    let pendingIn: AttendanceEvent | null = null;
    for (const ev of sorted) {
      if (ev.event === "CLOCK_IN" && pendingIn === null) {
        pendingIn = ev;
      } else if (ev.event === "CLOCK_OUT" && pendingIn !== null) {
        hours += (ev.timestamp_ts - pendingIn.timestamp_ts) / 3600;
        days.add(new Date(pendingIn.timestamp_ts * 1000).toDateString());
        pendingIn = null;
      }
    }
    return { name, hours, days: days.size };
  });
}

// ---------------------------------------------------------------------------
// ReportsTab
// ---------------------------------------------------------------------------

function ReportsTab() {
  type RangeId = "period" | "lastperiod" | "month";
  const [range, setRange] = useState<RangeId>("period");
  const [payPeriodStartDay, setPayPeriodStartDay] = useState(1); // Monday default
  const [employees, setEmployees] = useState<{ name: string; hours: number; days: number }[]>([]);
  const [loading, setLoading] = useState(false);
  const [rangeLabel, setRangeLabel] = useState("");

  // Load pay_period_start_day from settings once.
  useEffect(() => {
    fetchSettings()
      .then((s) => setPayPeriodStartDay(Number(s.pay_period_start_day ?? 1)))
      .catch(() => {});
  }, []);

  // Build the date range whenever the range selector or payPeriodStartDay changes.
  const { startDate, endDate } = useMemo(() => {
    const today = todayDateStr();
    const periodStart = mostRecentWeekday(payPeriodStartDay);
    switch (range) {
      case "period": {
        const start = toDateStr(periodStart);
        setRangeLabel(`${start} – ${today}`);
        return { startDate: start, endDate: today };
      }
      case "lastperiod": {
        const end = new Date(periodStart);
        end.setDate(end.getDate() - 1);
        const start = new Date(periodStart);
        start.setDate(start.getDate() - 7);
        const s = toDateStr(start);
        const e = toDateStr(end);
        setRangeLabel(`${s} – ${e}`);
        return { startDate: s, endDate: e };
      }
      case "month": {
        const d = new Date();
        const start = toDateStr(new Date(d.getFullYear(), d.getMonth(), 1));
        setRangeLabel(`${start} – ${today}`);
        return { startDate: start, endDate: today };
      }
    }
  }, [range, payPeriodStartDay]);

  // Fetch and pair events whenever the date range changes.
  useEffect(() => {
    if (!startDate || !endDate) return;
    setLoading(true);
    fetchAttendanceEvents({ start_date: startDate, end_date: endDate })
      .then((evs) => setEmployees(pairShifts(evs).sort((a, b) => b.hours - a.hours)))
      .catch(() => setEmployees([]))
      .finally(() => setLoading(false));
  }, [startDate, endDate]);

  const ranges: { id: RangeId; label: string }[] = [
    { id: "period",     label: "This Pay Period" },
    { id: "lastperiod", label: "Last Pay Period"  },
    { id: "month",      label: "This Month"       },
  ];

  return (
    <div className="space-y-6">
      {/* Range pills */}
      <div className="flex gap-2 flex-wrap">
        {ranges.map((r) => (
          <button
            key={r.id}
            onClick={() => setRange(r.id)}
            className={`rounded-full border px-4 py-1.5 text-sm font-medium transition-colors ${
              range === r.id
                ? "border-accent bg-accent/15 text-accent"
                : "border-border text-text-secondary hover:border-accent/40 hover:text-text-primary"
            }`}
          >
            {r.label}
          </button>
        ))}
      </div>

      {/* Summary table */}
      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text-primary">Employee Summary</h3>
          {rangeLabel && (
            <span className="font-mono text-[10px] text-text-muted">{rangeLabel}</span>
          )}
        </div>
        {loading ? (
          <div className="space-y-2 p-4">
            <div className="skeleton h-8" />
            <div className="skeleton h-8" />
            <div className="skeleton h-8" />
          </div>
        ) : employees.length === 0 ? (
          <div className="py-12 text-center text-text-muted text-sm">No completed shifts for this period</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left">
                  <th className="px-4 py-2.5 text-xs font-medium text-text-secondary">Employee</th>
                  <th className="px-4 py-2.5 text-xs font-medium text-text-secondary">Total Hrs</th>
                  <th className="px-4 py-2.5 text-xs font-medium text-text-secondary">Days Present</th>
                </tr>
              </thead>
              <tbody>
                {employees.map((e, i) => (
                  <tr key={i} className={`border-b border-border/50 ${i % 2 === 0 ? "" : "bg-bg-elevated/50"}`}>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <EmployeeAvatar name={e.name} size="sm" />
                        <span className="font-medium text-text-primary text-xs">{e.name}</span>
                      </div>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-accent">{e.hours.toFixed(1)}h</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-text-secondary">{e.days}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Bar chart — CSS only, one bar per employee */}
      {employees.length > 0 && !loading && (
        <div className="card p-4 space-y-3">
          <h3 className="text-sm font-semibold text-text-primary">Hours This Period</h3>
          {(() => {
            const max = Math.max(...employees.map((e) => e.hours), 1);
            return employees.map((e, i) => (
              <div key={i} className="flex items-center gap-3 text-xs">
                <div className="w-20 shrink-0 truncate text-text-secondary">{e.name.split(" ")[0]}</div>
                <div className="flex-1 h-5 bg-bg-elevated rounded overflow-hidden">
                  <div
                    className="h-full bg-accent/60 rounded transition-all duration-500"
                    style={{ width: `${(e.hours / max) * 100}%` }}
                  />
                </div>
                <div className="w-10 text-right font-mono text-text-muted">{e.hours.toFixed(1)}h</div>
              </div>
            ));
          })()}
        </div>
      )}
    </div>
  );
}

// ── Main DashboardPage ────────────────────────────────────────────────────────
export function DashboardPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { frame } = useFrameContext();
  const rawTab = searchParams.get("tab");
  const activeTab: Tab = (["live", "today", "reports", "export"].includes(rawTab ?? "")
    ? rawTab
    : "live") as Tab;

  const setTab = (t: Tab) => setSearchParams({ tab: t }, { replace: true });

  const health = useSystemStatus();
  const engineReady = health.engine_ready === true;
  const [attendance, setAttendance] = useState<AttendanceStatus | null>(null);
  const [todayStatus, setTodayStatus] = useState<TodayAttendanceStatus | null>(null);
  const lastAttendanceEventKey = useRef("");

  const loadTodayStatus = useCallback(() => {
    return fetchTodayAttendanceStatus().then(setTodayStatus).catch(() => {});
  }, []);

  useEffect(() => {
    if (!engineReady) return;
    const load = () => fetchAttendanceActive().then(setAttendance).catch(() => {});
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [engineReady]);

  useEffect(() => {
    if (!engineReady) return;
    loadTodayStatus();
    const id = setInterval(loadTodayStatus, 60000);
    return () => clearInterval(id);
  }, [engineReady, loadTodayStatus]);

  useEffect(() => {
    const latest = frame?.recent_attendance?.[0];
    if (!latest) return;
    const key = `${latest.id}:${latest.event}:${latest.timestamp_ts}`;
    if (key === lastAttendanceEventKey.current) return;
    lastAttendanceEventKey.current = key;
    loadTodayStatus();
  }, [frame?.recent_attendance, loadTodayStatus]);

  return (
    <div className="space-y-0">
      {/* Mobile segment tabs */}
      <MobileTabBar active={activeTab} onChange={setTab} />

      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.15 }}
        >
          {activeTab === "live"    && <LiveTab attendance={attendance} engineReady={engineReady} />}
          {activeTab === "today"   && <TodayTab todayStatus={todayStatus} onScheduleSaved={loadTodayStatus} />}
          {activeTab === "reports" && <ReportsTab />}
          {activeTab === "export"  && <ExportPanel />}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
