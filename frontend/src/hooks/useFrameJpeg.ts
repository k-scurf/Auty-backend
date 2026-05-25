import { useEffect, useState } from "react";
import { frameUrl } from "../services/api";

/** Target preview rate when the tab is visible. */
const INTERVAL_MS = 200;
const HIDDEN_INTERVAL_MS = 800;

type Listener = (url: string) => void;

let listeners = new Set<Listener>();
let timer: ReturnType<typeof setTimeout> | null = null;
let inFlight = false;
let lastUrl = "";

function schedule() {
  if (listeners.size === 0) {
    if (timer) clearTimeout(timer);
    timer = null;
    return;
  }
  const delay = document.hidden ? HIDDEN_INTERVAL_MS : INTERVAL_MS;
  timer = setTimeout(fetchNext, delay);
}

function fetchNext() {
  if (listeners.size === 0 || inFlight) return;
  inFlight = true;
  const url = frameUrl();
  const img = new Image();
  img.onload = () => {
    inFlight = false;
    lastUrl = url;
    listeners.forEach((fn) => fn(url));
    schedule();
  };
  img.onerror = () => {
    inFlight = false;
    schedule();
  };
  img.src = url;
}

function subscribe(fn: Listener) {
  listeners.add(fn);
  if (lastUrl) fn(lastUrl);
  else fn(frameUrl());
  if (!timer && !inFlight) fetchNext();
  return () => {
    listeners.delete(fn);
    if (listeners.size === 0 && timer) {
      clearTimeout(timer);
      timer = null;
    }
  };
}

/** One shared JPEG poller for the whole app (avoids N tabs × 6 connections). */
export function useFrameJpeg(): string {
  const [src, setSrc] = useState(lastUrl || frameUrl());

  useEffect(() => {
    const unsub = subscribe(setSrc);
    const onVis = () => {
      if (!document.hidden && listeners.size > 0 && !timer && !inFlight) {
        fetchNext();
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      unsub();
    };
  }, []);

  return src;
}
