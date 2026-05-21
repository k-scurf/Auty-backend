interface Props {
  className?: string;
}

export function Skeleton({ className = "h-4 w-full" }: Props) {
  return (
    <div
      className={`animate-pulse rounded-md bg-slate-700/50 ${className}`}
      aria-hidden
    />
  );
}
