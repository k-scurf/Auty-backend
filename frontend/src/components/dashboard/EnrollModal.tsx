import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { enrollProfile, skipEnrollment } from "../../services/api";

interface Props {
  open: boolean;
  imageB64?: string;
  onClose: () => void;
}

export function EnrollModal({ open, imageB64, onClose }: Props) {
  const [name, setName] = useState("");
  const [age, setAge] = useState("");
  const [status, setStatus] = useState("FRIEND");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleSave = async () => {
    if (!name.trim()) {
      setErr("Name is required");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await enrollProfile({
        name: name.trim(),
        age,
        status,
        image_b64: imageB64,
      });
      setName("");
      setAge("");
      onClose();
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? String((e as { response?: { data?: { detail?: string } } }).response?.data?.detail)
          : "Enrollment failed";
      setErr(msg);
    } finally {
      setBusy(false);
    }
  };

  const handleSkip = async () => {
    await skipEnrollment();
    onClose();
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.div
            className="w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-glow"
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.95, opacity: 0 }}
          >
            <h3 className="mb-4 text-lg font-semibold text-accent">New friend</h3>
            {imageB64 && (
              <img
                src={`data:image/jpeg;base64,${imageB64}`}
                alt="Pending enrollment"
                className="mb-4 mx-auto h-40 rounded-lg border border-border object-cover"
              />
            )}
            <div className="space-y-3">
              <input
                className="w-full rounded-lg border border-border bg-inset px-3 py-2 text-sm"
                placeholder="Name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <input
                className="w-full rounded-lg border border-border bg-inset px-3 py-2 text-sm"
                placeholder="Age"
                value={age}
                onChange={(e) => setAge(e.target.value)}
              />
              <input
                className="w-full rounded-lg border border-border bg-inset px-3 py-2 text-sm"
                placeholder="Status (e.g. FRIEND)"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              />
            </div>
            {err && <p className="mt-2 text-sm text-red-400">{err}</p>}
            <div className="mt-6 flex gap-2">
              <button
                type="button"
                className="flex-1 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-surface disabled:opacity-50"
                disabled={busy}
                onClick={handleSave}
              >
                Save profile
              </button>
              <button
                type="button"
                className="rounded-lg border border-border px-4 py-2 text-sm text-slate-300"
                onClick={handleSkip}
              >
                Skip
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
