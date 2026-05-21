import { motion } from "framer-motion";

interface Props {
  fsmState: string;
  mood: string;
}

export function StatusPills({ fsmState, mood }: Props) {
  return (
    <div className="flex flex-wrap gap-2">
      <motion.span
        key={fsmState}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        className="rounded-full border border-border bg-inset px-3 py-1 text-xs font-medium text-slate-300"
      >
        {fsmState}
      </motion.span>
      <span className="rounded-full border border-accent/30 bg-accent/10 px-3 py-1 text-xs font-medium text-accent">
        {mood}
      </span>
    </div>
  );
}
