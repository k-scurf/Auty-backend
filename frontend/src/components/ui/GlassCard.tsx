import type { ReactNode, HTMLAttributes } from "react";

interface Props extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  elevated?: boolean;
}

export function GlassCard({ children, className = "", elevated = false, ...props }: Props) {
  return (
    <div
      className={`card p-4 ${elevated ? "shadow-elevated bg-bg-elevated" : ""} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
