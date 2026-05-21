import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { GlassCard } from "../ui/GlassCard";
import { cancelEnrollment, enrollProfile } from "../../services/api";
import type { EnrollmentProgress } from "../../types";

interface Props {
  progress: EnrollmentProgress | null | undefined;
  legacyImageB64?: string;
  onDone: () => void;
}

export function EnrollmentWizard({ progress, legacyImageB64, onDone }: Props) {
  const [name, setName] = useState("");
  const [age, setAge] = useState("");
  const [status, setStatus] = useState("FRIEND");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const capturing = Boolean(progress?.active);
  const autoCommitted = Boolean(progress?.auto_committed);
  const provisional = progress?.provisional_name ?? "";
  const ready = Boolean(progress?.ready_to_save);
  const previewB64 = progress?.preview_b64 ?? legacyImageB64;
  const minAuto = progress?.min_auto ?? 8;
  const target = progress?.target ?? 25;

  useEffect(() => {
    if (autoCommitted && provisional && !name) {
      setName("");
    }
  }, [autoCommitted, provisional, name]);

  const handleSave = async () => {
    if (!autoCommitted && !name.trim()) {
      setError("Name is required");
      return;
    }
    if (autoCommitted && !name.trim()) {
      onDone();
      return;
    }
    setSaving(true);
    setError("");
    try {
      await enrollProfile({
        name: name.trim(),
        age,
        status,
        image_b64: previewB64 ?? undefined,
      });
      onDone();
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? String(
              (e as { response?: { data?: { detail?: string } } }).response
                ?.data?.detail
            )
          : "Enrollment failed";
      setError(msg || "Enrollment failed");
    } finally {
      setSaving(false);
    }
  };

  const title = autoCommitted
    ? `Recognized as ${provisional}`
    : ready
      ? "Who is this?"
      : "New friend";

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      >
        <GlassCard className="w-full max-w-md space-y-4">
          <h2 className="text-lg font-semibold text-slate-100">{title}</h2>

          {capturing && !ready && (
            <>
              <p className="text-sm text-accent">
                {progress?.instruction || "Follow the prompts…"}
              </p>
              <motion.div className="h-2 overflow-hidden rounded-full bg-inset" layout>
                <div
                  className="h-full bg-accent transition-all"
                  style={{ width: `${progress?.percent ?? 0}%` }}
                />
              </motion.div>
              <p className="text-xs text-slate-400">
                {progress?.captured ?? 0} / {minAuto} minimum · {target} ideal · phase{" "}
                {progress?.phase}
                {progress?.rejected_blur
                  ? ` · ${progress.rejected_blur} rejected (blur/pose)`
                  : ""}
              </p>
            </>
          )}

          {ready && !autoCommitted && (
            <p className="text-sm text-slate-300">
              Photos captured — add a name to save.
            </p>
          )}

          {autoCommitted && (
            <p className="text-sm text-slate-300">
              You are already in the database. Add a real name (optional) or skip to keep{" "}
              {provisional}.
            </p>
          )}

          {previewB64 && (
            <img
              src={`data:image/jpeg;base64,${previewB64}`}
              alt="Enrollment preview"
              className="mx-auto h-32 rounded-lg border border-border object-cover"
            />
          )}

          {ready && (
            <motion.div
              className="space-y-2"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <input
                className="w-full rounded-lg border border-border bg-inset px-3 py-2 text-sm"
                placeholder={autoCommitted ? "Your name (optional)" : "Name"}
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoFocus
              />
              <input
                className="w-full rounded-lg border border-border bg-inset px-3 py-2 text-sm"
                placeholder="Age"
                value={age}
                onChange={(e) => setAge(e.target.value)}
              />
              <select
                className="w-full rounded-lg border border-border bg-inset px-3 py-2 text-sm"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                <option value="FRIEND">Friend</option>
                <option value="FAMILY">Family</option>
                <option value="WORK">Work</option>
              </select>
              {error && <p className="text-sm text-amber-400">{error}</p>}
              <motion.button
                type="button"
                whileTap={{ scale: 0.98 }}
                disabled={saving}
                className="w-full rounded-lg bg-accent py-2 text-sm font-medium text-slate-900 disabled:opacity-50"
                onClick={handleSave}
              >
                {saving
                  ? "Saving…"
                  : autoCommitted
                    ? name.trim()
                      ? "Save name"
                      : "Continue"
                    : "Save profile"}
              </motion.button>
              {autoCommitted && (
                <button
                  type="button"
                  className="w-full rounded-lg border border-border py-2 text-sm text-slate-300"
                  onClick={onDone}
                >
                  Skip — keep {provisional}
                </button>
              )}
            </motion.div>
          )}

          {!autoCommitted && (
            <button
              type="button"
              className="text-xs text-slate-500 underline"
              onClick={() => {
                cancelEnrollment();
                onDone();
              }}
            >
              Not now
            </button>
          )}
        </GlassCard>
      </motion.div>
    </AnimatePresence>
  );
};
