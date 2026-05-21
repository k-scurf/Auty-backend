import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { ProfileGrid } from "../components/profiles/ProfileGrid";
import { fetchProfiles } from "../services/api";
import type { Profile } from "../types";

export function ProfilesPage() {
  const [profiles, setProfiles] = useState<Profile[]>([]);

  useEffect(() => {
    fetchProfiles().then(setProfiles).catch(() => {});
  }, []);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <h2 className="mb-4 text-lg font-semibold text-slate-100">
        Known profiles
      </h2>
      <ProfileGrid profiles={profiles} />
    </motion.div>
  );
}
