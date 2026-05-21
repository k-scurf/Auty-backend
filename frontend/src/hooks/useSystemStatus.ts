import { useEffect, useState } from "react";
import { fetchHealthSoft } from "../services/api";
import type { HealthStatus } from "../types";

const defaultStatus: HealthStatus = {
  engine_ready: false,
  camera_ok: false,
  db_loaded: false,
  face_count: 0,
  profile_count: 0,
  fps: 0,
  uptime: 0,
  frame_count: 0,
};

export function useSystemStatus(pollMs = 5000) {
  const [status, setStatus] = useState<HealthStatus>(defaultStatus);

  useEffect(() => {
    let active = true;

    const poll = async () => {
      try {
        const data = await fetchHealthSoft();
        if (active) setStatus(data);
      } catch {
        if (active) setStatus(defaultStatus);
      }
    };

    poll();
    const id = setInterval(poll, pollMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [pollMs]);

  return status;
}
