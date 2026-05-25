import { Outlet } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { BottomTabBar } from "./BottomTabBar";
import { AlertBanner } from "../ui/AlertBanner";
import { useWebSocket } from "../../hooks/useWebSocket";
import { useSystemStatus } from "../../hooks/useSystemStatus";
import { FrameContext } from "../../context/FrameContext";
import { queryClient } from "../../lib/queryClient";

export function AppShell() {
  const { frame, connected, error } = useWebSocket();
  const health = useSystemStatus();

  return (
    <QueryClientProvider client={queryClient}>
      <FrameContext.Provider value={{ frame, connected, error }}>
        <div className="flex min-h-screen bg-bg">
          <Sidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <TopBar health={health} wsConnected={connected} />

            {/* Alert banners */}
            {health.engine_ready === false && !connected && (
              <div className="px-4 pt-2">
                <AlertBanner
                  variant="info"
                  message="Loading vision models and camera — this can take up to a minute on first run."
                />
              </div>
            )}
            {health.engine_ready !== false && error && (
              <div className="px-4 pt-2">
                <AlertBanner variant="warning" message={error} />
              </div>
            )}

            <main className="flex-1 overflow-auto p-6 pb-20 md:pb-6">
              <Outlet />
            </main>
          </div>
          <BottomTabBar />
        </div>
      </FrameContext.Provider>
    </QueryClientProvider>
  );
}
