import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { LogsPage } from "./pages/LogsPage";
import { ProfilesPage } from "./pages/ProfilesPage";
import { AlertsPage } from "./pages/AlertsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { DebugPage } from "./pages/DebugPage";
import { KioskPage } from "./pages/KioskPage";
import { SchedulePage } from "./pages/SchedulePage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Kiosk runs full-screen — no AppShell chrome */}
        <Route path="kiosk" element={<KioskPage />} />

        <Route element={<AppShell />}>
          <Route index element={<DashboardPage />} />
          <Route path="logs" element={<LogsPage />} />
          <Route path="profiles" element={<ProfilesPage />} />
          <Route path="schedules" element={<SchedulePage />} />
          <Route path="alerts" element={<AlertsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="debug" element={<DebugPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
