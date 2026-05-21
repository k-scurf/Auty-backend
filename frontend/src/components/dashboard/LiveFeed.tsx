import { memo, useEffect, useRef, useState } from "react";
import type { FrameSnapshot } from "../../types";
import { frameUrl } from "../../services/api";

interface Props {
  frame: FrameSnapshot | null;
}

function drawTracks(
  ctx: CanvasRenderingContext2D,
  frame: FrameSnapshot,
  scaleX: number,
  scaleY: number
) {
  const fw = frame.frame_width || 960;
  const fh = frame.frame_height || 540;
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);

  for (const t of frame.tracks) {
    const [x, y, w, h] = t.bbox;
    const sx = (x / fw) * scaleX;
    const sy = (y / fh) * scaleY;
    const sw = (w / fw) * scaleX;
    const sh = (h / fh) * scaleY;
    const known = t.known;
    ctx.strokeStyle = known
      ? "rgba(45, 212, 191, 0.85)"
      : "rgba(251, 146, 60, 0.9)";
    ctx.lineWidth = 2;
    ctx.strokeRect(sx, sy, sw, sh);
    const label = known
      ? `${t.name} ${Math.round(t.confidence * 100)}%`
      : "UNKNOWN";
    ctx.fillStyle = known
      ? "rgba(45, 212, 191, 0.9)"
      : "rgba(251, 146, 60, 0.95)";
    ctx.font = "12px Inter, sans-serif";
    ctx.fillText(label, sx + 4, Math.max(14, sy - 6));
  }
}

/** ~20 FPS — MJPEG in <img> is broken in Chrome/Safari; poll JPEG instead. */
const FRAME_MS = 50;

function LiveFeedInner({ frame }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const lastCountRef = useRef(-1);
  const [imgSrc, setImgSrc] = useState(() => frameUrl());

  useEffect(() => {
    let active = true;
    const tick = () => {
      if (active) setImgSrc(frameUrl());
    };
    tick();
    const id = window.setInterval(tick, FRAME_MS);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (!frame || frame.frame_count === lastCountRef.current) return;
    lastCountRef.current = frame.frame_count;
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;

    const rect = wrap.getBoundingClientRect();
    if (canvas.width !== rect.width || canvas.height !== rect.height) {
      canvas.width = rect.width;
      canvas.height = rect.height;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    drawTracks(ctx, frame, rect.width, rect.height);
  }, [frame]);

  return (
    <div
      ref={wrapRef}
      className="relative aspect-video w-full overflow-hidden rounded-xl border border-border bg-black"
    >
      <img
        src={imgSrc}
        alt="Live camera"
        className="h-full w-full object-contain"
        draggable={false}
      />
      <canvas
        ref={canvasRef}
        className="pointer-events-none absolute inset-0 h-full w-full"
      />
    </div>
  );
}

export const LiveFeed = memo(LiveFeedInner);
