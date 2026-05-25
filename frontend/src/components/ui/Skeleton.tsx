interface Props {
  className?: string;
}

export function Skeleton({ className = "h-4 w-full" }: Props) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}
