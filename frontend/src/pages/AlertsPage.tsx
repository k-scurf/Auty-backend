import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { LogList } from "../components/logs/LogList";
import { fetchAlerts } from "../services/api";
import type { LogEntry } from "../types";

export function AlertsPage() {
  const [alerts, setAlerts] = useState<LogEntry[]>([]);

  useEffect(() => {
    const load = () => fetchAlerts().then(setAlerts).catch(() => {});
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, []);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <h2 className="mb-2 text-lg font-semibold text-slate-100">Alerts</h2>
      <p className="mb-4 text-sm text-slate-500">
        Unknown faces and security alert events this session.
      </p>
      <LogList entries={[...alerts].reverse()} />
    </motion.div>
  );
}
