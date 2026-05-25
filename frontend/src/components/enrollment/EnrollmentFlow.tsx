import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  enrollProfile, cancelEnrollment, recordConsent,
  frameUrl, checkEnrollmentFrame,
} from "../../services/api";
import type { EnrollmentErrorDetail, FrameCheckResult } from "../../types";

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
import { useFrameJpeg } from "../../hooks/useFrameJpeg";
import { useDeviceCamera } from "../../hooks/useDeviceCamera";
import { isMobileDevice } from "../../utils/isMobile";

const USE_DEVICE_CAMERA = isMobileDevice();

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

// SVG ring constants (viewBox 320×320, camera circle r=128, ring r=148)
const SVG_SIZE = 320;
const CX = 160, CY = 160;
const RING_R = 148;
const CAM_R  = 128;

/** Client-side brightness check on center region (60–220). */
function clientLighting(ctx: CanvasRenderingContext2D, w: number, h: number): boolean {
  const size = Math.min(100, w, h);
  const x0 = Math.max(0, Math.floor(w / 2 - size / 2));
  const y0 = Math.max(0, Math.floor(h / 2 - size / 2));
  const data = ctx.getImageData(x0, y0, size, size).data;
  let brightness = 0;
  const n = data.length / 4;
  for (let i = 0; i < data.length; i += 4) {
    brightness += data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114;
  }
  return brightness / n >= 60 && brightness / n <= 220;
}

// ── Quality check indicator (Fix 1) ─────────────────────────────────────────
function QualityCheck({ label, passed }: { label: string; passed: boolean }) {
  return (
    <div
      className="flex items-center gap-2 rounded-md px-3 py-1.5 transition-colors duration-150"
      style={{
        background: passed ? "var(--color-bg-success)" : "var(--color-bg-elevated)",
      }}
    >
      <span
        className="text-sm font-medium transition-colors duration-150"
        style={{ color: passed ? "var(--color-text-success)" : "var(--color-text-muted)" }}
      >
        {passed ? "✓" : "×"}
      </span>
      <span
        className="text-[13px] transition-colors duration-150"
        style={{ color: passed ? "var(--color-text-success)" : "var(--color-text-secondary)" }}
      >
        {label}
      </span>
    </div>
  );
}

// ── Step 2: Capture (3-photo + live quality checks) ───────────────────────
function CaptureStep({
  onNext,
  onBack,
  capturedImages,
  onImagesChange,
  retakeIndex,
  onRetakeIndexChange,
}: {
  onNext: () => void;
  onBack: () => void;
  capturedImages: string[];
  onImagesChange: (imgs: string[]) => void;
  retakeIndex: number | null;
  onRetakeIndexChange: (idx: number | null) => void;
}) {
  const imgSrc = useFrameJpeg();
  const feedRef = useRef<HTMLImageElement>(null);
  const { videoRef: deviceVideoRef, error: cameraError } = useDeviceCamera(USE_DEVICE_CAMERA, "front");
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const [quality, setQuality] = useState<FrameCheckResult | null>(null);
  const [flashActive, setFlashActive] = useState(false);

  useEffect(() => {
    cancelEnrollment().catch(() => {});
  }, []);

  // Fix 1: poll quality every 500ms (device video or server JPEG feed)
  // Deps: [] — run once on mount only.
  //   • imgSrc was previously included but changes every ~200ms (useFrameJpeg)
  //     which caused the interval to be torn down and recreated constantly,
  //     so it never had a chance to fire.
  //   • deviceVideoRef is a stable ref object — no need to re-subscribe on it.
  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      const video = deviceVideoRef.current;
      const feed = feedRef.current;
      const canvas = canvasRef.current;
      if (!canvas) return;

      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      // All canvas work is inside try/catch so a SecurityError or transient
      // loading state never silently kills the polling loop.
      try {
        let w = 0;
        let h = 0;
        if (USE_DEVICE_CAMERA && video && video.readyState >= 2 && video.videoWidth > 0) {
          w = video.videoWidth;
          h = video.videoHeight;
          canvas.width = w;
          canvas.height = h;
          ctx.drawImage(video, 0, 0, w, h);
        } else if (feed && feed.complete && feed.naturalWidth > 0) {
          w = feed.naturalWidth;
          h = feed.naturalHeight;
          canvas.width = w;
          canvas.height = h;
          ctx.drawImage(feed, 0, 0, w, h);
        } else {
          return; // frame not ready yet — skip this tick
        }

        // Client-side brightness check (no API call needed for lighting).
        // Must be inside try/catch — getImageData throws SecurityError if
        // the canvas is somehow tainted.
        let lightingOk = true;
        try {
          lightingOk = clientLighting(ctx, w, h);
        } catch {
          lightingOk = true; // assume ok if we can't read pixels
        }

        // Higher quality (0.85) so face detection doesn't trip on JPEG artefacts.
        const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
        const result = await checkEnrollmentFrame(dataUrl);
        if (cancelled) return;
        const faceOk = result.face_detected && result.face_count === 1;
        setQuality({
          ...result,
          face_detected: faceOk,
          lighting_ok: lightingOk && result.lighting_ok,
          centered: faceOk && result.centered,
        });
      } catch {
        // Network error or canvas failure — don't update quality so the last
        // known good state is preserved rather than flashing to all-gray.
      }
    };

    const id = setInterval(poll, 500);
    poll(); // run immediately so indicators appear within 0-500ms of mount
    return () => { cancelled = true; clearInterval(id); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleCapture = () => {
    const video = deviceVideoRef.current;
    const feed = feedRef.current;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    if (USE_DEVICE_CAMERA && video && video.readyState >= 2) {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      ctx.drawImage(video, 0, 0);
    } else if (feed && feed.complete && feed.naturalWidth > 0) {
      canvas.width = feed.naturalWidth;
      canvas.height = feed.naturalHeight;
      ctx.drawImage(feed, 0, 0);
    } else {
      return;
    }

    const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
    setFlashActive(true);
    setTimeout(() => setFlashActive(false), 150);

    const updated = [...capturedImages];
    if (retakeIndex !== null) {
      updated[retakeIndex] = dataUrl;
      onImagesChange(updated);
      onRetakeIndexChange(null);
    } else if (updated.length < 3) {
      updated.push(dataUrl);
      onImagesChange(updated);
    }
  };

  const allChecksPassed =
    !!quality &&
    quality.face_detected &&
    quality.lighting_ok &&
    quality.centered;

  const allCaptured = capturedImages.length === 3;
  const showCaptureButton = !allCaptured || retakeIndex !== null;
  const captureDisabled = !allChecksPassed;

  const handleBack = () => {
    cancelEnrollment().catch(() => {});
    onBack();
  };

  return (
    <div className="flex flex-col items-center gap-5 w-full">
      <canvas ref={canvasRef} className="hidden" aria-hidden />

      <p className="text-sm text-text-secondary text-center">
        {retakeIndex !== null
          ? `Retaking photo ${retakeIndex + 1}`
          : allCaptured
            ? "All 3 photos captured"
            : `Photo ${capturedImages.length + 1} of 3`}
      </p>

      <div className="relative" style={{ width: SVG_SIZE, height: SVG_SIZE }}>
        {flashActive && (
          <div
            className="absolute inset-0 rounded-full bg-white z-10 pointer-events-none enroll-flash"
            style={{ animation: "enroll-flash 150ms ease-out forwards" }}
          />
        )}

        <div
          className="absolute overflow-hidden rounded-full border-2 transition-colors duration-150"
          style={{
            width: CAM_R * 2,
            height: CAM_R * 2,
            top: CY - CAM_R,
            left: CX - CAM_R,
            borderColor: allChecksPassed ? "var(--color-accent)" : "var(--color-border)",
          }}
        >
          {USE_DEVICE_CAMERA ? (
            cameraError ? (
              <div className="flex h-full w-full items-center justify-center bg-surface p-3 text-center">
                <p className="text-[11px] text-danger leading-snug">{cameraError}</p>
              </div>
            ) : (
              <video
                ref={deviceVideoRef}
                autoPlay
                playsInline
                muted
                className="h-full w-full object-cover"
                style={{ transform: "scaleX(-1)" }}
              />
            )
          ) : (
            <img
              ref={feedRef}
              src={imgSrc}
              alt="Camera feed"
              className="h-full w-full object-cover"
              crossOrigin="anonymous"
              onError={(e) => {
                (e.target as HTMLImageElement).src = frameUrl();
              }}
            />
          )}
        </div>

        <svg
          width={SVG_SIZE}
          height={SVG_SIZE}
          viewBox={`0 0 ${SVG_SIZE} ${SVG_SIZE}`}
          className="absolute inset-0 pointer-events-none"
        >
          <circle
            cx={CX}
            cy={CY}
            r={RING_R}
            fill="none"
            stroke={allChecksPassed ? "var(--color-accent)" : "rgba(255,255,255,0.12)"}
            strokeWidth="3"
            style={{ transition: "stroke 150ms ease" }}
          />
        </svg>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-2">
        <QualityCheck label="Face detected" passed={quality?.face_detected ?? false} />
        <QualityCheck label="Good lighting" passed={quality?.lighting_ok ?? false} />
        <QualityCheck label="Face centered" passed={quality?.centered ?? false} />
      </div>

      {!allChecksPassed && !cameraError && (
        <p className="text-xs text-text-muted text-center px-4">
          {quality === null
            ? "Starting camera…"
            : quality.message === "models_loading"
              ? "Recognition engine loading — please wait…"
              : !quality.face_detected
                ? (quality.face_count ?? 0) > 1
                  ? "Only one person should be in the frame"
                  : "Position your face in the circle"
                : !quality.lighting_ok
                  ? "Move to better lighting (not too dark or bright)"
                  : "Center your face in the frame"}
        </p>
      )}

      <div className="flex gap-3">
        {[0, 1, 2].map((idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => {
              if (capturedImages[idx]) {
                onRetakeIndexChange(retakeIndex === idx ? null : idx);
              }
            }}
            className={`relative h-[72px] w-[72px] overflow-hidden rounded-lg border flex items-center justify-center transition-all duration-150 ${
              retakeIndex === idx
                ? "border-accent ring-2 ring-accent/30"
                : capturedImages[idx]
                  ? "border-accent/50 hover:border-accent"
                  : "border-dashed border-border bg-bg-elevated"
            }`}
          >
            {capturedImages[idx] ? (
              <>
                <img
                  src={capturedImages[idx]}
                  alt={`Capture ${idx + 1}`}
                  className="h-full w-full object-cover"
                  style={USE_DEVICE_CAMERA ? { transform: "scaleX(-1)" } : undefined}
                />
                <span className="absolute bottom-0.5 right-0.5 rounded bg-black/60 px-1 text-[9px] text-white">
                  retake
                </span>
              </>
            ) : (
              <span className="text-lg text-text-muted">{idx + 1}</span>
            )}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-3 w-full max-w-sm">
        {showCaptureButton && (
          <button
            type="button"
            onClick={handleCapture}
            disabled={captureDisabled}
            className="btn-primary disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {retakeIndex !== null ? `Retake photo ${retakeIndex + 1}` : "Capture"}
          </button>
        )}

        <div className="flex gap-3">
          <button type="button" onClick={handleBack} className="btn-ghost flex-1">
            ← Back
          </button>
          {allCaptured && retakeIndex === null ? (
            <button type="button" onClick={onNext} className="btn-primary flex-1">
              Continue →
            </button>
          ) : (
            <button type="button" disabled className="btn-primary flex-1 opacity-40 cursor-not-allowed">
              {capturedImages.length}/3 captured
            </button>
          )}
        </div>
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

function LowConfidenceStep({
  confidence,
  onRetake,
  onSaveAnyway,
}: {
  confidence?: number;
  onRetake: () => void;
  onSaveAnyway: () => void;
}) {
  const pct = Math.round((confidence ?? 0) * 100);
  return (
    <div className="flex flex-col gap-4 max-w-sm mx-auto w-full text-center">
      <h3 className="text-lg font-semibold text-text-primary">Recognition quality is low</h3>
      <p className="text-sm text-text-secondary leading-relaxed">
        We can enroll this employee, but recognition may be unreliable. Better lighting or
        retaking photos usually fixes this.
      </p>
      <p className="text-sm text-warning">
        Quality score: {pct}% — below recommended 85%
      </p>
      <div className="flex gap-3 mt-2">
        <button type="button" onClick={onRetake} className="btn-ghost flex-1">
          Retake photos
        </button>
        <button type="button" onClick={onSaveAnyway} className="btn-primary flex-1">
          Save anyway
        </button>
      </div>
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
  const [capturedImages, setCapturedImages] = useState<string[]>([]);
  const [retakeIndex, setRetakeIndex] = useState<number | null>(null);
  const [showLowConfidence, setShowLowConfidence] = useState(false);
  const [lowConfidenceScore, setLowConfidenceScore] = useState<number | undefined>();

  const handleConsent = async () => {
    await recordConsent({ employee_id: "pending", name: "pending" }).catch(() => {});
    setConsentAccepted(true);
    setStep(2);
  };

  const handleCaptureNext = () => {
    if (capturedImages.length !== 3) {
      setError({
        title: "Photos required",
        message: "Capture all 3 photos before continuing.",
        action: "retake_all",
      });
      return;
    }
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
      return;
    }
    if (err.action === "retake" || err.action === "retake_all") {
      setStep(2);
      if (err.action === "retake_all") {
        setCapturedImages([]);
        setRetakeIndex(null);
      } else if (err.photoIndex != null) {
        setRetakeIndex(err.photoIndex);
      }
    }
  };

  const submitEnrollment = async (skipLowConfidenceCheck = false) => {
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
    if (capturedImages.length !== 3) {
      setError({
        title: "Photos required",
        message: "All 3 enrollment photos are required.",
        action: "retake_all",
      });
      setStep(2);
      return;
    }

    setSaving(true);
    setError(null);
    setShowLowConfidence(false);

    try {
      await enrollProfile({
        name: name.trim(),
        age: "",
        status: role,
        images: capturedImages,
        image_b64: capturedImages[0],
        allow_low_confidence: skipLowConfidenceCheck,
      });
      setStep(4);
    } catch (e: unknown) {
      const parsed = parseEnrollmentError(e);
      if (parsed.code === "LOW_CONFIDENCE" && !skipLowConfidenceCheck) {
        setLowConfidenceScore(parsed.confidence);
        setShowLowConfidence(true);
        setSaving(false);
        return;
      }
      handleEnrollmentFailure(parsed);
    } finally {
      setSaving(false);
    }
  };

  const handleSave = () => submitEnrollment(false);

  const handleDecline = () => {
    cancelEnrollment().catch(() => {});
    onDone();
  };

  const handleCaptureBack = () => {
    // Step indicator goes back to consent; session cancel is handled inside CaptureStep
    setStep(1);
  };

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-bg/95 backdrop-blur p-4">
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
              <CaptureStep
                onNext={handleCaptureNext}
                onBack={handleCaptureBack}
                capturedImages={capturedImages}
                onImagesChange={setCapturedImages}
                retakeIndex={retakeIndex}
                onRetakeIndexChange={setRetakeIndex}
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
              ) : showLowConfidence ? (
                <LowConfidenceStep
                  confidence={lowConfidenceScore}
                  onRetake={() => {
                    setCapturedImages([]);
                    setRetakeIndex(null);
                    setShowLowConfidence(false);
                    setError(null);
                    setStep(2);
                  }}
                  onSaveAnyway={() => {
                    setShowLowConfidence(false);
                    submitEnrollment(true);
                  }}
                />
              ) : (
                <>
                  {error && (
                    <EnrollmentErrorBanner
                      error={error}
                      onRetry={handleSave}
                      onRetakeAll={() => {
                        setCapturedImages([]);
                        setRetakeIndex(null);
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
                  setCapturedImages([]);
                  setRetakeIndex(null);
                  setConsentAccepted(false);
                  setShowLowConfidence(false);
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
