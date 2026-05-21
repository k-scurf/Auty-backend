import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { useWebSocket } from "../../hooks/useWebSocket";
import { useSystemStatus } from "../../hooks/useSystemStatus";
import { FrameContext } from "../../context/FrameContext";

export function AppShell() {
  const { frame, connected, error } = useWebSocket();
  const health = useSystemStatus();

  return (
    <FrameContext.Provider value={{ frame, connected, error }}>
      <div className="flex min-h-screen bg-surface">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar health={health} frame={frame} wsConnected={connected} />
          {error && (
            <div className="border-b border-amber-500/30 bg-amber-500/10 px-6 py-2 text-sm text-amber-200">
              {error}
            </div>
          )}
          {!error && !connected && health.engine_ready === false && (
            <div className="border-b border-sky-500/30 bg-sky-500/10 px-6 py-2 text-sm text-sky-200">
              Loading vision models and camera — this can take up to a minute on first run.
            </div>
          )}
          <main className="flex-1 overflow-auto p-6">
            <Outlet />
          </main>
        </div>
      </div>
    </FrameContext.Provider>
  );
}
