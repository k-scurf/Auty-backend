import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  cancelEnrollment, recordConsent, renameProvisionalEnrollment,
} from "../../services/api";
import type { EnrollmentErrorDetail } from "../../types";
import { GuidedPoseCapture } from "./GuidedPoseCapture";

type EnrollmentErrorDisplay = {
  code?: string;
  title: string;
  message: string;
  action: string;
  photoIndex?: number;
  confidence?: number;
};

function parseEnrollmentError(e: unknown): EnrollmentErrorDisplay {
  const fallback: EnrollmentErrorDisplay = {
    title: "Something went wrong",
    message: "The recognition system encountered an error. Please try again.",
    action: "retry",
  };
  if (!e || typeof e !== "object" || !("response" in e)) return fallback;
  const detail = (e as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
  if (!detail) return fallback;
  if (typeof detail === "string") {
    return { title: "Enrollment failed", message: detail, action: "retry" };
  }
  const d = detail as EnrollmentErrorDetail;
  const titles: Record<string, string> = {
    NO_FACE_DETECTED: "No face detected",
    MULTIPLE_FACES: "Multiple faces detected",
    LOW_CONFIDENCE: "Recognition quality too low",
    CONSENT_MISSING: "Consent required",
    ALREADY_ENROLLED: "Already enrolled",
    MODEL_ERROR: "Something went wrong",
    ENROLLMENT_FAILED: "Enrollment failed",
  };
  return {
    code: d.code,
    title: titles[d.code] ?? "Enrollment failed",
    message: d.message || fallback.message,
    action: d.action || "retry",
    photoIndex: d.photo_index,
    confidence: d.confidence,
  };
}
type Step = 1 | 2 | 3 | 4;

const STEP_LABELS = ["Consent", "Capture", "Details", "Done"];

// Messages shown in sequence while the save API call runs
const SAVE_STEPS = [
  "Analyzing face images…",
  "Generating recognition template…",
  "Saving employee profile…",
];

interface Props {
  onDone: () => void;
  employeeName?: string;
  previewB64?: string | null;
  progress?: {
    active?: boolean;
    instruction?: string;
    captured?: number;
    target?: number;
    min_auto?: number;
    percent?: number;
    rejected_blur?: number;
    rejected_quality?: number;
    rejected_pose?: number;
    rejected_embed?: number;
    tick_count?: number;
    last_reject_reason?: string | null;
    ready_to_save?: boolean;
    preview_b64?: string | null;
    auto_committed?: boolean;
    provisional_name?: string | null;
    phase?: string;
    phase_counts?: Record<string, number>;
    phase_targets?: Record<string, number>;
    phases?: string[];
  } | null;
}

// ── Step 1: Consent ──────────────────────────────────────────────────────────
function ConsentStep({ onAccept, onDecline }: { onAccept: () => void; onDecline: () => void }) {
  const [checked, setChecked] = useState(false);

  const BLOCKS = [
    { icon: "🔒", title: "Secure storage",  body: "Your biometric template is stored locally on-premises and is never transmitted to third parties." },
    { icon: "📋", title: "Purpose",          body: "Your face data is used solely to verify your identity for clock-in and clock-out." },
    { icon: "🗑",  title: "Deletion rights", body: "You may request deletion of your biometric data at any time through your manager." },
    { icon: "🛡",  title: "Compliance",      body: "Data collection complies with applicable biometric privacy laws including BIPA and CCPA." },
  ];

  return (
    <div className="flex flex-col items-center gap-6 max-w-[560px] mx-auto w-full px-2">
      <div className="text-center space-y-1">
        <h2 className="text-xl font-bold text-text-primary">Biometric Data Consent</h2>
        <p className="text-sm text-text-secondary">Please review and consent before proceeding.</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full">
        {BLOCKS.map((b) => (
          <div key={b.title} className="card p-4 space-y-1.5">
            <div className="text-xl">{b.icon}</div>
            <div className="text-xs font-semibold text-text-primary">{b.title}</div>
            <div className="text-xs text-text-secondary leading-relaxed">{b.body}</div>
          </div>
        ))}
      </div>

      <div className="w-full rounded-card border border-border bg-bg-elevated p-4 max-h-32 overflow-y-auto text-xs text-text-secondary leading-relaxed">
        By enrolling, you consent to the collection, storage, and processing of your biometric face
        data (a numerical template derived from your face). This data is used exclusively for
        automated clock-in and clock-out verification. Your template is stored on-premises in
        encrypted form. You may withdraw consent and request deletion at any time by contacting your
        manager. Data will be retained only as long as you remain employed at this location.
      </div>

      <label className="flex items-center gap-2.5 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => setChecked(e.target.checked)}
          className="h-4 w-4 rounded border-border accent-accent"
        />
        <span className="text-sm text-text-secondary">
          I have read and agree to the biometric data terms above
        </span>
      </label>

      <div className="flex gap-3 w-full">
        <button onClick={onDecline} className="btn-ghost flex-1">Decline</button>
        <button onClick={onAccept} disabled={!checked} className="btn-primary flex-1">
          Accept & Continue →
        </button>
      </div>
    </div>
  );
}

// ── Step 3: Details ──────────────────────────────────────────────────────────
function EnrollmentErrorBanner({
  error,
  onRetry,
  onRetakeAll,
}: {
  error: EnrollmentErrorDisplay;
  onRetry: () => void;
  onRetakeAll: () => void;
}) {
  return (
    <div
      className="rounded-lg border p-4 mb-2"
      style={{
        background: "var(--color-bg-danger-soft)",
        borderColor: "var(--color-border-danger)",
      }}
    >
      <p className="text-sm font-medium text-danger mb-1">{error.title}</p>
      <p className="text-sm text-danger/90 leading-relaxed">{error.message}</p>
      {error.action === "retry" && (
        <button type="button" onClick={onRetry} className="btn-secondary text-sm mt-3">
          Try again
        </button>
      )}
      {(error.action === "retake_all" || error.action === "retake") && (
        <button type="button" onClick={onRetakeAll} className="btn-secondary text-sm mt-3">
          Retake all photos
        </button>
      )}
    </div>
  );
}

function DetailsStep({
  name, setName, role, setRole, employeeId, setEmployeeId,
  error, onNext, onBack,
}: {
  name: string; setName: (v: string) => void;
  role: string; setRole: (v: string) => void;
  employeeId: string; setEmployeeId: (v: string) => void;
  error: EnrollmentErrorDisplay | null;
  onNext: () => void; onBack: () => void;
}) {
  return (
    <div className="flex flex-col gap-5 max-w-sm mx-auto w-full">
      <div className="space-y-1">
        <label className="text-xs font-medium text-text-secondary">
          Full Name <span className="text-danger">*</span>
        </label>
        <input
          className="input w-full"
          placeholder="e.g. Jane Smith"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
      </div>
      <div className="space-y-1">
        <label className="text-xs font-medium text-text-secondary">
          Role <span className="text-danger">*</span>
        </label>
        <select className="input w-full" value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="">Select role…</option>
          <option value="EMPLOYEE">Employee</option>
          <option value="MANAGER">Manager</option>
          <option value="ADMIN">Admin</option>
        </select>
      </div>
      <div className="space-y-1">
        <label className="text-xs font-medium text-text-secondary">
          Employee ID{" "}
          <span className="text-text-muted text-[10px]">(optional)</span>
        </label>
        <input
          className="input w-full"
          placeholder="e.g. EMP-001"
          value={employeeId}
          onChange={(e) => setEmployeeId(e.target.value)}
        />
      </div>
      {error && (
        <p className="text-sm text-danger">
          <span className="font-medium">{error.title}: </span>
          {error.message}
        </p>
      )}
      <div className="flex gap-3">
        <button onClick={onBack} className="btn-ghost flex-1">← Back</button>
        <button
          onClick={onNext}
          disabled={!name.trim() || !role}
          className="btn-primary flex-1"
        >
          Save Employee →
        </button>
      </div>
    </div>
  );
}

// ── Step 4: Confirmation ─────────────────────────────────────────────────────
function ConfirmStep({
  name, onAddAnother, onDone,
}: {
  name: string; onAddAnother: () => void; onDone: () => void;
}) {
  return (
    <div className="flex flex-col items-center gap-6 max-w-sm mx-auto w-full text-center">
      <motion.div
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ type: "spring", stiffness: 260, damping: 18 }}
        className="flex h-20 w-20 items-center justify-center rounded-full bg-accent/20"
      >
        <span className="text-4xl text-accent">✓</span>
      </motion.div>
      <div className="space-y-1">
        <div className="text-xl font-bold text-text-primary">{name} has been added</div>
        <div className="text-sm text-text-secondary">
          Employee is now enrolled and ready to clock in immediately.
        </div>
      </div>
      <div className="flex gap-3 w-full">
        <button onClick={onAddAnother} className="btn-secondary flex-1">Add Another</button>
        <button onClick={onDone} className="btn-primary flex-1">Done</button>
      </div>
    </div>
  );
}

// ── Fix 5: Animated save progress screen ─────────────────────────────────────
function SavingScreen() {
  const [stepIdx, setStepIdx] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setStepIdx((i) => Math.min(i + 1, SAVE_STEPS.length - 1));
    }, 700);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex flex-col items-center gap-5 py-10 max-w-sm mx-auto w-full">
      {/* Spinning ring */}
      <svg className="animate-spin text-accent" width="40" height="40" viewBox="0 0 40 40" fill="none">
        <circle cx="20" cy="20" r="16" stroke="currentColor" strokeWidth="3" strokeOpacity="0.25" />
        <path d="M20 4a16 16 0 0 1 16 16" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      </svg>

      {/* Step messages — animated */}
      <div className="space-y-2 text-center w-full">
        {SAVE_STEPS.map((msg, i) => (
          <motion.p
            key={msg}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: i <= stepIdx ? 1 : 0.2, y: 0 }}
            transition={{ duration: 0.3, delay: i === stepIdx ? 0 : 0 }}
            className={`text-sm transition-colors ${
              i < stepIdx
                ? "text-accent line-through opacity-50"
                : i === stepIdx
                  ? "text-text-primary font-medium"
                  : "text-text-muted"
            }`}
          >
            {i < stepIdx && "✓ "}{msg}
          </motion.p>
        ))}
      </div>
    </div>
  );
}

// ── Main EnrollmentFlow ──────────────────────────────────────────────────────
export function EnrollmentFlow({ onDone }: Props) {
  const [step, setStep] = useState<Step>(1);
  const [name, setName] = useState("");
  const [role, setRole] = useState("EMPLOYEE");
  const [employeeId, setEmployeeId] = useState("");
  const [error, setError] = useState<EnrollmentErrorDisplay | null>(null);
  const [saving, setSaving] = useState(false);
  const [consentAccepted, setConsentAccepted] = useState(false);

  const handleConsent = async () => {
    await recordConsent({ employee_id: "pending", name: "pending" }).catch(() => {});
    setConsentAccepted(true);
    setStep(2);
  };

  // Pose capture + the embeddings themselves are already done and committed
  // server-side (vision/enrollment/session.py auto-commits once min_auto
  // samples land under a provisional "Guest_xxx" name). All that's left here
  // is collecting the real name and renaming that provisional record.
  const handleGuidedComplete = () => {
    setError(null);
    setStep(3);
  };

  const handleEnrollmentFailure = (err: EnrollmentErrorDisplay) => {
    setError(err);
    if (err.action === "restart") {
      setTimeout(() => {
        setConsentAccepted(false);
        setStep(1);
      }, 2000);
    }
  };

  const submitEnrollment = async () => {
    if (!name.trim()) {
      setError({ title: "Name required", message: "Enter the employee's full name.", action: "fix_input" });
      return;
    }
    if (!consentAccepted) {
      setError({
        title: "Consent required",
        message: "Biometric consent must be collected before enrolling. Restarting from the consent step.",
        action: "restart",
      });
      setTimeout(() => setStep(1), 2000);
      return;
    }

    setSaving(true);
    setError(null);

    try {
      await renameProvisionalEnrollment(name.trim());
      setStep(4);
    } catch (e: unknown) {
      handleEnrollmentFailure(parseEnrollmentError(e));
    } finally {
      setSaving(false);
    }
  };

  const handleSave = () => submitEnrollment();

  const handleDecline = () => {
    cancelEnrollment().catch(() => {});
    onDone();
  };

  const handleCaptureBack = () => {
    cancelEnrollment().catch(() => {});
    setStep(1);
  };

  return (
    <div className="fixed inset-0 z-[100] flex min-h-screen min-w-full flex-col items-center justify-center bg-bg p-4">
      {/* Step indicator */}
      <div className="flex items-center gap-0 mb-8 w-full max-w-lg">
        {STEP_LABELS.map((label, i) => {
          const s = (i + 1) as Step;
          const active = step === s;
          const done   = step > s;
          return (
            <div key={s} className="flex items-center flex-1">
              <div className={`flex items-center gap-1.5 text-xs font-medium
                ${active ? "text-accent" : done ? "text-text-secondary" : "text-text-muted"}`}>
                <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px] font-bold
                  ${active
                    ? "border-accent bg-accent text-bg"
                    : done
                      ? "border-accent/40 bg-accent/15 text-accent"
                      : "border-border text-text-muted"
                  }`}>
                  {done ? "✓" : s}
                </span>
                <span className="hidden sm:block">{label}</span>
              </div>
              {i < STEP_LABELS.length - 1 && (
                <div className={`mx-2 flex-1 h-px ${done ? "bg-accent/40" : "bg-border"}`} />
              )}
            </div>
          );
        })}
      </div>

      {/* Step content */}
      <div className="w-full max-w-lg">
        <AnimatePresence mode="wait">
          {step === 1 && (
            <motion.div
              key="s1"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
            >
              <ConsentStep onAccept={handleConsent} onDecline={handleDecline} />
            </motion.div>
          )}

          {step === 2 && (
            <motion.div
              key="s2"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
            >
              <GuidedPoseCapture
                onComplete={handleGuidedComplete}
                onCancel={handleCaptureBack}
              />
            </motion.div>
          )}

          {step === 3 && (
            <motion.div
              key="s3"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
            >
              {/* ── Fix 5: Show animated save steps instead of a plain spinner */}
              {saving ? (
                <SavingScreen />
              ) : (
                <>
                  {error && (
                    <EnrollmentErrorBanner
                      error={error}
                      onRetry={handleSave}
                      onRetakeAll={() => {
                        setError(null);
                        setStep(2);
                      }}
                    />
                  )}
                  <DetailsStep
                    name={name}
                    setName={setName}
                    role={role}
                    setRole={setRole}
                    employeeId={employeeId}
                    setEmployeeId={setEmployeeId}
                    error={error}
                    onNext={handleSave}
                    onBack={() => setStep(2)}
                  />
                </>
              )}
            </motion.div>
          )}

          {step === 4 && (
            <motion.div
              key="s4"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
            >
              <ConfirmStep
                name={name}
                onAddAnother={() => {
                  setStep(1);
                  setName("");
                  setRole("EMPLOYEE");
                  setEmployeeId("");
                  setError(null);
                  setConsentAccepted(false);
                }}
                onDone={onDone}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Cancel link — hidden on confirmation screen */}
      {step < 4 && (
        <button
          onClick={handleDecline}
          className="mt-8 text-xs text-text-muted hover:text-text-secondary transition-colors"
        >
          Cancel enrollment
        </button>
      )}
    </div>
  );
}
