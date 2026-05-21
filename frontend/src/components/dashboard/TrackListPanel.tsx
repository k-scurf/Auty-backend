import { GlassCard } from "../ui/GlassCard";
import type { Track } from "../../types";

interface Props {
  tracks: Track[];
  debugMode?: boolean;
}

export function TrackListPanel({ tracks, debugMode }: Props) {
  if (tracks.length === 0) {
    return null;
  }

  return (
    <GlassCard className="space-y-2">
      <h3 className="text-sm font-medium text-slate-300">Tracks</h3>
      <ul className="max-h-48 space-y-2 overflow-y-auto text-xs">
        {tracks.map((t) => (
          <li
            key={t.id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-inset/50 px-2 py-1.5"
          >
            <span className="font-mono text-slate-400">T{t.id}</span>
            <span className={t.known ? "text-accent" : "text-amber-400"}>
              {t.name}
            </span>
            <span>{Math.round(t.confidence * 100)}%</span>
            {(debugMode || t.quality_score !== undefined) && (
              <>
                <span className="text-slate-500">Q {Math.round(t.quality_score ?? 0)}</span>
                <span className="text-slate-500">blur {Math.round(t.blur_score ?? 0)}</span>
                {t.distance != null && (
                  <span className="text-slate-500">d {t.distance.toFixed(2)}</span>
                )}
                {t.match_margin != null && t.match_margin > 0 && (
                  <span className="text-slate-500">m {t.match_margin.toFixed(2)}</span>
                )}
                <span className="text-slate-500">{t.lock_state}</span>
                {t.reject_reason && (
                  <span className="text-slate-500">{t.reject_reason}</span>
                )}
              </>
            )}
          </li>
        ))}
      </ul>
    </GlassCard>
  );
}
