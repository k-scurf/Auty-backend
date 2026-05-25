import { Badge } from "../ui/Badge";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import type { Track } from "../../types";
import { profilePhotoUrl } from "../../services/api";

interface Props {
  track: Track | null;
  statusLine: string;
}

export function ProfileCard({ track, statusLine }: Props) {
  if (!track) {
    return (
      <GlassCard className="flex flex-col gap-3">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-40 w-full rounded-lg" />
        <Skeleton className="h-4 w-full" />
      </GlassCard>
    );
  }

  const known = track.known;
  const photo =
    known && track.name !== "UNKNOWN"
      ? profilePhotoUrl(track.name)
      : null;

  return (
    <GlassCard
      className={`flex flex-col gap-4 ${!known ? "shadow-glow-warm border-amber-500/30" : ""}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">
            {known ? track.name : "Unrecognized face"}
          </h2>
          <p className="text-xs text-slate-400">{statusLine}</p>
        </div>
        <Badge
          label={known ? "KNOWN" : "UNKNOWN"}
          variant={known ? "known" : "unknown"}
        />
      </div>

      <div className="flex justify-center">
        {photo ? (
          <img
            src={photo}
            alt={track.name}
            className="h-36 w-36 rounded-xl border border-border object-cover"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        ) : (
          <div className="flex h-36 w-36 items-center justify-center rounded-xl border border-dashed border-border bg-inset text-4xl text-slate-600">
            ?
          </div>
        )}
      </div>

      {known && (
        <div>
          <div className="mb-1 flex justify-between text-xs text-slate-400">
            <span>Confidence</span>
            <span>{Math.round(track.confidence * 100)}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-inset">
            <div
              className="h-full rounded-full bg-accent transition-all duration-300"
              style={{ width: `${Math.min(100, track.confidence * 100)}%` }}
            />
          </div>
        </div>
      )}

      <p className="text-xs text-slate-500">Stability {track.stability_pct}%</p>
    </GlassCard>
  );
}
