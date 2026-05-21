import axios from "axios";
import type { FrameSnapshot, HealthStatus, LogEntry, Profile } from "../types";

const baseURL = import.meta.env.VITE_API_URL || "";

export const api = axios.create({ baseURL, timeout: 15000 });

export async function fetchHealthSoft(): Promise<HealthStatus> {
  const { data } = await api.get("/api/health/status");
  return {
    engine_ready: data.engine_ready ?? true,
    camera_ok: data.camera_ok,
    db_loaded: data.db_loaded,
    face_count: data.face_count ?? 0,
    profile_count: data.profile_count ?? 0,
    fps: data.fps ?? 0,
    uptime: data.uptime ?? 0,
    frame_count: data.frame_count ?? 0,
  };
}

export async function fetchLogs(): Promise<LogEntry[]> {
  const { data } = await api.get<LogEntry[]>("/api/logs");
  return data;
}

export async function fetchAlerts(): Promise<LogEntry[]> {
  const { data } = await api.get<LogEntry[]>("/api/alerts");
  return data;
}

export async function fetchProfiles(): Promise<Profile[]> {
  const { data } = await api.get<Profile[]>("/api/profiles");
  return data;
}

export async function fetchSettings(): Promise<Record<string, unknown>> {
  const { data } = await api.get("/api/settings");
  return data;
}

export async function patchSettings(
  settings: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const { data } = await api.patch("/api/settings", { settings });
  return data;
}

export async function enrollProfile(payload: {
  name: string;
  age: string;
  status: string;
  image_b64?: string;
}): Promise<void> {
  await api.post("/api/profiles", payload);
}

export async function skipEnrollment(): Promise<void> {
  await api.post("/api/enrollment/skip");
}

export async function startEnrollment(trackId?: number): Promise<void> {
  await api.post("/api/enrollment/start", null, {
    params: trackId != null ? { track_id: trackId } : {},
  });
}

export async function cancelEnrollment(): Promise<void> {
  await api.post("/api/enrollment/cancel");
}

export function profilePhotoUrl(name: string): string {
  return `${baseURL}/api/profiles/${encodeURIComponent(name)}/photo`;
}

export function streamUrl(): string {
  return `${baseURL}/api/stream.mjpg`;
}

/** Single-frame JPEG (Chrome/Safari-safe live preview). */
export function frameUrl(): string {
  return `${baseURL}/api/frame.jpg?t=${Date.now()}`;
}

export function wsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  if (import.meta.env.DEV) {
    return `${proto}//${window.location.host}/api/ws`;
  }
  const base = baseURL || `${window.location.protocol}//${window.location.host}`;
  const u = new URL(base);
  return `${proto}//${u.host}/api/ws`;
}

export type { FrameSnapshot };
