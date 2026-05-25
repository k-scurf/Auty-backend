import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { fetchSettings, patchSettings, fetchAuditLog, resetAllProfiles } from "../services/api";
import type { AuditEntry } from "../services/api";

type Section = "general" | "recognition" | "kiosk" | "payroll" | "privacy" | "audit";

const SECTIONS: { id: Section; label: string; icon: string }[] = [
  { id: "general",     label: "General",         icon: "⚙" },
  { id: "recognition", label: "Recognition",      icon: "👁" },
  { id: "kiosk",       label: "Kiosk",            icon: "📟" },
  { id: "payroll",     label: "Payroll",          icon: "💳" },
  { id: "privacy",     label: "Data & Privacy",   icon: "🛡" },
  { id: "audit",       label: "Audit Log",        icon: "📋" },
];

const RETENTION_OPTIONS = [
  { value: "30",  label: "30 days" },
  { value: "90",  label: "90 days" },
  { value: "180", label: "180 days" },
  { value: "365", label: "1 year" },
];

const PAY_PERIOD_DAYS = [
  { value: "0", label: "Sunday" },
  { value: "1", label: "Monday" },
  { value: "5", label: "Friday" },
];

const EXPORT_FORMATS = [
  { value: "gusto",  label: "Gusto" },
  { value: "adp",    label: "ADP Run" },
  { value: "square", label: "Square Payroll" },
];

function ToggleRow({ label, description, checked, onChange }: {
  label: string; description?: string; checked: boolean; onChange: () => void;
}) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4">
      <div>
        <div className="text-sm font-medium text-text-primary">{label}</div>
        {description && <div className="text-xs text-text-muted mt-0.5">{description}</div>}
      </div>
      <div
        onClick={onChange}
        className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors cursor-pointer ${checked ? "bg-accent" : "bg-bg-elevated border border-border"}`}
      >
        <div className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-4" : "translate-x-0.5"}`} />
      </div>
    </label>
  );
}

function SaveField({ label, value, onChange, onSave, type = "text", hint, disabled = false, placeholder = "" }: {
  label: string; value: string; onChange: (v: string) => void; onSave: () => void;
  type?: string; hint?: string; disabled?: boolean; placeholder?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-text-secondary">{label}</label>
      <div className="flex gap-2">
        <input
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          className="input flex-1 text-sm"
        />
        <button onClick={onSave} className="btn-secondary px-3 text-xs">Save</button>
      </div>
      {hint && <p className="text-xs text-text-muted">{hint}</p>}
    </div>
  );
}

export function SettingsPage() {
  const navigate = useNavigate();
  const [activeSection, setActiveSection] = useState<Section>("general");
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [saved, setSaved] = useState(false);
  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([]);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Field states
  const [companyName, setCompanyName]   = useState("");
  const [timezone,    setTimezone]      = useState("America/Chicago");
  const [locationId,  setLocationId]    = useState("main");
  const [pinInput,    setPinInput]      = useState("1234");
  const [showPin,     setShowPin]       = useState(false);
  const [kioskMsg,    setKioskMsg]      = useState("");
  const [minConf,     setMinConf]       = useState(0.75);
  const [failStreak,  setFailStreak]    = useState(5);
  const [retention,   setRetention]     = useState("90");
  const [payFormat,   setPayFormat]     = useState("gusto");
  const [payPeriod,   setPayPeriod]     = useState("1");

  useEffect(() => {
    fetchSettings().then((s) => {
      setSettings(s);
      setCompanyName(String(s.company_name ?? ""));
      setTimezone(String(s.timezone ?? "America/Chicago"));
      setLocationId(String(s.location_id ?? "main"));
      setPinInput(String(s.kiosk_pin ?? "1234"));
      setKioskMsg(String(s.kiosk_clock_in_message ?? ""));
      setMinConf(Number(s.attendance_min_confidence ?? 0.75));
      setFailStreak(Number(s.fail_streak_alert ?? 5));
      setRetention(String(s.data_retention_days ?? "90"));
      setPayFormat(String(s.default_export_format ?? "gusto"));
      setPayPeriod(String(s.pay_period_start_day ?? "1"));
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (activeSection === "audit") {
      fetchAuditLog(100).then(setAuditEntries).catch(() => {});
    }
  }, [activeSection]);

  const markSaved = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const toggle = async (key: string) => {
    setSaveError(null);
    try {
      const next = !settings[key];
      const updated = await patchSettings({ [key]: next });
      setSettings(updated);
      markSaved();
    } catch {
      setSaveError("Failed to save — check server connection");
    }
  };

  const saveField = async (key: string, value: unknown) => {
    setSaveError(null);
    try {
      const updated = await patchSettings({ [key]: value });
      setSettings(updated);
      markSaved();
    } catch {
      setSaveError("Failed to save — check server connection");
    }
  };

  const renderSection = () => {
    switch (activeSection) {
      case "general":
        return (
          <div className="space-y-6">
            <h2 className="text-base font-semibold text-text-primary">General</h2>
            <div className="card p-5 space-y-5">
              <SaveField
                label="Company Name"
                value={companyName}
                onChange={setCompanyName}
                onSave={() => saveField("company_name", companyName)}
                placeholder="Acme Corp"
              />
              <SaveField
                label="Timezone"
                value={timezone}
                onChange={setTimezone}
                onSave={() => saveField("timezone", timezone)}
                hint="IANA timezone (e.g. America/New_York)"
                placeholder="America/Chicago"
              />
              <SaveField
                label="Location / Site ID"
                value={locationId}
                onChange={setLocationId}
                onSave={() => saveField("location_id", locationId)}
                placeholder="main"
              />
            </div>
            <div className="card p-5 space-y-4">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">System Features</h3>
              <ToggleRow label="Attendance Tracking" description="Enable clock-in / clock-out recording" checked={Boolean(settings["attendance_enabled"])} onChange={() => toggle("attendance_enabled")} />
              <ToggleRow label="Server HUD Overlay" description="Draw bbox overlays on MJPEG stream" checked={Boolean(settings["hud_enabled"])} onChange={() => toggle("hud_enabled")} />
              <ToggleRow label="Voice Commands" checked={Boolean(settings["voice_enabled"])} onChange={() => toggle("voice_enabled")} />
            </div>
          </div>
        );

      case "recognition":
        return (
          <div className="space-y-6">
            <h2 className="text-base font-semibold text-text-primary">Recognition</h2>
            <div className="card p-5 space-y-5">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-medium text-text-secondary">Min Confidence</label>
                  <span className={`font-mono text-sm font-bold ${minConf < 0.70 ? "text-warning" : "text-accent"}`}>{minConf.toFixed(2)}</span>
                </div>
                <input
                  type="range" min="0.50" max="0.99" step="0.01"
                  value={minConf}
                  onChange={(e) => setMinConf(Number(e.target.value))}
                  onMouseUp={() => saveField("attendance_min_confidence", minConf)}
                  onTouchEnd={() => saveField("attendance_min_confidence", minConf)}
                  className="w-full accent-accent"
                />
                {minConf < 0.70 && (
                  <p className="text-xs text-warning">⚠ Values below 0.70 may increase false matches</p>
                )}
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-text-secondary">Fail Streak Alert (consecutive unknowns)</label>
                <div className="flex gap-2">
                  <input
                    type="number" min={1} max={20} value={failStreak}
                    onChange={(e) => setFailStreak(Number(e.target.value))}
                    className="input w-24 text-sm"
                  />
                  <button onClick={() => saveField("fail_streak_alert", failStreak)} className="btn-secondary text-xs px-3">Save</button>
                </div>
              </div>
              <ToggleRow label="Async Recognition" description="Run recognition on a background thread" checked={Boolean(settings["async_recognition"])} onChange={() => toggle("async_recognition")} />
              <ToggleRow label="Guided Enrollment" description="Multi-photo enrollment with quality feedback" checked={Boolean(settings["guided_enrollment_enabled"])} onChange={() => toggle("guided_enrollment_enabled")} />
            </div>
          </div>
        );

      case "kiosk":
        return (
          <div className="space-y-6">
            <h2 className="text-base font-semibold text-text-primary">Kiosk</h2>
            <div className="card p-5 space-y-5">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-text-secondary">Manager PIN (4 digits)</label>
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <input
                      type={showPin ? "text" : "password"}
                      maxLength={4}
                      value={pinInput}
                      onChange={(e) => setPinInput(e.target.value.replace(/\D/g, "").slice(0, 4))}
                      className="input w-full font-mono tracking-widest text-sm"
                      placeholder="••••"
                    />
                    <button
                      onClick={() => setShowPin((v) => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-text-muted hover:text-text-secondary"
                    >
                      {showPin ? "Hide" : "Show"}
                    </button>
                  </div>
                  <button onClick={() => saveField("kiosk_pin", pinInput)} disabled={pinInput.length !== 4} className="btn-secondary text-xs px-3">Save</button>
                </div>
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-text-secondary">Clock-in message</label>
                <textarea
                  value={kioskMsg}
                  onChange={(e) => setKioskMsg(e.target.value)}
                  rows={3}
                  placeholder="Look at the camera to clock in"
                  className="input w-full resize-none text-sm"
                />
                <button onClick={() => saveField("kiosk_clock_in_message", kioskMsg)} className="btn-secondary text-xs px-3">Save Message</button>
              </div>
              <a
                href="/kiosk"
                target="_blank"
                rel="noreferrer"
                className="btn-secondary block text-center text-sm"
              >
                Open Kiosk Screen →
              </a>
            </div>
          </div>
        );

      case "payroll":
        return (
          <div className="space-y-6">
            <h2 className="text-base font-semibold text-text-primary">Payroll</h2>
            <div className="card p-5 space-y-5">
              <div className="space-y-2">
                <label className="text-xs font-medium text-text-secondary">Default Export Format</label>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  {EXPORT_FORMATS.map((f) => (
                    <button
                      key={f.value}
                      onClick={() => { setPayFormat(f.value); saveField("default_export_format", f.value); }}
                      className={`rounded-card border px-4 py-3 text-sm font-medium transition-colors text-left ${
                        payFormat === f.value ? "border-accent bg-accent/10 text-accent" : "border-border text-text-secondary hover:border-accent/40"
                      }`}
                    >
                      {payFormat === f.value && <span className="mr-2 text-accent">✓</span>}
                      {f.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-text-secondary">Pay Period Start Day</label>
                <select
                  value={payPeriod}
                  onChange={(e) => { setPayPeriod(e.target.value); saveField("pay_period_start_day", Number(e.target.value)); }}
                  className="input w-full text-sm"
                >
                  {PAY_PERIOD_DAYS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
                </select>
              </div>
            </div>
          </div>
        );

      case "privacy":
        return (
          <div className="space-y-6">
            <h2 className="text-base font-semibold text-text-primary">Data & Privacy</h2>
            <div className="card p-5 space-y-5">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-text-secondary">Snapshot Retention</label>
                <select
                  value={retention}
                  onChange={(e) => { setRetention(e.target.value); saveField("data_retention_days", Number(e.target.value)); }}
                  className="input w-full text-sm"
                >
                  {RETENTION_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
              <ToggleRow label="Save Clock-in Snapshots" description="Store a JPEG with each clock-in event for disputes" checked={Boolean(settings["save_clock_in_snapshot"])} onChange={() => toggle("save_clock_in_snapshot")} />
            </div>

            {/* Danger zone */}
            <div className="rounded-card border border-danger/30 bg-danger/5 p-5 space-y-3">
              <h3 className="text-sm font-semibold text-danger">Danger Zone</h3>
              <p className="text-xs text-text-secondary">Permanently delete all employee face templates and attendance records. This action cannot be undone.</p>
              {!deleteConfirm ? (
                <button onClick={() => setDeleteConfirm(true)} className="btn-danger text-sm">
                  Delete All Employee Data
                </button>
              ) : (
                <div className="flex gap-3">
                  <button onClick={() => setDeleteConfirm(false)} className="btn-ghost text-sm">Cancel</button>
                  <button
                    onClick={async () => {
                      setDeleteConfirm(false);
                      try {
                        await resetAllProfiles();
                        // Navigate to dashboard so all stale React state is
                        // cleared — the components will re-fetch from the
                        // now-empty backend on mount.
                        navigate("/");
                      } catch {
                        setSaveError("Reset failed — check server connection");
                      }
                    }}
                    className="btn-danger text-sm"
                  >
                    Confirm: Delete Everything
                  </button>
                </div>
              )}
            </div>
          </div>
        );

      case "audit":
        return (
          <div className="space-y-4">
            <h2 className="text-base font-semibold text-text-primary">Audit Log</h2>
            <div className="card overflow-hidden">
              {auditEntries.length === 0 ? (
                <div className="py-10 text-center text-text-muted text-sm">No audit entries found</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs font-mono">
                    <thead>
                      <tr className="border-b border-border text-left">
                        <th className="px-4 py-2.5 font-medium text-text-secondary">Timestamp</th>
                        <th className="px-4 py-2.5 font-medium text-text-secondary">Action</th>
                        <th className="px-4 py-2.5 font-medium text-text-secondary">Manager</th>
                        <th className="px-4 py-2.5 font-medium text-text-secondary">Detail</th>
                      </tr>
                    </thead>
                    <tbody>
                      {auditEntries.map((e, i) => (
                        <tr key={i} className={`border-b border-border/50 ${i % 2 === 0 ? "" : "bg-bg-elevated/40"}`}>
                          <td className="px-4 py-2 text-text-muted whitespace-nowrap">{e.ts}</td>
                          <td className="px-4 py-2 text-accent">{e.action}</td>
                          <td className="px-4 py-2 text-text-secondary">{e.manager ?? "—"}</td>
                          <td className="px-4 py-2 text-text-muted">{e.detail ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        );
    }
  };

  return (
    <div className="flex gap-0 min-h-full">
      {/* Sidebar nav — desktop */}
      <nav className="hidden md:flex flex-col shrink-0 w-48 border-r border-border pr-2 mr-6 pt-1 space-y-0.5">
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            onClick={() => setActiveSection(s.id)}
            className={`flex items-center gap-2.5 rounded-btn px-3 py-2 text-sm font-medium text-left transition-colors
              ${activeSection === s.id ? "bg-accent/10 text-accent" : "text-text-secondary hover:bg-bg-elevated hover:text-text-primary"}`}
          >
            <span>{s.icon}</span>
            {s.label}
          </button>
        ))}
      </nav>

      {/* Mobile: accordion-style section selector */}
      <div className="md:hidden w-full space-y-1 mb-4">
        <div className="flex flex-wrap gap-2">
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              onClick={() => setActiveSection(s.id)}
              className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors
                ${activeSection === s.id ? "border-accent bg-accent/10 text-accent" : "border-border text-text-secondary"}`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 min-w-0">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeSection}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.15 }}
            className="max-w-lg"
          >
            {renderSection()}
          </motion.div>
        </AnimatePresence>

        <AnimatePresence>
          {saved && (
            <motion.div
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="fixed bottom-6 right-6 z-50 rounded-card border border-accent/30 bg-accent/10 px-4 py-2 text-sm font-medium text-accent shadow-glow"
            >
              ✓ Settings saved
            </motion.div>
          )}
          {saveError && (
            <motion.div
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="fixed bottom-6 right-6 z-50 rounded-card border border-danger/30 bg-danger/10 px-4 py-2 text-sm font-medium text-danger shadow-lg"
            >
              ✕ {saveError}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
