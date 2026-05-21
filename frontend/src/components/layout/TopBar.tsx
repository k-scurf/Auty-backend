import { useEffect, useState } from "react";
import type { FrameSnapshot } from "../../types";
import type { HealthStatus } from "../../types";

interface Props {
  health: HealthStatus;
  frame: FrameSnapshot | null;
  wsConnected: boolean;
}

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-slate-400">
      <span
        className={`h-2 w-2 rounded-full ${ok ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]" : "bg-red-500"}`}
        title={label}
      />
      {label}
    </span>
  );
}

export function TopBar({ health, frame, wsConnected }: Props) {
  const [clock, setClock] = useState(() => new Date().toLocaleTimeString());

  useEffect(() => {
    const id = setInterval(() => setClock(new Date().toLocaleTimeString()), 1000);
    return () => clearInterval(id);
  }, []);

  const fps = frame?.fps ?? health.fps;

  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-panel/60 px-6 backdrop-blur">
      <div className="flex items-center gap-4">
        <StatusDot ok={health.camera_ok} label="Camera" />
        <StatusDot ok={health.db_loaded} label="Database" />
        <StatusDot ok={wsConnected} label="Live" />
        <span className="text-xs text-slate-500">
          {fps > 0 ? `${fps.toFixed(1)} FPS` : "— FPS"}
        </span>
      </div>
      <span className="font-mono text-sm text-slate-400">{clock}</span>
    </header>
  );
}
