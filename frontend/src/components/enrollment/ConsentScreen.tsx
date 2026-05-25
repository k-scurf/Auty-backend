import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { GlassCard } from "../ui/GlassCard";
import { recordConsent } from "../../services/api";

interface Props {
  employeeName?: string;
  employeeId?: string;
  formVersion?: string;
  onConsent: () => void;
  onDecline: () => void;
}

export function ConsentScreen({
  employeeName = "",
  employeeId = "",
  formVersion = "1.0",
  onConsent,
  onDecline,
}: Props) {
  const [agreed, setAgreed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConsent = async () => {
    if (!agreed) return;
    setSubmitting(true);
    setError(null);
    try {
      await recordConsent({
        employee_id: employeeId || employeeName || "unknown",
        name: employeeName || "Employee",
        form_version: formVersion,
      });
      onConsent();
    } catch {
      setError("Failed to record consent. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      >
        <GlassCard className="w-full max-w-lg space-y-5">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">
              Biometric Data Consent
            </h2>
            <p className="mt-1 text-xs text-slate-500">Form version {formVersion}</p>
          </div>

          <div className="space-y-3 text-sm text-slate-300">
            <section className="space-y-1">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                What we collect
              </h3>
              <p>
                We capture 3–5 photos of your face from the live camera to create
                a mathematical face template (embedding). Raw photos are discarded
                after template generation.
              </p>
            </section>

            <section className="space-y-1">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                How it is stored
              </h3>
              <p>
                Your face template is encrypted and stored locally on this device.
                It is never shared with third parties or uploaded to external servers.
              </p>
            </section>

            <section className="space-y-1">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                What it is used for
              </h3>
              <p>
                Your face template is used exclusively to verify your identity when
                you clock in and out for work. It is not used for any other purpose.
              </p>
            </section>

            <section className="space-y-1">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Your rights
              </h3>
              <p>
                You may request deletion of your biometric data at any time through
                your employee profile page. Your account owner will be notified and
                your data will be permanently deleted.
              </p>
            </section>
          </div>

          <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border bg-inset/40 p-3">
            <input
              type="checkbox"
              checked={agreed}
              onChange={(e) => setAgreed(e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-accent"
            />
            <span className="text-sm text-slate-200">
              I consent to the collection and use of my biometric data for
              attendance tracking as described above.
            </span>
          </label>

          {error && <p className="text-xs text-red-400">{error}</p>}

          <div className="flex gap-3">
            <button
              onClick={onDecline}
              className="flex-1 rounded-lg border border-border py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
            >
              Decline
            </button>
            <button
              onClick={handleConsent}
              disabled={!agreed || submitting}
              className="flex-1 rounded-lg bg-accent py-2 text-sm font-semibold text-slate-900 hover:bg-accent/90 disabled:opacity-40 transition-colors"
            >
              {submitting ? "Recording consent…" : "I Agree — Continue"}
            </button>
          </div>
        </GlassCard>
      </motion.div>
    </AnimatePresence>
  );
}
