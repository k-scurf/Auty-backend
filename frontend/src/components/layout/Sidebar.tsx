import { NavLink } from "react-router-dom";
import { motion } from "framer-motion";

const links = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/logs", label: "Logs" },
  { to: "/profiles", label: "Profiles" },
  { to: "/alerts", label: "Alerts" },
  { to: "/settings", label: "Settings" },
  { to: "/debug", label: "Debug" },
];

export function Sidebar() {
  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-panel/80 px-3 py-6">
      <div className="mb-8 px-2">
        <h1 className="text-xl font-bold tracking-tight text-accent">Auty</h1>
        <p className="text-xs text-slate-400">Face recognition</p>
      </div>
      <nav className="flex flex-1 flex-col gap-1">
        {links.map(({ to, label, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `relative rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                isActive
                  ? "text-accent"
                  : "text-slate-400 hover:bg-inset hover:text-slate-200"
              }`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <motion.span
                    layoutId="nav-pill"
                    className="absolute inset-0 rounded-lg border border-accent/30 bg-accent/10"
                    transition={{ type: "spring", stiffness: 380, damping: 30 }}
                  />
                )}
                <span className="relative">{label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
