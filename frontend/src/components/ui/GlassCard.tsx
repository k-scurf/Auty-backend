import type { ReactNode } from "react";

interface Props {
  children: ReactNode;
  className?: string;
}

export function GlassCard({ children, className = "" }: Props) {
  return (
    <div className={`glass-card p-4 ${className}`.trim()}>{children}</div>
  );
}
