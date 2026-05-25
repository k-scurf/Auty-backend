import { motion } from "framer-motion";

const STATE_LABELS: Record<string, string> = {
  IDLE: "Ready",
  DETECTING: "Scanning",
  RECOGNIZED: "Employee Recognized",
  UNKNOWN: "Unrecognized Face",
  ALERT: "Attention Required",
  ENGAGED: "Active",
};

interface Props {
  fsmState: string;
}

export function StatusPills({ fsmState }: Props) {
  const label = STATE_LABELS[fsmState] ?? fsmState;
  return (
    <div className="flex flex-wrap gap-2">
      <motion.span
        key={fsmState}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        className="rounded-full border border-border bg-inset px-3 py-1 text-xs font-medium text-slate-300"
      >
        {label}
      </motion.span>
    </div>
  );
}
