import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ExportFormatCard } from "../ui/ExportFormatCard";
import { fetchExportPreview, downloadExport, fetchSettings } from "../../services/api";
import type { ExportPreview } from "../../types";

type Format = "gusto" | "adp" | "square";
type Step = 1 | 2 | 3;

// ---------------------------------------------------------------------------
// Date helpers
// ---------------------------------------------------------------------------

function toDateStr(d: Date): string {
  // Use local date parts to avoid UTC offset surprises on toISOString()
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function todayStr(): string {
  return toDateStr(new Date());
}

/** Most-recent (or current) occurrence of *dayOfWeek* (0=Sun … 6=Sat), at or before today. */
function mostRecentWeekday(dayOfWeek: number): Date {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  const diff = (d.getDay() - dayOfWeek + 7) % 7;
  d.setDate(d.getDate() - diff);
  return d;
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

/** First day of the current calendar month. */
function monthStartStr(): string {
  const d = new Date();
  return toDateStr(new Date(d.getFullYear(), d.getMonth(), 1));
}

const STEP_LABELS = ["Date Range", "Format", "Preview & Download"];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ExportPanel() {
  // ── Settings ──────────────────────────────────────────────────────────────
  // Pay-period start day (0=Sun … 6=Sat).  Loaded from backend settings;
  // defaults to Monday until the fetch completes.
  const [payPeriodStartDay, setPayPeriodStartDay] = useState(1); // 1 = Monday

  // ── Wizard state ─────────────────────────────────────────────────────────
  const [step, setStep] = useState<Step>(1);
  const [format, setFormat] = useState<Format>("gusto");
  const [startDate, setStartDate] = useState(() => toDateStr(mostRecentWeekday(1)));
  const [endDate, setEndDate] = useState(todayStr);
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load settings once on mount.
  useEffect(() => {
    fetchSettings()
      .then((s) => {
        const startDay = Number(s.pay_period_start_day ?? 1);
        setPayPeriodStartDay(startDay);
        // Default date range to the current pay period now that we know the start day.
        const periodStart = mostRecentWeekday(startDay);
        setStartDate(toDateStr(periodStart));
        setEndDate(todayStr());

        const fmt = String(s.default_export_format ?? "gusto") as Format;
        if (["gusto", "adp", "square"].includes(fmt)) setFormat(fmt);
      })
      .catch(() => {});
  }, []);

  // ── Quick range presets (depend on payPeriodStartDay) ─────────────────────
  const quickRanges = [
    {
      label: "This Pay Period",
      start: () => toDateStr(mostRecentWeekday(payPeriodStartDay)),
      end:   () => todayStr(),
    },
    {
      label: "Last Pay Period",
      start: () => toDateStr(addDays(mostRecentWeekday(payPeriodStartDay), -7)),
      end:   () => toDateStr(addDays(mostRecentWeekday(payPeriodStartDay), -1)),
    },
    {
      label: "This Month",
      start: () => monthStartStr(),
      end:   () => todayStr(),
    },
  ];

  // ── Preview / download ────────────────────────────────────────────────────
  const loadPreview = async () => {
    setError(null);
    setLoadingPreview(true);
    try {
      const data = await fetchExportPreview({ format, start_date: startDate, end_date: endDate });
      setPreview(data);
    } catch {
      setError("Failed to load preview. Check that dates are valid.");
    } finally {
      setLoadingPreview(false);
    }
  };

  const handleDownload = async () => {
    setError(null);
    setDownloading(true);
    try {
      const blob = await downloadExport({ format, start_date: startDate, end_date: endDate });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `attendance_${format}_${startDate}_${endDate}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Export failed. Please try again.");
    } finally {
      setDownloading(false);
    }
  };

  const goToStep = (s: Step) => {
    if (s === 3 && !preview) loadPreview();
    setStep(s);
  };

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="max-w-2xl space-y-6">
      {/* Step indicator */}
      <div className="flex items-center gap-0">
        {STEP_LABELS.map((label, i) => {
          const s = (i + 1) as Step;
          const active = step === s;
          const done = step > s;
          return (
            <div key={s} className="flex items-center flex-1">
              <button
                onClick={() => { if (done || active) setStep(s); }}
                className={`flex items-center gap-2 text-sm font-medium transition-colors ${
                  active ? "text-accent" : done ? "text-text-secondary" : "text-text-muted"
                }`}
              >
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-bold ${
                    active ? "border-accent bg-accent text-bg"
                    : done  ? "border-accent/40 bg-accent/15 text-accent"
                    : "border-border text-text-muted"
                  }`}
                >
                  {done ? "✓" : s}
                </span>
                <span className="hidden sm:block">{label}</span>
              </button>
              {i < STEP_LABELS.length - 1 && (
                <div className={`mx-2 flex-1 h-px ${done ? "bg-accent/40" : "bg-border"}`} />
              )}
            </div>
          );
        })}
      </div>

      {/* Steps */}
      <AnimatePresence mode="wait">
        {step === 1 && (
          <motion.div
            key="s1"
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
            className="card p-5 space-y-5"
          >
            <h3 className="font-semibold text-text-primary">Select Date Range</h3>

            {/* Quick-range chips */}
            <div className="flex flex-wrap gap-2">
              {quickRanges.map((r) => {
                const rs = r.start();
                const re = r.end();
                const active = startDate === rs && endDate === re;
                return (
                  <button
                    key={r.label}
                    onClick={() => { setStartDate(rs); setEndDate(re); setPreview(null); }}
                    className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                      active
                        ? "border-accent bg-accent/15 text-accent"
                        : "border-border text-text-secondary hover:border-accent/40 hover:text-text-primary"
                    }`}
                  >
                    {r.label}
                  </button>
                );
              })}
            </div>

            {/* Manual date pickers */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <label className="text-xs font-medium text-text-secondary">Start date</label>
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => { setStartDate(e.target.value); setPreview(null); }}
                  className="input w-full text-xs"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-text-secondary">End date</label>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => { setEndDate(e.target.value); setPreview(null); }}
                  className="input w-full text-xs"
                />
              </div>
            </div>

            <div className="flex justify-end">
              <button
                onClick={() => setStep(2)}
                disabled={!startDate || !endDate || startDate > endDate}
                className="btn-primary disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Next: Choose Format →
              </button>
            </div>
          </motion.div>
        )}

        {step === 2 && (
          <motion.div
            key="s2"
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
            className="card p-5 space-y-5"
          >
            <h3 className="font-semibold text-text-primary">Select Export Format</h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {(["gusto", "adp", "square"] as Format[]).map((f) => (
                <ExportFormatCard
                  key={f}
                  format={f}
                  selected={format === f}
                  onSelect={() => { setFormat(f); setPreview(null); }}
                />
              ))}
            </div>
            <div className="flex justify-between gap-3">
              <button onClick={() => setStep(1)} className="btn-ghost">← Back</button>
              <button
                onClick={() => goToStep(3)}
                className="btn-primary"
                disabled={loadingPreview}
              >
                {loadingPreview ? "Loading preview…" : "Preview Export →"}
              </button>
            </div>
          </motion.div>
        )}

        {step === 3 && (
          <motion.div
            key="s3"
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
            className="card p-5 space-y-5"
          >
            <h3 className="font-semibold text-text-primary">Preview & Download</h3>

            {loadingPreview && (
              <div className="space-y-2">
                <div className="skeleton h-4 w-1/2" />
                <div className="skeleton h-4 w-1/3" />
                <div className="skeleton h-4 w-2/3" />
              </div>
            )}

            {preview && !loadingPreview && (
              <div className="space-y-4">
                <div className="grid grid-cols-3 gap-3 text-center">
                  <div className="rounded-card border border-border bg-bg-elevated p-3">
                    <div className="font-mono text-xl font-bold text-accent">{preview.employee_count}</div>
                    <div className="text-xs text-text-secondary mt-0.5">Employees</div>
                  </div>
                  <div className="rounded-card border border-border bg-bg-elevated p-3">
                    <div className="font-mono text-xl font-bold text-accent">{preview.total_hours}h</div>
                    <div className="text-xs text-text-secondary mt-0.5">Total Hours</div>
                  </div>
                  <div className="rounded-card border border-border bg-bg-elevated p-3">
                    <div className="font-mono text-xl font-bold text-text-primary">{preview.row_count}</div>
                    <div className="text-xs text-text-secondary mt-0.5">Rows</div>
                  </div>
                </div>
                <div className="font-mono text-xs text-text-muted">
                  {preview.start_date} → {preview.end_date} · {format.toUpperCase()} format
                </div>
                {preview.row_count === 0 && (
                  <p className="text-sm text-text-muted text-center py-4">
                    No completed shifts found for this date range.
                  </p>
                )}
              </div>
            )}

            {error && <p className="text-sm text-danger">{error}</p>}

            <div className="flex justify-between gap-3">
              <button onClick={() => setStep(2)} className="btn-ghost">← Back</button>
              <button
                onClick={handleDownload}
                disabled={downloading || !preview || preview.row_count === 0}
                className="btn-primary flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {downloading ? "Downloading…" : (
                  <>
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <path d="M7 2v7M4 7l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M2 12h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                    </svg>
                    Download CSV
                  </>
                )}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
