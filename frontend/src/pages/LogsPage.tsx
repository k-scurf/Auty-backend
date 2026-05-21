import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { LogList } from "../components/logs/LogList";
import { fetchLogs } from "../services/api";
import type { LogEntry } from "../types";
import { useFrameContext } from "../context/FrameContext";

export function LogsPage() {
  const { frame } = useFrameContext();
  const [logs, setLogs] = useState<LogEntry[]>([]);

  useEffect(() => {
    fetchLogs().then(setLogs).catch(() => {});
    const id = setInterval(() => {
      fetchLogs().then(setLogs).catch(() => {});
    }, 3000);
    return () => clearInterval(id);
  }, []);

  const display =
    logs.length > 0 ? logs : [...(frame?.log_tail ?? [])].reverse();

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <h2 className="mb-4 text-lg font-semibold text-slate-100">
        Recognition log
      </h2>
      <LogList entries={display} />
    </motion.div>
  );
}
