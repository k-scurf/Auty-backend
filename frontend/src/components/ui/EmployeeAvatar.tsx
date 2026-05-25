import { useState } from "react";

const PALETTE = [
  "#00D4AA", "#3B9EFF", "#FF5B5B", "#FFB020",
  "#A78BFA", "#34D399", "#F472B6", "#FB923C",
];

function hashName(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = (h * 31 + name.charCodeAt(i)) & 0xffffffff;
  }
  return Math.abs(h);
}

const SIZES = {
  sm: { outer: "h-6 w-6", text: "text-[9px]", dot: "h-1.5 w-1.5 -bottom-0.5 -right-0.5" },
  md: { outer: "h-8 w-8", text: "text-[11px]", dot: "h-2 w-2 -bottom-0.5 -right-0.5" },
  lg: { outer: "h-12 w-12", text: "text-base", dot: "h-2.5 w-2.5 bottom-0 right-0" },
  xl: { outer: "h-16 w-16", text: "text-xl", dot: "h-3 w-3 bottom-0.5 right-0.5" },
};

const STATUS_COLORS = {
  in:    "bg-accent",
  out:   "bg-text-muted",
  alert: "bg-danger",
};

interface Props {
  name: string;
  photo?: string;
  size?: "sm" | "md" | "lg" | "xl";
  status?: "in" | "out" | "alert";
}

export function EmployeeAvatar({ name, photo, size = "md", status }: Props) {
  const [imgError, setImgError] = useState(false);
  const sz = SIZES[size];
  const initials = name
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
  const color = PALETTE[hashName(name) % PALETTE.length];

  return (
    <div className={`relative inline-flex shrink-0 ${sz.outer}`}>
      {photo && !imgError ? (
        <img
          src={photo}
          alt={name}
          className="h-full w-full rounded-full object-cover"
          onError={() => setImgError(true)}
        />
      ) : (
        <div
          className={`h-full w-full rounded-full flex items-center justify-center font-semibold text-bg ${sz.text}`}
          style={{ backgroundColor: color }}
        >
          {initials || "?"}
        </div>
      )}
      {status && (
        <span
          className={`absolute border-2 border-bg-surface rounded-full ${sz.dot} ${STATUS_COLORS[status]}`}
        />
      )}
    </div>
  );
}
