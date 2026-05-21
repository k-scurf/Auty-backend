import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { GlassCard } from "../components/ui/GlassCard";
import { fetchSettings, patchSettings } from "../services/api";

const DEBUG_TOGGLES = [
  { key: "debug_mode", label: "Debug mode (WS payload)" },
  { key: "debug_draw_landmarks", label: "Draw landmarks on HUD" },
  { key: "debug_draw_quality", label: "Draw quality scores" },
  { key: "debug_draw_track_ids", label: "Draw track IDs" },
  { key: "debug_show_distances", label: "Show embedding distances" },
  { key: "debug_scores", label: "Log match scores to console" },
] as const;

const PIPELINE_NUMBERS = [
  { key: "confidence_threshold", label: "Match threshold", min: 0.2, max: 0.9, step: 0.01 },
  { key: "lock_retain_threshold", label: "Lock retain", min: 0.25, max: 0.7, step: 0.01 },
  { key: "lock_release_threshold", label: "Lock release", min: 0.2, max: 0.6, step: 0.01 },
  { key: "unknown_alert_max", label: "Unknown alert max", min: 0.2, max: 0.6, step: 0.01 },
  { key: "det_min_score_strict", label: "Det score strict", min: 0.5, max: 0.9, step: 0.01 },
  { key: "quality_min_blur_variance", label: "Min blur variance", min: 20, max: 200, step: 5 },
  { key: "lock_confirm_frames", label: "Lock confirm frames", min: 1, max: 15, step: 1 },
] as const;

const PRESETS: Record<string, Record<string, unknown>> = {
  strict: {
    detection_mode: "strict",
    detect_full_resolution: true,
    retinaface_detect_scale: 1.0,
    insightface_det_thresh: 0.62,
    det_min_score_strict: 0.65,
    haar_fallback_on_retinaface_fail: false,
    max_face_detections: 4,
    confidence_threshold: 0.48,
    lock_retain_threshold: 0.4,
    lock_release_threshold: 0.32,
    score_margin: 0.06,
    lock_confirm_frames: 6,
    min_vote_ratio: 0.65,
    unknown_alert_max: 0.35,
    reset_db_each_run: false,
  },
  balanced: {
    detection_mode: "balanced",
    detect_full_resolution: false,
    retinaface_detect_scale: 0.85,
    insightface_det_thresh: 0.55,
    det_min_score_strict: 0.55,
    haar_fallback_on_retinaface_fail: true,
    max_face_detections: 4,
    confidence_threshold: 0.45,
    lock_retain_threshold: 0.38,
    lock_release_threshold: 0.3,
    score_margin: 0.05,
    lock_confirm_frames: 5,
    min_vote_ratio: 0.55,
    unknown_alert_max: 0.38,
  },
  long_range: {
    detection_mode: "balanced",
    detect_full_resolution: true,
    retinaface_detect_scale: 1.0,
    insightface_det_thresh: 0.52,
    det_min_score_strict: 0.58,
    min_face_area_ratio: 0.004,
    confidence_threshold: 0.42,
    lock_retain_threshold: 0.36,
    unknown_alert_max: 0.32,
  },
  security_desk: {
    enrollment_min_auto_save: 8,
    enrollment_min_ready_ui: 6,
    enrollment_target_total: 25,
    enrollment_relaxed_pose: true,
    quality_min_enroll_capture: 55,
    enrollment_phase_timeout_sec: 12,
    enrollment_provisional_prefix: "Guest",
    enrollment_min_stable_frames: 10,
    unknown_min_stable_frames: 8,
    track_require_verified_det: true,
    max_missing_frames: 5,
    max_unverified_frames: 2,
    bytetrack_track_buffer: 15,
    auto_enrollment_enabled: true,
    guided_enrollment_enabled: true,
    confidence_threshold: 0.48,
    score_margin: 0.06,
    lock_confirm_frames: 6,
    reset_db_each_run: false,
  },
};

export function DebugPage() {
  const [settings, setSettings] = useState<Record<string, unknown>>({});

  useEffect(() => {
    fetchSettings().then(setSettings).catch(() => {});
  }, []);

  const toggle = async (key: string) => {
    const updated = await patchSettings({ [key]: !settings[key] });
    setSettings(updated);
  };

  const setNumber = async (key: string, value: number) => {
    const updated = await patchSettings({ [key]: value });
    setSettings(updated);
  };

  const applyPreset = async (name: keyof typeof PRESETS) => {
    const updated = await patchSettings(PRESETS[name]);
    setSettings(updated);
  };

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="max-w-xl space-y-6">
      <h2 className="text-lg font-semibold text-slate-100">Debug & pipeline</h2>
      <GlassCard className="flex flex-wrap gap-2">
        <span className="w-full text-sm text-slate-400">Presets (restart server after apply)</span>
        {(["strict", "balanced", "long_range", "security_desk"] as const).map((p) => (
          <button
            key={p}
            type="button"
            className="rounded-lg border border-border px-3 py-1.5 text-sm capitalize text-slate-300 hover:bg-inset"
            onClick={() => applyPreset(p)}
          >
            {p.replace("_", " ")}
          </button>
        ))}
      </GlassCard>
      <GlassCard className="space-y-3">
        <h3 className="text-sm font-medium text-slate-300">Overlays</h3>
        {DEBUG_TOGGLES.map(({ key, label }) => (
          <label key={key} className="flex justify-between gap-4 text-sm">
            <span className="text-slate-400">{label}</span>
            <input
              type="checkbox"
              checked={Boolean(settings[key])}
              onChange={() => toggle(key)}
              className="accent-accent"
            />
          </label>
        ))}
      </GlassCard>
      <GlassCard className="space-y-4">
        <h3 className="text-sm font-medium text-slate-300">Thresholds</h3>
        {PIPELINE_NUMBERS.map(({ key, label, min, max, step }) => (
          <div key={key}>
            <motion.div
              className="mb-1 flex justify-between text-xs text-slate-400"
              layout
            >
              <span>{label}</span>
              <span>{Number(settings[key] ?? min)}</span>
            </motion.div>
            <input
              type="range"
              min={min}
              max={max}
              step={step}
              value={Number(settings[key] ?? min)}
              onChange={(e) => setNumber(key, parseFloat(e.target.value))}
              className="w-full accent-accent"
            />
          </div>
        ))}
      </GlassCard>
      <p className="text-xs text-slate-500">
        Mode: {String(settings.detection_mode ?? "balanced")} · Detections:{" "}
        {String(settings.max_face_detections ?? 3)}
      </p>
    </motion.div>
  );
}
