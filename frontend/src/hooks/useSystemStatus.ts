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

export function useSystemStatus() {
  const [status, setStatus] = useState<HealthStatus>(defaultStatus);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      let nextMs = 5000;
      try {
        const data = await fetchHealthSoft();
        if (active) {
          setStatus(data);
          nextMs = data.engine_ready ? 5000 : 1000;
        }
      } catch {
        if (active) setStatus(defaultStatus);
        nextMs = 1000;
      }
      if (active) timer = setTimeout(poll, nextMs);
    };

    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, []);

  return status;
}
