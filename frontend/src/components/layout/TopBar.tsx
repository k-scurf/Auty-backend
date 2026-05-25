import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import type { HealthStatus } from "../../types";

interface Props {
  health: HealthStatus;
  wsConnected: boolean;
}

const DASHBOARD_TABS = [
  { id: "live",    label: "Live" },
  { id: "today",   label: "Today" },
  { id: "reports", label: "Reports" },
  { id: "export",  label: "Export" },
];

export function TopBar({ health, wsConnected }: Props) {
  const [clock, setClock] = useState(() => new Date().toLocaleTimeString());
  const location = useLocation();
  const isDashboard = location.pathname === "/";

  useEffect(() => {
    const id = setInterval(() => setClock(new Date().toLocaleTimeString()), 1000);
    return () => clearInterval(id);
  }, []);

  const activeTab = new URLSearchParams(location.search).get("tab");

  return (
    <header className="shrink-0 border-b border-border bg-bg-surface/80 backdrop-blur">
      {/* Main bar */}
      <div className="flex h-14 items-center justify-between px-6">
        {/* Left: wordmark + location */}
        <div className="flex items-center gap-3">
          <span className="text-base font-bold text-accent tracking-tight">Auty</span>
          <span className="hidden sm:block text-text-muted text-xs">|</span>
          <span className="hidden sm:block text-text-secondary text-xs font-mono">{clock}</span>
        </div>

        {/* Right: status + bell + avatar */}
        <div className="flex items-center gap-4">
          {/* System status dots (compact) */}
          <div className="hidden lg:flex items-center gap-3">
            <StatusDot ok={health.camera_ok} label="Camera" />
            <StatusDot ok={health.db_loaded} label="DB" />
            <StatusDot ok={wsConnected} label="Live" />
          </div>

          {/* Notification bell */}
          <button className="relative rounded-btn p-1.5 text-text-secondary hover:bg-bg-elevated hover:text-text-primary transition-colors" aria-label="Alerts">
            <BellIcon />
          </button>

          {/* Avatar / initials */}
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-bg text-xs font-bold select-none">
            M
          </div>
        </div>
      </div>

      {/* Dashboard tab underline nav */}
      {isDashboard && (
        <nav className="hidden md:flex items-end gap-0 px-6">
          {DASHBOARD_TABS.map((tab) => (
            <NavLink
              key={tab.id}
              to={`/?tab=${tab.id}`}
              className={({ isActive: _ }) => {
                const active = activeTab === tab.id || (tab.id === "live" && !activeTab);
                return `relative px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px
                  ${active
                    ? "border-accent text-accent"
                    : "border-transparent text-text-secondary hover:text-text-primary"
                  }`;
              }}
            >
              {tab.label}
            </NavLink>
          ))}
        </nav>
      )}
    </header>
  );
}

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-text-secondary">
      <span
        className={`h-2 w-2 rounded-full ${ok ? "bg-accent shadow-glow" : "bg-danger"}`}
        title={label}
      />
      {label}
    </span>
  );
}

function BellIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
      <path d="M9 1.5a5.5 5.5 0 0 0-5.5 5.5v3.5L2 12.5h14l-1.5-2V7A5.5 5.5 0 0 0 9 1.5Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M7 14a2 2 0 0 0 4 0" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}
