import { AnimatePresence, motion } from "framer-motion";
import type { LogEntry } from "../../types";

function formatTime(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString();
}

function variant(type: string) {
  if (type === "KNOWN") return "text-accent";
  if (type === "UNKNOWN") return "text-amber-300";
  if (type === "ALERT") return "text-red-300";
  if (type === "ENROLLED") return "text-emerald-300";
  return "text-slate-300";
}

interface Props {
  entries: LogEntry[];
}

export function LogList({ entries }: Props) {
  return (
    <ul className="space-y-2">
      <AnimatePresence initial={false}>
        {entries.map((e, i) => (
          <motion.li
            key={`${e.ts}-${e.type}-${e.name ?? e.track_id ?? i}`}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0 }}
            className="flex items-center gap-3 rounded-lg border border-border/60 bg-inset/50 px-4 py-3 text-sm"
          >
            <span className="font-mono text-xs text-slate-500">
              {formatTime(e.ts)}
            </span>
            <span className={`font-semibold ${variant(e.type)}`}>{e.type}</span>
            {e.name && <span className="text-slate-200">{e.name}</span>}
            {e.confidence != null && (
              <span className="text-slate-500">
                {Math.round(e.confidence * 100)}%
              </span>
            )}
            {e.detail && (
              <span className="text-slate-500 truncate">{e.detail}</span>
            )}
          </motion.li>
        ))}
      </AnimatePresence>
      {entries.length === 0 && (
        <p className="text-center text-sm text-slate-500">No events yet.</p>
      )}
    </ul>
  );
}
