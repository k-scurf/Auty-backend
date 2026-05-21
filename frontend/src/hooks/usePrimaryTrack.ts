import { useMemo } from "react";
import type { FrameSnapshot, Track } from "../types";

export function usePrimaryTrack(frame: FrameSnapshot | null): Track | null {
  return useMemo(() => {
    if (!frame?.tracks?.length) return null;
    const pid = frame.primary_track_id;
    if (pid != null) {
      const found = frame.tracks.find((t) => t.id === pid);
      if (found) return found;
    }
    return frame.tracks[0] ?? null;
  }, [frame]);
}
