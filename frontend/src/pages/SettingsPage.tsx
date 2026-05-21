import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { fetchSettings, patchSettings } from "../services/api";
import { GlassCard } from "../components/ui/GlassCard";

const TOGGLES = [
  { key: "hud_enabled", label: "Server HUD overlay (MJPEG)" },
  { key: "hud_draw_bbox", label: "Draw bounding boxes on stream" },
  { key: "user_emotion_enabled", label: "User emotion detection" },
  { key: "greetings_enabled", label: "Greetings" },
  { key: "personality_enabled", label: "Personality / LLM" },
  { key: "voice_enabled", label: "Voice" },
  { key: "reset_memory_each_run", label: "Reset social memory each run" },
  { key: "async_recognition", label: "Async recognition" },
] as const;

export function SettingsPage() {
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchSettings().then(setSettings).catch(() => {});
  }, []);

  const toggle = async (key: string) => {
    const next = !settings[key];
    const updated = await patchSettings({ [key]: next });
    setSettings(updated);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="max-w-lg">
      <h2 className="mb-4 text-lg font-semibold text-slate-100">Settings</h2>
      <GlassCard className="space-y-4">
        {TOGGLES.map(({ key, label }) => (
          <label
            key={key}
            className="flex cursor-pointer items-center justify-between gap-4 text-sm"
          >
            <span className="text-slate-300">{label}</span>
            <input
              type="checkbox"
              checked={Boolean(settings[key])}
              onChange={() => toggle(key)}
              className="h-4 w-4 accent-accent"
            />
          </label>
        ))}
      </GlassCard>
      {saved && (
        <p className="mt-2 text-sm text-accent">Settings saved.</p>
      )}
    </motion.div>
  );
}
