import { useCallback, useEffect, useRef, useState } from "react";
import type { FrameSnapshot } from "../types";
import { wsUrl } from "../services/api";

const MAX_HZ = 15;
const MIN_INTERVAL = 1000 / MAX_HZ;

export function useWebSocket() {
  const [frame, setFrame] = useState<FrameSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(500);
  const failCountRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const pendingRef = useRef<FrameSnapshot | null>(null);
  const lastApplyRef = useRef(0);

  const flush = useCallback(() => {
    rafRef.current = null;
    const now = performance.now();
    if (now - lastApplyRef.current < MIN_INTERVAL) {
      rafRef.current = requestAnimationFrame(flush);
      return;
    }
    if (pendingRef.current) {
      setFrame(pendingRef.current);
      lastApplyRef.current = now;
      pendingRef.current = null;
    }
  }, []);

  const scheduleUpdate = useCallback(
    (data: FrameSnapshot) => {
      pendingRef.current = data;
      if (rafRef.current === null) {
        rafRef.current = requestAnimationFrame(flush);
      }
    },
    [flush]
  );

  useEffect(() => {
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      if (cancelled) return;
      const ws = new WebSocket(wsUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setError(null);
        backoffRef.current = 500;
        failCountRef.current = 0;
      };

      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.type === "error") {
            setError(data.message || "Server error");
            return;
          }
          scheduleUpdate(data as FrameSnapshot);
        } catch {
          /* ignore parse errors */
        }
      };

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        if (!cancelled) {
          const delay = backoffRef.current;
          backoffRef.current = Math.min(delay * 2, 8000);
          reconnectTimer = setTimeout(connect, delay);
        }
      };

      ws.onerror = () => {
        failCountRef.current += 1;
        if (failCountRef.current >= 4) {
          setError(
            import.meta.env.DEV
              ? "Cannot reach Auty API — run python main.py (port 8000) while this page is open on :5173"
              : "Cannot reach Auty — run python main.py, then open http://127.0.0.1:8000",
          );
        } else {
          setError("Connecting to live feed…");
        }
        ws.close();
      };
    };

    connect();

    return () => {
      cancelled = true;
      clearTimeout(reconnectTimer);
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      wsRef.current?.close();
    };
  }, [scheduleUpdate]);

  return { frame, connected, error };
}
