import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  startEnrollment, cancelEnrollment, fetchEnrollmentStatus, frameUrl,
} from "../../services/api";
import type { EnrollmentProgress } from "../../types";
import { useFrameJpeg } from "../../hooks/useFrameJpeg";
import { useDeviceCamera } from "../../hooks/useDeviceCamera";
import { isMobileDevice } from "../../utils/isMobile";

const USE_DEVICE_CAMERA = isMobileDevice();

// Face-ID-style auto-capture flow. Pose estimation, the 5-step sequence, and
// the stability gating that decides when a sample is actually captured all
// run server-side (vision/enrollment_pose_guide.py + vision/enrollment/session.py).
// This component only polls /api/enrollment/status and renders what it gets back.

const SVG_SIZE = 320;
const CX = 160, CY = 160;
const RING_R = 148;
const CAM_R = 128;
const POLL_MS = 200;

const STEP_LABELS: Record<string, string> = {
  front: "Center", center: "Center",
  left: "Left", right: "Right",
  up: "Up", down: "Down",
};

interface Props {
  trackId?: number;
  onComplete: (progress: EnrollmentProgress) => void;
  onCancel: () => void;
}

export function GuidedPoseCapture({ trackId, onComplete, onCancel }: Props) {
  const imgSrc = useFrameJpeg();
  const feedRef = useRef<HTMLImageElement>(null);
  // Posts to /api/enrollment/frame instead of /api/recognize-frame — the
  // server has no local webcam pointed at the kiosk in this setup, so the
  // device's own camera (iPad/phone) is the only thing that ever sees the
  // person being enrolled. Without this, server-side pose detection looks at
  // an empty server-side camera feed and reports "no face" forever.
  const { videoRef: deviceVideoRef, error: cameraError } = useDeviceCamera(
    USE_DEVICE_CAMERA, "front", "/api/enrollment/frame"
  );

  const [progress, setProgress] = useState<EnrollmentProgress | null>(null);
  const [justCaptured, setJustCaptured] = useState(false);
  const lastCapturedRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    startEnrollment(trackId).catch(() => {});

    const poll = async () => {
      try {
        const data = await fetchEnrollmentStatus();
        if (cancelled) return;
        setProgress(data);

        if (data.captured > lastCapturedRef.current) {
          lastCapturedRef.current = data.captured;
          setJustCaptured(true);
          setTimeout(() => setJustCaptured(false), 220);
        }

        if (data.active && data.phase === "done") {
          onComplete(data);
        }
      } catch {
        // transient network hiccup — keep last known state, try again next tick
      }
    };

    const id = setInterval(poll, POLL_MS);
    poll();
    return () => {
      cancelled = true;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trackId]);

  const handleCancel = () => {
    cancelEnrollment().catch(() => {});
    onCancel();
  };

  const phases = progress?.phases ?? ["front", "left", "right", "up", "down"];
  const phaseCounts = progress?.phase_counts ?? {};
  const phaseTargets = progress?.phase_targets ?? {};
  const currentPhase = progress?.phase ?? "front";
  const stability = Math.max(0, Math.min(1, progress?.stability_progress ?? 0));
  const faceVisible = progress?.face_visible ?? true; // assume ok before first poll lands
  const blocked = !faceVisible || (!!progress?.last_reject_reason && progress.last_reject_reason !== "pose");

  // Red by default — only green while the head is actually at the target
  // angle (stability_progress > 0 means the backend's pose-guide buffer is
  // currently accumulating, i.e. angle is correct right now). Capturing a
  // sample doesn't change this — only pose correctness does.
  const goodAngle = !blocked && stability > 0;
  const ringColor = goodAngle ? "var(--color-text-success)" : "var(--color-danger)";

  return (
    <div className="flex flex-col items-center gap-5 w-full">
      <p
        className="text-sm font-medium text-center min-h-[20px]"
        style={{ color: blocked ? "var(--color-danger)" : "var(--color-text-primary)" }}
      >
        {progress?.live_message || progress?.instruction || "Position your face in the frame"}
      </p>

      <div className="relative" style={{ width: SVG_SIZE, height: SVG_SIZE }}>
        {justCaptured && (
          <div
            className="absolute inset-0 rounded-full bg-white z-10 pointer-events-none"
            style={{ animation: "enroll-flash 200ms ease-out forwards" }}
          />
        )}

        <div
          className="absolute overflow-hidden rounded-full border-2 transition-colors duration-150"
          style={{
            width: CAM_R * 2,
            height: CAM_R * 2,
            top: CY - CAM_R,
            left: CX - CAM_R,
            borderColor: ringColor,
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

        {/* Outer ring: stability progress sweep */}
        <svg
          width={SVG_SIZE}
          height={SVG_SIZE}
          viewBox={`0 0 ${SVG_SIZE} ${SVG_SIZE}`}
          className="absolute inset-0 pointer-events-none"
        >
          <circle
            cx={CX} cy={CY} r={RING_R}
            fill="none"
            stroke="rgba(255,255,255,0.10)"
            strokeWidth="4"
          />
          <circle
            cx={CX} cy={CY} r={RING_R}
            fill="none"
            stroke={ringColor}
            strokeWidth="4"
            strokeLinecap="round"
            strokeDasharray={2 * Math.PI * RING_R}
            strokeDashoffset={2 * Math.PI * RING_R * (1 - stability)}
            transform={`rotate(-90 ${CX} ${CY})`}
            style={{ transition: "stroke-dashoffset 120ms linear, stroke 150ms ease" }}
          />
        </svg>
      </div>

      {/* Step dots with checkmarks */}
      <div className="flex items-center gap-3">
        {phases.map((p) => {
          const target = phaseTargets[p] ?? 1;
          const count = phaseCounts[p] ?? 0;
          const done = count >= target;
          const active = p === currentPhase;
          return (
            <div key={p} className="flex flex-col items-center gap-1">
              <span
                className={`flex h-7 w-7 items-center justify-center rounded-full border text-xs font-bold transition-colors duration-150
                  ${done
                    ? "border-accent bg-accent/15 text-accent"
                    : active
                      ? "border-accent text-accent"
                      : "border-border text-text-muted"
                  }`}
              >
                <AnimatePresence mode="wait">
                  {done ? (
                    <motion.span
                      key="check"
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                      transition={{ type: "spring", stiffness: 300, damping: 16 }}
                    >
                      ✓
                    </motion.span>
                  ) : (
                    <span key="dot">{active ? "•" : ""}</span>
                  )}
                </AnimatePresence>
              </span>
              <span className="text-[10px] text-text-muted">{STEP_LABELS[p] ?? p}</span>
            </div>
          );
        })}
      </div>

      <p className="text-xs text-text-muted">
        {progress?.captured ?? 0} samples captured
      </p>

      <button
        type="button"
        onClick={handleCancel}
        className="text-xs text-text-muted hover:text-text-secondary transition-colors"
      >
        Cancel enrollment
      </button>
    </div>
  );
}
