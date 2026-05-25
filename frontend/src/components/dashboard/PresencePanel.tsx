import { GlassCard } from "../ui/GlassCard";
import type { PresenceSnapshot } from "../../types";

function formatTime(ts: number): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const h = Math.floor(m / 60);
  if (h > 0) return `${h}h ${m % 60}m`;
  return `${m}m`;
}

interface Props {
  presence?: PresenceSnapshot | null;
}

export function PresencePanel({ presence }: Props) {
  if (!presence) return null;

  const clockedIn = presence.in_office ?? [];
  const recent = presence.recent_activity ?? [];
  const totals = presence.today_totals ?? {};

  return (
    <GlassCard className="space-y-3">
      <h3 className="text-sm font-medium text-text-primary">Clocked In Now</h3>
      {clockedIn.length === 0 ? (
        <p className="text-xs text-text-muted">No employees clocked in</p>
      ) : (
        <ul className="space-y-2 text-xs">
          {clockedIn.map((p) => (
            <li
              key={p.name}
              className="rounded-lg bg-bg-elevated px-2 py-1.5"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-accent">{p.name}</span>
                <span className="text-accent/80">IN</span>
              </div>
              <p className="mt-0.5 text-text-muted">
                Since {formatTime(p.since_ts)}
                {totals[p.name] != null && totals[p.name] > 0 && (
                  <> · {formatDuration(totals[p.name])} today</>
                )}
              </p>
            </li>
          ))}
        </ul>
      )}

      <h3 className="text-sm font-medium text-text-primary">Today's Activity</h3>
      {recent.length === 0 ? (
        <p className="text-xs text-text-muted">No activity yet</p>
      ) : (
        <ul className="max-h-32 space-y-1 overflow-y-auto text-xs text-text-secondary">
          {recent.slice(0, 10).map((a, i) => (
            <li key={`${a.name}-${a.last_seen_ts}-${i}`}>
              {a.name} · {a.event === "CHECK_OUT" ? "clocked out" : "clocked in"} {formatTime(a.last_seen_ts)}
            </li>
          ))}
        </ul>
      )}
    </GlassCard>
  );
}
