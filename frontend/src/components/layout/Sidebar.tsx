import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
  icon: React.ReactNode;
}

function DashIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <rect x="1" y="1" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
      <rect x="11" y="1" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
      <rect x="1" y="11" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
      <rect x="11" y="11" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}
function LogsIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <rect x="2" y="2" width="14" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <line x1="5" y1="6" x2="13" y2="6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="5" y1="9" x2="13" y2="9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="5" y1="12" x2="10" y2="12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
function UsersIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <circle cx="7" cy="6" r="3" stroke="currentColor" strokeWidth="1.5" />
      <path d="M1 16c0-3.314 2.686-5 6-5s6 1.686 6 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M13 8c1.657 0 3 1.343 3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="13" cy="5" r="2" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}
function AlertIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <path d="M9 2L16 15H2L9 2Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <line x1="9" y1="8" x2="9" y2="11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="9" cy="13" r="0.75" fill="currentColor" />
    </svg>
  );
}
function ScheduleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <rect x="1" y="3" width="16" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <line x1="1" y1="7" x2="17" y2="7" stroke="currentColor" strokeWidth="1.5" />
      <line x1="5" y1="1" x2="5" y2="5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="13" y1="1" x2="13" y2="5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="5" y1="11" x2="13" y2="11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
function SettingsIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <circle cx="9" cy="9" r="2.5" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="M9 1v2M9 15v2M1 9h2M15 9h2M2.636 2.636l1.414 1.414M13.95 13.95l1.414 1.414M2.636 15.364l1.414-1.414M13.95 4.05l1.414-1.414"
        stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
      />
    </svg>
  );
}
function KioskIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <rect x="3" y="1" width="12" height="16" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <line x1="9" y1="13" x2="9" y2="15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="9" cy="7" r="3" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

const LINKS: NavItem[] = [
  { to: "/",        label: "Dashboard",    end: true, icon: <DashIcon /> },
  { to: "/logs",    label: "Attendance",   icon: <LogsIcon /> },
  { to: "/profiles",  label: "Employees",  icon: <UsersIcon /> },
  { to: "/schedules", label: "Schedules",  icon: <ScheduleIcon /> },
  { to: "/alerts",    label: "Alerts",     icon: <AlertIcon /> },
  { to: "/settings",label: "Settings",     icon: <SettingsIcon /> },
];

export function Sidebar() {
  const [expanded, setExpanded] = useState(true);
  const navigate = useNavigate();

  return (
    <aside
      className={`hidden md:flex flex-col shrink-0 border-r border-border bg-bg-surface transition-all duration-200 ${expanded ? "w-[220px]" : "w-16"}`}
    >
      {/* Logo */}
      <div className={`flex h-14 items-center border-b border-border px-4 ${expanded ? "justify-between" : "justify-center"}`}>
        {expanded && (
          <div>
            <span className="text-lg font-bold text-accent tracking-tight">Auty</span>
          </div>
        )}
        <button
          onClick={() => setExpanded((v) => !v)}
          className="rounded p-1 text-text-muted hover:text-text-primary hover:bg-bg-elevated transition-colors"
          aria-label={expanded ? "Collapse sidebar" : "Expand sidebar"}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            {expanded ? (
              <path d="M10 4L6 8l4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            ) : (
              <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            )}
          </svg>
        </button>
      </div>

      {/* Nav */}
      <nav className="flex flex-1 flex-col gap-0.5 px-2 py-3">
        {LINKS.map(({ to, label, end, icon }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `relative flex items-center gap-3 rounded-btn px-3 py-2.5 text-sm font-medium transition-colors
              ${isActive ? "text-accent" : "text-text-secondary hover:bg-bg-elevated hover:text-text-primary"}
              ${!expanded ? "justify-center" : ""}`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <motion.span
                    layoutId="nav-pill"
                    className="absolute inset-0 rounded-btn border border-accent/30 bg-accent/10"
                    transition={{ type: "spring", stiffness: 380, damping: 30 }}
                  />
                )}
                <span className="relative shrink-0">{icon}</span>
                {expanded && <span className="relative">{label}</span>}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Kiosk launch */}
      <div className="px-2 pb-4">
        <button
          onClick={() => navigate("/kiosk")}
          className={`flex w-full items-center gap-3 rounded-btn border border-border px-3 py-2.5 text-sm font-medium text-text-secondary hover:border-accent/40 hover:text-accent hover:bg-bg-elevated transition-colors ${!expanded ? "justify-center" : ""}`}
        >
          <span className="shrink-0"><KioskIcon /></span>
          {expanded && <span>Open Kiosk</span>}
        </button>
      </div>
    </aside>
  );
}
