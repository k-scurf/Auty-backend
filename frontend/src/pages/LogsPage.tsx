import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { fetchAttendanceEvents, fetchAlerts } from "../services/api";
import { AttendanceBadge } from "../components/ui/AttendanceBadge";
import { EmployeeAvatar } from "../components/ui/EmployeeAvatar";
import type { AttendanceEvent, LogEntry } from "../types";

type Filter = "all" | "clock_in" | "clock_out" | "alert";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all",       label: "All" },
  { id: "clock_in",  label: "Clock In" },
  { id: "clock_out", label: "Clock Out" },
  { id: "alert",     label: "Alerts" },
];

// Unified row shape so both source types render the same way
interface Row {
  key: string;
  ts: number;
  kind: "clock_in" | "clock_out" | "alert";
  name?: string;
  confidence?: number;
  detail?: string;
  rawType: string;
}

function toRows(events: AttendanceEvent[], alerts: LogEntry[]): Row[] {
  const rows: Row[] = [];

  for (const ev of events) {
    rows.push({
      key: ev.id,
      ts: ev.timestamp_ts,
      kind: ev.event === "CLOCK_IN" ? "clock_in" : "clock_out",
      name: ev.name,
      confidence: ev.confidence,
      rawType: ev.event,
    });
  }

  for (let i = 0; i < alerts.length; i++) {
    const a = alerts[i];
    rows.push({
      key: `alert-${a.ts}-${i}`,
      ts: a.ts,
      kind: "alert",
      name: a.name,
      confidence: a.confidence,
      detail: a.detail,
      rawType: a.type,
    });
  }

  // Newest first
  rows.sort((a, b) => b.ts - a.ts);
  return rows;
}

type BadgeVariant = "clocked_in" | "complete" | "missing" | "late" | "ontime" | "neutral";
function getBadgeVariant(kind: Row["kind"]): BadgeVariant {
  if (kind === "clock_in")  return "clocked_in";
  if (kind === "clock_out") return "complete";
  return "missing";
}

function getBadgeLabel(row: Row): string {
  if (row.kind === "clock_in")  return "Clock In";
  if (row.kind === "clock_out") return "Clock Out";
  return row.rawType;
}

export function LogsPage() {
  const [events,  setEvents]  = useState<AttendanceEvent[]>([]);
  const [alerts,  setAlerts]  = useState<LogEntry[]>([]);
  const [filter,  setFilter]  = useState<Filter>("all");

  const load = () => {
    fetchAttendanceEvents().then((e) => setEvents(e as AttendanceEvent[])).catch(() => {});
    fetchAlerts().then(setAlerts).catch(() => {});
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  const display = useMemo(() => {
    const all = toRows(events, alerts);
    if (filter === "all") return all;
    return all.filter((r) => r.kind === filter);
  }, [events, alerts, filter]);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-text-primary">Attendance Log</h2>
        <span className="font-mono text-xs text-text-muted">{display.length} events</span>
      </div>

      {/* Filter bar */}
      <div className="flex gap-2 flex-wrap">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            onClick={() => setFilter(f.id)}
            className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors
              ${filter === f.id
                ? "border-accent bg-accent/15 text-accent"
                : "border-border text-text-secondary hover:border-accent/40 hover:text-text-primary"}`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        {display.length === 0 ? (
          <div className="py-12 text-center text-text-muted text-sm">No events to show</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left sticky top-0 bg-bg-surface z-10">
                  <th className="px-4 py-2.5 text-xs font-medium text-text-secondary">Time</th>
                  <th className="px-4 py-2.5 text-xs font-medium text-text-secondary">Type</th>
                  <th className="px-4 py-2.5 text-xs font-medium text-text-secondary">Employee</th>
                  <th className="px-4 py-2.5 text-xs font-medium text-text-secondary">Confidence</th>
                  <th className="px-4 py-2.5 text-xs font-medium text-text-secondary">Detail</th>
                </tr>
              </thead>
              <tbody>
                {display.map((row, i) => (
                  <tr
                    key={row.key}
                    className={`border-b border-border/50 ${i % 2 === 0 ? "bg-bg-surface" : "bg-bg-elevated/50"}`}
                  >
                    <td className="px-4 py-2.5 font-mono text-xs text-text-muted whitespace-nowrap">
                      {new Date(row.ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}
                    </td>
                    <td className="px-4 py-2.5">
                      <AttendanceBadge variant={getBadgeVariant(row.kind)} label={getBadgeLabel(row)} />
                    </td>
                    <td className="px-4 py-2.5">
                      {row.name ? (
                        <div className="flex items-center gap-2">
                          <EmployeeAvatar name={row.name} size="sm" />
                          <span className="text-xs font-medium text-text-primary">{row.name}</span>
                        </div>
                      ) : (
                        <span className="text-xs text-text-muted">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs text-text-secondary">
                      {row.confidence != null ? `${Math.round(row.confidence * 100)}%` : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-text-muted max-w-[200px] truncate">
                      {row.detail ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </motion.div>
  );
}
