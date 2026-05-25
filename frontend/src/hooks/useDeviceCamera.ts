/**
 * useDeviceCamera
 *
 * Manages the device's camera stream (getUserMedia) and periodically sends
 * frames to /api/recognize-frame for server-side face recognition.
 *
 * Returns:
 *   videoRef  – attach to a <video> element to show the live feed
 *   error     – friendly error message when camera access fails
 *   active    – true once the stream is live
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../services/api";

const CAPTURE_INTERVAL_MS = 800; // ~1.25 fps — enough for recognition, keeps CPU/network low
const JPEG_QUALITY = 0.7;

export interface DeviceCameraState {
  videoRef: React.RefObject<HTMLVideoElement>;
  error: string | null;
  active: boolean;
}

export function useDeviceCamera(
  enabled: boolean,
  preference: "front" | "back" | "auto" = "front"
): DeviceCameraState {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState(false);

  const stopAll = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setActive(false);
  }, []);

  const captureAndSend = useCallback(async () => {
    const video = videoRef.current;
    if (!video || video.readyState < 2) return;
    if (!canvasRef.current) {
      canvasRef.current = document.createElement("canvas");
    }
    const canvas = canvasRef.current;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0);
    canvas.toBlob(
      async (blob) => {
        if (!blob) return;
        const form = new FormData();
        form.append("file", blob, "frame.jpg");
        try {
          await api.post("/api/recognize-frame", form, {
            headers: { "Content-Type": "multipart/form-data" },
          });
        } catch {
          // Silently swallow — network blips shouldn't kill the camera feed
        }
      },
      "image/jpeg",
      JPEG_QUALITY
    );
  }, []);

  useEffect(() => {
    if (!enabled) {
      stopAll();
      return;
    }

    let cancelled = false;

    const facingMode =
      preference === "front"
        ? "user"
        : preference === "back"
        ? "environment"
        : undefined;

    const constraints: MediaStreamConstraints = {
      video: {
        ...(facingMode ? { facingMode: { ideal: facingMode } } : {}),
        width: { ideal: 1280 },
        height: { ideal: 720 },
      },
    };

    navigator.mediaDevices
      .getUserMedia(constraints)
      .then((stream) => {
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.onloadedmetadata = () => {
            videoRef.current?.play().catch(() => {});
            setActive(true);
            timerRef.current = setInterval(captureAndSend, CAPTURE_INTERVAL_MS);
          };
        }
      })
      .catch((err: DOMException) => {
        if (cancelled) return;
        if (err.name === "NotAllowedError") {
          setError(
            "Camera access denied. Please allow camera access in Safari settings and refresh."
          );
        } else if (err.name === "NotFoundError") {
          setError("No camera found on this device.");
        } else if (err.name === "NotReadableError") {
          setError("Camera is in use by another app. Close other apps and refresh.");
        } else if (err.name === "SecurityError") {
          setError(
            "Camera blocked — this page must be served over HTTPS. " +
              "Connect via https://192.168.1.100:8000 and install the root certificate."
          );
        } else {
          setError(`Camera error: ${err.message}`);
        }
      });

    return () => {
      cancelled = true;
      stopAll();
    };
  }, [enabled, preference, captureAndSend, stopAll]);

  return { videoRef, error, active };
}
