import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { LiveFeed } from "../components/dashboard/LiveFeed";
import { ProfileCard } from "../components/dashboard/ProfileCard";
import { StatusPills } from "../components/dashboard/StatusPills";
import { EnrollModal } from "../components/dashboard/EnrollModal";
import { EnrollmentWizard } from "../components/dashboard/EnrollmentWizard";
import { TrackListPanel } from "../components/dashboard/TrackListPanel";
import { useFrameContext } from "../context/FrameContext";
import { usePrimaryTrack } from "../hooks/usePrimaryTrack";
import { fetchSettings } from "../services/api";

export function DashboardPage() {
  const { frame } = useFrameContext();
  const primary = usePrimaryTrack(frame);
  const [showEmotion, setShowEmotion] = useState(false);
  const [enrollDismissed, setEnrollDismissed] = useState(false);
  const [guidedEnroll, setGuidedEnroll] = useState(true);
  const [debugMode, setDebugMode] = useState(false);

  useEffect(() => {
    fetchSettings()
      .then((s) => {
        setShowEmotion(Boolean(s.user_emotion_enabled));
        setDebugMode(Boolean(s.debug_mode));
        setGuidedEnroll(s.guided_enrollment_enabled !== false);
      })
      .catch(() => {});
  }, []);

  const enrollment = frame?.enrollment;
  const progress = frame?.enrollment_progress;
  const legacyReady =
    Boolean(enrollment?.ready) && Boolean(enrollment?.image_b64);
  const guidedCapturing = Boolean(progress?.active);
  const guidedReady = Boolean(progress?.ready_to_save);
  const autoCommitted = Boolean(progress?.auto_committed);

  const showLegacyModal =
    !guidedEnroll && legacyReady && !enrollDismissed;
  const showWizard =
    guidedEnroll &&
    !enrollDismissed &&
    (guidedCapturing || guidedReady || autoCommitted || legacyReady);

  useEffect(() => {
    if (guidedCapturing || guidedReady || legacyReady) {
      setEnrollDismissed(false);
    }
  }, [guidedCapturing, guidedReady, legacyReady]);

  const handleEnrollClose = () => {
    setEnrollDismissed(true);
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="grid gap-6 lg:grid-cols-[1fr_320px]"
    >
      <div className="space-y-4">
        <StatusPills
          fsmState={frame?.fsm_state ?? "IDLE"}
          mood={frame?.mood ?? "Calm"}
        />
        <LiveFeed frame={frame} />
        <p className="text-sm text-slate-500">
          {guidedCapturing
            ? progress?.instruction || "Capturing enrollment photos…"
            : frame?.status_line || "Waiting for camera…"}
        </p>
      </div>
      <motion.div className="space-y-4" layout>
        <ProfileCard
          track={primary}
          statusLine={frame?.status_line ?? ""}
          showEmotion={showEmotion}
        />
        <TrackListPanel tracks={frame?.tracks ?? []} debugMode={debugMode} />
        {(guidedCapturing || autoCommitted) && (
          <p className="text-center text-xs text-accent">
            {autoCommitted
              ? `Recognized as ${progress?.provisional_name ?? "Guest"}`
              : `${progress?.captured ?? 0} / ${progress?.min_auto ?? 8} min · ${progress?.target ?? 25} ideal`}
          </p>
        )}
      </motion.div>
      <EnrollModal
        open={showLegacyModal}
        imageB64={enrollment?.image_b64}
        onClose={handleEnrollClose}
      />
      {showWizard && (
        <EnrollmentWizard
          progress={progress}
          legacyImageB64={enrollment?.image_b64}
          onDone={handleEnrollClose}
        />
      )}
    </motion.div>
  );
}
