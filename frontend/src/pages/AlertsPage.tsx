import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { fetchAlerts } from "../services/api";
import { AlertBanner } from "../components/ui/AlertBanner";
import { TimeDisplay } from "../components/ui/TimeDisplay";
import { EmployeeAvatar } from "../components/ui/EmployeeAvatar";
import type { LogEntry } from "../types";

type GroupType = "fail_streak" | "missing_checkout" | "late" | "unknown" | "other";

function classifyAlert(e: LogEntry): GroupType {
  const t = e.type?.toLowerCase() ?? "";
  if (t.includes("fail_streak") || t.includes("streak")) return "fail_streak";
  if (t.includes("missing") || t.includes("checkout")) return "missing_checkout";
  if (t.includes("late")) return "late";
  if (t.includes("unknown")) return "unknown";
  return "other";
}

const GROUP_META: Record<GroupType, { label: string; variant: "danger" | "warning" | "info" }> = {
  fail_streak:      { label: "Fail Streaks",          variant: "danger" },
  missing_checkout: { label: "Missing Clock-outs",    variant: "warning" },
  late:             { label: "Late Arrivals",          variant: "warning" },
  unknown:          { label: "Unrecognized Faces",     variant: "danger" },
  other:            { label: "Other Alerts",           variant: "info" },
};

const GROUP_ORDER: GroupType[] = ["fail_streak", "unknown", "missing_checkout", "late", "other"];

export function AlertsPage() {
  const [alerts, setAlerts] = useState<LogEntry[]>([]);

  useEffect(() => {
    const load = () => fetchAlerts().then((d) => setAlerts([...d].reverse())).catch(() => {});
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, []);

  const grouped = useMemo(() => {
    const acc: Partial<Record<GroupType, LogEntry[]>> = {};
    for (const e of alerts) {
      const g = classifyAlert(e);
      if (!acc[g]) acc[g] = [];
      acc[g]!.push(e);
    }
    return acc;
  }, [alerts]);

  const hasAny = alerts.length > 0;

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-text-primary">Attendance Alerts</h2>
        <p className="text-sm text-text-muted mt-0.5">Unrecognized face attempts and attendance alert events this session.</p>
      </div>

      {!hasAny && (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <div className="text-4xl">✅</div>
          <div className="font-semibold text-text-primary">No alerts</div>
          <div className="text-sm text-text-muted">All attendance events are within normal parameters.</div>
        </div>
      )}

      {GROUP_ORDER.map((g) => {
        const entries = grouped[g];
        if (!entries?.length) return null;
        const meta = GROUP_META[g];
        return (
          <div key={g} className="space-y-2">
            <AlertBanner
              variant={meta.variant}
              message={`${meta.label} — ${entries.length} event${entries.length !== 1 ? "s" : ""}`}
            />
            <div className="card divide-y divide-border/50 overflow-hidden">
              {entries.map((e, i) => (
                <div key={`${e.ts}-${e.type}-${i}`} className="flex items-center gap-3 px-4 py-3">
                  {e.name ? (
                    <EmployeeAvatar name={e.name} size="sm" status="alert" />
                  ) : (
                    <div className="h-6 w-6 rounded-full bg-danger/20 flex items-center justify-center text-danger text-xs">!</div>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium text-text-primary">{e.name ?? "Unknown"}</div>
                    {e.detail && <div className="text-[10px] text-text-muted mt-0.5 truncate">{e.detail}</div>}
                  </div>
                  <TimeDisplay ts={e.ts * 1000} variant="time" className="text-xs" />
                  {e.confidence != null && (
                    <span className="font-mono text-xs text-text-muted">{Math.round(e.confidence * 100)}%</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </motion.div>
  );
}
