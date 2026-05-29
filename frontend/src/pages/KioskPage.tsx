import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useWebSocket } from "../hooks/useWebSocket";
import { useFrameJpeg } from "../hooks/useFrameJpeg";
import { useDeviceCamera } from "../hooks/useDeviceCamera";
import { frameUrl } from "../services/api";
import {
  fetchSettings,
  fetchPresence,
  fetchAttendanceActive,
} from "../services/api";
import { isMobileDevice } from "../utils/isMobile";
import type { FrameSnapshot, PresenceSnapshot } from "../types";

const USE_DEVICE_CAMERA = isMobileDevice();

type KioskState = "idle" | "recognizing" | "clocked_in" | "clocked_out" | "unrecognized";

interface KioskEvent {
  state: KioskState;
  name?: string;
  time?: string;
}

function now12h() {
  return new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function presenceEventKey(name: string, event: string, ts: number) {
  return `${event}:${name}:${ts}`;
}

function attendanceEventKey(name: string, event: string, ts: number) {
  return `att:${event}:${name}:${ts}`;
}

// How recently an event must have occurred to be shown at bootstrap time.
// This ensures a check-in triggered by enrollment is immediately visible on
// the kiosk even though the kiosk page loaded after the event was already
// in events_tail.
const BOOTSTRAP_RECENT_WINDOW_SEC = 45;

function applyPresenceClockEvents(
  presence: PresenceSnapshot | null | undefined,
  opts: {
    bootstrap: boolean;
    seenPresence: Set<string>;
    prevIn: Set<string>;
    showClockIn: (name: string) => void;
    showClockOut: (name: string) => void;
  },
) {
  if (!presence) return;
  const events = presence.events_tail ?? [];

  if (opts.bootstrap) {
    const nowSec = Date.now() / 1000;
    for (const ev of events) {
      const key = presenceEventKey(ev.name, ev.event, ev.last_seen_ts);
      opts.seenPresence.add(key);
      // Show events that just happened — covers enrollment→kiosk flow where
      // the check-in fires before the page even loads.
      if (nowSec - ev.last_seen_ts < BOOTSTRAP_RECENT_WINDOW_SEC) {
        if (ev.event === "CHECK_IN") opts.showClockIn(ev.name);
        else if (ev.event === "CHECK_OUT") opts.showClockOut(ev.name);
      }
    }
    opts.prevIn.clear();
    for (const p of presence.in_office) opts.prevIn.add(p.name);
    return;
  }

  for (const ev of events) {
    const key = presenceEventKey(ev.name, ev.event, ev.last_seen_ts);
    if (opts.seenPresence.has(key)) continue;
    opts.seenPresence.add(key);
    if (ev.event === "CHECK_IN") opts.showClockIn(ev.name);
    else if (ev.event === "CHECK_OUT") opts.showClockOut(ev.name);
  }

  const curIn = new Set(presence.in_office.map((p) => p.name));
  for (const name of curIn) {
    if (!opts.prevIn.has(name)) opts.showClockIn(name);
  }
  for (const name of opts.prevIn) {
    if (!curIn.has(name)) opts.showClockOut(name);
  }
  opts.prevIn.clear();
  for (const n of curIn) opts.prevIn.add(n);
}

function LiveClock() {
  const [t, setT] = useState(now12h);
  useEffect(() => {
    const id = setInterval(() => setT(now12h()), 1000);
    return () => clearInterval(id);
  }, []);
  return <span className="font-mono text-sm text-text-muted">{t}</span>;
}

// SVG animated ring behind camera feed
function PulseRing({ state }: { state: KioskState }) {
  const isRecognizing = state === "recognizing";
  const isSuccess     = state === "clocked_in" || state === "clocked_out";
  const isFail        = state === "unrecognized";

  const color = isRecognizing ? "#3B9EFF"
              : isSuccess     ? "#00D4AA"
              : isFail        ? "#FF5B5B"
              : "#00D4AA";

  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
      <svg
        className="absolute"
        width="66vh"
        height="66vh"
        viewBox="0 0 200 200"
        style={{ maxWidth: "640px", maxHeight: "640px" }}
      >
        <circle
          cx="100" cy="100" r="96"
          fill="none"
          stroke={color}
          strokeWidth="1.5"
          strokeOpacity="0.25"
          className={isRecognizing ? "animate-pulse-ring-fast" : "animate-pulse-ring"}
        />
        <circle
          cx="100" cy="100" r="90"
          fill="none"
          stroke={color}
          strokeWidth={isSuccess || isFail ? 2.5 : 1}
          strokeOpacity={isSuccess || isFail ? 0.8 : 0.4}
        />
        {isSuccess && (
          <circle
            cx="100" cy="100" r="90"
            fill="none"
            stroke={color}
            strokeWidth="2"
            className="animate-ring-expand"
          />
        )}
      </svg>
    </div>
  );
}

function primaryRecognizedName(frame: FrameSnapshot | null): string | null {
  if (!frame?.tracks?.length) return null;
  const tid = frame.primary_track_id;
  const primary =
    (tid != null ? frame.tracks.find((t) => t.id === tid) : null) ??
    frame.tracks[0];
  if (!primary) return null;
  const name = primary.name?.trim();
  if (!name || name === "UNKNOWN") return null;
  return name;
}

export function KioskPage() {
  const { frame, connected, error: wsError } = useWebSocket();
  const [kioskState, setKioskState] = useState<KioskEvent>({ state: "idle" });
  const [statusHint, setStatusHint] = useState("Starting up…");
  const imgSrc = useFrameJpeg();
  const { videoRef, error: cameraError, active: cameraActive } = useDeviceCamera(USE_DEVICE_CAMERA, "front");
  const [showPin, setShowPin] = useState(false);
  const [, setTapCount] = useState(0);
  const tapTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastExitCornerMs = useRef(0);
  const [pinBuffer, setPinBuffer] = useState("");
  const [pinError, setPinError] = useState(false);
  const [kioskPin, setKioskPin] = useState("1234");
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevPresence = useRef<Set<string>>(new Set());
  const seenPresenceEvents = useRef<Set<string>>(new Set());
  const seenAttendanceEvents = useRef<Set<string>>(new Set());
  const httpBootstrapped = useRef(false);
  // Tracks whether we've seeded the presence state (from WS or HTTP — whichever arrives first).
  const presenceSeeded = useRef(false);
  const prevFsm = useRef("");
  // Name-based suppression: after a clock action fires for a person, suppress the
  // "recognizing" transition for that same name until their face disappears from
  // frame.  This prevents the kiosk looping idle → recognizing → (seenAttendanceEvents
  // blocks the event) → idle forever while the person is still standing there.
  // Cleared to null when `primaryRecognizedName` returns null (no face / different face).
  const suppressRecognizingForName = useRef<string | null>(null);

  useEffect(() => {
    fetchSettings().then((s) => { if (s.kiosk_pin) setKioskPin(String(s.kiosk_pin)); }).catch(() => {});
  }, []);

  const scheduleReset = useCallback((ms = 5000) => {
    if (resetTimer.current) clearTimeout(resetTimer.current);
    resetTimer.current = setTimeout(() => setKioskState({ state: "idle" }), ms);
  }, []);

  const showClockIn = useCallback((name: string) => {
    suppressRecognizingForName.current = name;
    setKioskState({ state: "clocked_in", name, time: now12h() });
    scheduleReset();
  }, [scheduleReset]);

  const showClockOut = useCallback((name: string) => {
    suppressRecognizingForName.current = name;
    setKioskState({ state: "clocked_out", name, time: now12h() });
    scheduleReset();
  }, [scheduleReset]);

  // HTTP polling — drives clock-in/out even when WebSocket is slow or empty.
  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const [presence, attendance] = await Promise.all([
          fetchPresence(),
          fetchAttendanceActive(),
        ]);
        if (cancelled) return;

        if (!httpBootstrapped.current) {
          httpBootstrapped.current = true;
          // Only seed presence from HTTP if the WS hasn't already done it.
          if (!presenceSeeded.current) {
            presenceSeeded.current = true;
            applyPresenceClockEvents(presence, {
              bootstrap: true,
              seenPresence: seenPresenceEvents.current,
              prevIn: prevPresence.current,
              showClockIn,
              showClockOut,
            });
          }
          // Seed all historical attendance events so WS duplicates are ignored.
          // For events that just happened (within the recent window) also display
          // them so a clock-in that fired before the page loaded is immediately visible.
          const nowSec = Date.now() / 1000;
          let shownBootstrapEvent = false;
          for (const ev of attendance.recent_events ?? []) {
            const key = attendanceEventKey(ev.name, ev.event, ev.timestamp_ts);
            seenAttendanceEvents.current.add(key);
            if (!shownBootstrapEvent && nowSec - ev.timestamp_ts < BOOTSTRAP_RECENT_WINDOW_SEC) {
              shownBootstrapEvent = true;
              if (ev.event === "CLOCK_IN") showClockIn(ev.name);
              else if (ev.event === "CLOCK_OUT") showClockOut(ev.name);
            }
          }
          if (!shownBootstrapEvent) setStatusHint("Look at the camera to clock in");
          return;
        }

        for (const ev of attendance.recent_events ?? []) {
          const key = attendanceEventKey(ev.name, ev.event, ev.timestamp_ts);
          if (seenAttendanceEvents.current.has(key)) continue;
          seenAttendanceEvents.current.add(key);
          if (ev.event === "CLOCK_IN") showClockIn(ev.name);
          else if (ev.event === "CLOCK_OUT") showClockOut(ev.name);
        }
        // Presence-based clock events are intentionally NOT applied here.
        // The in_office diff fires showClockOut when the presence timeout fires
        // (5 s after absence) — that would show false "clocked out" screens.
        // Attendance events above are the single source of truth for the kiosk.

        const inOffice = presence.in_office?.length ?? 0;
        const clocked = attendance.clocked_in?.length ?? 0;
        if (inOffice > 0 || clocked > 0) {
          setStatusHint("");
        } else {
          setStatusHint("Look at the camera to clock in");
        }
      } catch {
        // Only show the error after the first successful bootstrap;
        // pre-engine warmup 503s are expected and should be silent.
        if (!cancelled && httpBootstrapped.current) {
          setStatusHint("Cannot reach server — is python main.py running?");
        }
      }
    };

    poll();
    const id = setInterval(poll, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [showClockIn, showClockOut]);

  // WebSocket — recognizing / unrecognized UI feedback + fast clock-in detection
  useEffect(() => {
    if (!frame) return;
    const { presence, fsm_state, recent_attendance } = frame;

    // Fast path: attendance events arrive in every WS frame (~12/s).
    // Process them before the 2-second HTTP poll so the kiosk transitions
    // to "clocked in/out" almost immediately after the backend logs the event.
    for (const ev of recent_attendance ?? []) {
      const key = attendanceEventKey(ev.name, ev.event, ev.timestamp_ts);
      if (seenAttendanceEvents.current.has(key)) continue;
      seenAttendanceEvents.current.add(key);
      if (ev.event === "CLOCK_IN") showClockIn(ev.name);
      else if (ev.event === "CLOCK_OUT") showClockOut(ev.name);
    }

    if (!presenceSeeded.current && presence) {
      // Seed from first WS frame so we know who was already in office.
      presenceSeeded.current = true;
      applyPresenceClockEvents(presence, {
        bootstrap: true,
        seenPresence: seenPresenceEvents.current,
        prevIn: prevPresence.current,
        showClockIn,
        showClockOut,
      });
    }
    // Non-bootstrap presence events are NOT forwarded to showClockIn/showClockOut.
    // Presence auto-CHECK_OUT fires 5 s after someone walks away, which would
    // show a false "clocked out" screen.  Attendance events (recent_attendance
    // above) are the sole authoritative source for kiosk clock-in/out display.

    const recognized = primaryRecognizedName(frame);

    // Clear suppression as soon as the face leaves frame (recognized is null)
    // or a different person appears.  This allows the next approach by the same
    // person (after they've physically left) to trigger a fresh action.
    if (!recognized || recognized !== suppressRecognizingForName.current) {
      if (suppressRecognizingForName.current !== null && !recognized) {
        suppressRecognizingForName.current = null;
      }
    }

    // Gate the "recognizing" state: skip if we already fired an action for this
    // person and they haven't left frame yet.  Without this the kiosk resets to
    // "idle" after 5 s, sees the face still there, enters "recognizing" again,
    // but seenAttendanceEvents already has the key → never transitions → loops.
    const suppress = suppressRecognizingForName.current !== null &&
      suppressRecognizingForName.current === recognized;
    if (recognized && kioskState.state === "idle" && !suppress) {
      setKioskState({ state: "recognizing" });
      setStatusHint(`Recognizing ${recognized}…`);
    }

    if (fsm_state === "UNKNOWN" && prevFsm.current !== "UNKNOWN" && !recognized) {
      setKioskState({ state: "unrecognized" });
      scheduleReset();
    }
    if (fsm_state === "DETECTING" && kioskState.state === "idle" && !recognized) {
      setKioskState({ state: "recognizing" });
    }
    if (fsm_state === "IDLE" && kioskState.state === "recognizing" && !recognized) {
      setKioskState({ state: "idle" });
    }

    prevFsm.current = fsm_state;
  }, [frame, kioskState.state, scheduleReset, showClockIn, showClockOut]);

  useEffect(() => {
    if (connected) {
      setStatusHint((h) =>
        h === "Starting up…" || h.startsWith("Cannot") || h.startsWith("Connecting")
          ? "Look at the camera to clock in"
          : h,
      );
    } else if (wsError && !wsError.startsWith("Connecting")) {
      if (httpBootstrapped.current) setStatusHint(wsError);
    } else {
      setStatusHint("Starting up…");
    }
  }, [connected, wsError]);

  // On mobile: update status hint based on device camera state
  useEffect(() => {
    if (!USE_DEVICE_CAMERA) return;
    if (cameraError) {
      setStatusHint(cameraError);
    } else if (!cameraActive) {
      setStatusHint("Allow camera access to continue…");
    } else {
      setStatusHint((h) =>
        h === "Allow camera access to continue…" || h === "Starting up…"
          ? "Look at the camera to clock in"
          : h
      );
    }
  }, [cameraActive, cameraError]);

  const EXIT_TAP_RESET_MS = 1500;

  const registerExitCornerTap = useCallback(() => {
    const now = Date.now();
    if (now - lastExitCornerMs.current < 250) return;
    lastExitCornerMs.current = now;

    setTapCount((prev) => {
      const next = prev + 1;
      if (tapTimer.current) clearTimeout(tapTimer.current);
      if (next >= 3) {
        tapTimer.current = setTimeout(() => setTapCount(0), EXIT_TAP_RESET_MS);
        setShowPin(true);
        return 0;
      }
      tapTimer.current = setTimeout(() => setTapCount(0), EXIT_TAP_RESET_MS);
      return next;
    });
  }, []);

  const handleExitCornerPointerUp = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      e.preventDefault();
      if (e.pointerType === "mouse" && e.button !== 0) return;
      registerExitCornerTap();
    },
    [registerExitCornerTap],
  );

  const handleExitCornerClick = useCallback(
    (e: React.MouseEvent<HTMLButtonElement>) => {
      e.preventDefault();
      registerExitCornerTap();
    },
    [registerExitCornerTap],
  );

  const handlePinKey = useCallback((key: string) => {
    const next = (pinBuffer + key).slice(-4);
    setPinBuffer(next);
    if (next.length === 4) {
      if (next === kioskPin) {
        window.location.href = "/";
      } else {
        setPinError(true);
        setPinBuffer("");
        setTimeout(() => setPinError(false), 1500);
      }
    }
  }, [pinBuffer, kioskPin]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (showPin && /^\d$/.test(e.key)) handlePinKey(e.key);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showPin, handlePinKey]);

  const isTerminal = kioskState.state === "clocked_in" || kioskState.state === "clocked_out" || kioskState.state === "unrecognized";

  return (
    <div className="relative flex h-screen w-screen flex-col items-center justify-between overflow-hidden bg-bg select-none">
      <div className="absolute top-0 left-0 right-0 flex justify-center pt-6 z-10">
        <span className="text-sm font-bold tracking-[0.3em] text-text-muted uppercase">Auty</span>
      </div>

      <div className="relative flex flex-1 items-center justify-center w-full">
        <PulseRing state={kioskState.state} />

        <div
          className={`relative overflow-hidden rounded-2xl border-2 transition-colors duration-300
            ${kioskState.state === "unrecognized" ? "border-danger kiosk-vignette-danger" : "border-border"}
          `}
          style={{ height: "60vh", aspectRatio: "16/9", maxWidth: "min(80vw, 900px)" }}
        >
          {USE_DEVICE_CAMERA ? (
            cameraError ? (
              <div className="flex h-full w-full items-center justify-center bg-surface p-6 text-center">
                <p className="text-sm text-danger">{cameraError}</p>
              </div>
            ) : (
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className="h-full w-full object-cover"
                style={{ transform: "scaleX(-1)" /* mirror front camera */}}
              />
            )
          ) : (
            <img
              src={imgSrc}
              alt="Camera feed"
              className="h-full w-full object-cover"
              onError={(e) => {
                (e.target as HTMLImageElement).src = frameUrl();
              }}
            />
          )}
        </div>
      </div>

      <div className="relative z-10 w-full flex flex-col items-center px-4 pb-8">
        <AnimatePresence mode="wait">
          {kioskState.state === "idle" && (
            <motion.p
              key="idle"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="text-2xl font-medium text-text-secondary text-center"
            >
              {statusHint || "Look at the camera to clock in"}
            </motion.p>
          )}

          {kioskState.state === "recognizing" && (
            <motion.div
              key="recognizing"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="flex items-center gap-3 text-accent-blue"
            >
              <svg className="animate-spin" width="20" height="20" viewBox="0 0 20 20" fill="none">
                <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="2" strokeOpacity="0.3" />
                <path d="M10 2a8 8 0 0 1 8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
              <span className="text-xl font-medium">Recognizing…</span>
            </motion.div>
          )}

          {kioskState.state === "clocked_in" && (
            <motion.div
              key="clocked_in"
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
              transition={{ type: "spring", stiffness: 300, damping: 24 }}
              className="card flex flex-col items-center gap-3 px-10 py-6 text-center max-w-sm w-full"
            >
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent/20 text-accent text-2xl">✓</div>
              <div className="text-[28px] font-bold text-text-primary leading-tight">{kioskState.name}</div>
              <div className="text-sm font-medium text-accent uppercase tracking-wider">Clocked in</div>
              <div className="font-mono text-[40px] font-bold text-accent leading-none">{kioskState.time}</div>
            </motion.div>
          )}

          {kioskState.state === "clocked_out" && (
            <motion.div
              key="clocked_out"
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
              transition={{ type: "spring", stiffness: 300, damping: 24 }}
              className="card flex flex-col items-center gap-3 px-10 py-6 text-center max-w-sm w-full"
            >
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent-blue/20 text-accent-blue text-2xl">👋</div>
              <div className="text-[28px] font-bold text-text-primary leading-tight">{kioskState.name}</div>
              <div className="text-sm font-medium text-text-secondary uppercase tracking-wider">Clocked out</div>
              <div className="font-mono text-[40px] font-bold text-text-primary leading-none">{kioskState.time}</div>
              <div className="text-sm text-text-secondary">Have a great day!</div>
            </motion.div>
          )}

          {kioskState.state === "unrecognized" && (
            <motion.div
              key="unrecognized"
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
              transition={{ type: "spring", stiffness: 300, damping: 24 }}
              className="flex flex-col items-center gap-2 text-center"
            >
              <div className="text-2xl font-bold text-danger">Face not recognized</div>
              <div className="text-text-secondary">Please see your manager</div>
            </motion.div>
          )}
        </AnimatePresence>

        {isTerminal && (
          <div className="mt-4 w-full max-w-sm overflow-hidden rounded-full bg-bg-elevated h-1">
            <motion.div
              className={`h-full ${kioskState.state === "unrecognized" ? "bg-danger" : "bg-accent"}`}
              initial={{ width: "100%" }}
              animate={{ width: "0%" }}
              transition={{ duration: 5, ease: "linear" }}
            />
          </div>
        )}
      </div>

      <div className="absolute bottom-4 right-4 z-10">
        <LiveClock />
      </div>

      <button
        type="button"
        onPointerUp={handleExitCornerPointerUp}
        onClick={handleExitCornerClick}
        aria-label="Manager access"
        className="absolute top-0 right-0 z-[60] min-h-[80px] min-w-[80px] h-20 w-20 touch-manipulation opacity-0"
      />

      <AnimatePresence>
        {showPin && (
          <motion.div
            key="pin"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 z-50 flex flex-col items-center justify-center gap-6 bg-bg/95 backdrop-blur"
          >
            <div className="text-text-secondary text-xs font-medium uppercase tracking-widest mb-2">Manager Access</div>
            <div className="flex gap-3">
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  className={`h-4 w-4 rounded-full border-2 transition-colors ${
                    pinBuffer.length > i ? "bg-accent border-accent" : "border-border"
                  }`}
                />
              ))}
            </div>
            {pinError && (
              <motion.p
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-sm text-danger"
              >
                Incorrect PIN
              </motion.p>
            )}
            <div className="grid grid-cols-3 gap-3 mt-2">
              {[1, 2, 3, 4, 5, 6, 7, 8, 9, null, 0, "⌫"].map((n, i) =>
                n === null ? (
                  <div key={i} />
                ) : (
                  <button
                    key={i}
                    onClick={() => {
                      if (n === "⌫") setPinBuffer((b) => b.slice(0, -1));
                      else handlePinKey(String(n));
                    }}
                    className="h-16 w-16 rounded-xl border border-border bg-bg-elevated text-2xl font-semibold text-text-primary hover:bg-bg-elevated hover:border-accent/40 hover:text-accent transition-colors"
                  >
                    {n}
                  </button>
                )
              )}
            </div>
            <button
              onClick={() => { setShowPin(false); setPinBuffer(""); }}
              className="mt-4 text-sm text-text-muted hover:text-text-secondary transition-colors"
            >
              Cancel
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
