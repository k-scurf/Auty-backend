import axios from "axios";
import type {
  AttendanceEvent,
  AttendanceStatus,
  ExportPreview,
  FrameCheckResult,
  FrameSnapshot,
  HealthStatus,
  LogEntry,
  Profile,
  TodayAttendanceStatus,
  WeeklySchedule,
} from "../types";

const baseURL = import.meta.env.VITE_API_URL || "";

export const api = axios.create({ baseURL, timeout: 15000 });

export async function fetchHealthSoft(): Promise<HealthStatus> {
  const { data } = await api.get("/api/health/status");
  return {
    engine_ready: data.engine_ready ?? false,
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
  /** Base-64 JPEG data-URLs from the device-camera 3-photo flow. */
  images?: string[];
  allow_low_confidence?: boolean;
}): Promise<void> {
  await api.post("/api/profiles", payload);
}

/**
 * Send a single frame (base-64 data-URL) to the backend and get back three
 * boolean quality signals for the enrollment capture wizard.
 */
export async function checkEnrollmentFrame(
  imageDataUrl: string
): Promise<FrameCheckResult> {
  const { data } = await api.post<FrameCheckResult>(
    "/api/camera/check-frame",
    { image_b64: imageDataUrl },
    { timeout: 2000 }
  );
  return data;
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

export async function fetchEnrollmentStatus(): Promise<import("../types").EnrollmentProgress> {
  const { data } = await api.get("/api/enrollment/status");
  return data;
}

export async function renameProvisionalEnrollment(name: string): Promise<{ ok: boolean; name: string }> {
  const { data } = await api.post("/api/enrollment/rename", { name });
  return data;
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

// ---------------------------------------------------------------------------
// Attendance
// ---------------------------------------------------------------------------

export async function fetchAttendanceActive(): Promise<AttendanceStatus> {
  const { data } = await api.get("/api/attendance/active");
  return data;
}

export async function fetchTodayAttendanceStatus(): Promise<TodayAttendanceStatus> {
  const { data } = await api.get<TodayAttendanceStatus>("/api/attendance/status/today");
  return data;
}

export async function fetchSchedule(employeeId: string): Promise<WeeklySchedule> {
  const { data } = await api.get<WeeklySchedule>(
    `/api/schedules/${encodeURIComponent(employeeId)}`
  );
  return data;
}

export async function saveSchedule(
  employeeId: string,
  schedule: WeeklySchedule
): Promise<WeeklySchedule> {
  const { data } = await api.post<WeeklySchedule>(
    `/api/schedules/${encodeURIComponent(employeeId)}`,
    schedule
  );
  return data;
}

export async function fetchPresence(): Promise<import("../types").PresenceSnapshot> {
  const { data } = await api.get("/api/presence");
  return data;
}

export async function fetchAttendanceEvents(params?: {
  start_date?: string;
  end_date?: string;
  employee?: string;
  location_id?: string;
}): Promise<AttendanceEvent[]> {
  const { data } = await api.get("/api/attendance/events", { params });
  return data;
}

export async function addAttendanceNote(payload: {
  event_id: string;
  note: string;
  manager?: string;
}): Promise<void> {
  await api.post("/api/attendance/notes", payload);
}

export async function fetchExportPreview(params: {
  format: string;
  start_date: string;
  end_date: string;
  location_id?: string;
}): Promise<ExportPreview> {
  const { data } = await api.get("/api/attendance/export/preview", { params });
  return data;
}

export async function downloadExport(payload: {
  format: string;
  start_date: string;
  end_date: string;
  location_id?: string;
}): Promise<Blob> {
  const { data } = await api.post("/api/attendance/export", payload, {
    responseType: "blob",
  });
  return data;
}

// ---------------------------------------------------------------------------
// Consent
// ---------------------------------------------------------------------------

export async function recordConsent(payload: {
  employee_id: string;
  name: string;
  ip_address?: string;
  form_version?: string;
}): Promise<void> {
  await api.post("/api/consent", payload);
}

export async function fetchConsentStatus(
  employeeId: string
): Promise<{ employee_id: string; consented: boolean; timestamp_utc?: string }> {
  const { data } = await api.get(`/api/consent/${encodeURIComponent(employeeId)}`);
  return data;
}

export async function requestDataDeletion(employeeId: string): Promise<void> {
  await api.post(`/api/consent/${encodeURIComponent(employeeId)}/delete`);
}

/** Remove one employee's profile and biometric data from the server. */
export async function deleteProfile(profileId: string): Promise<void> {
  await api.delete(`/api/profiles/${encodeURIComponent(profileId)}`);
}

export async function resetAllProfiles(): Promise<void> {
  await api.post("/api/profiles/reset-all");
}

// ---------------------------------------------------------------------------
// Audit log
// ---------------------------------------------------------------------------

export interface AuditEntry {
  ts: string;
  action: string;
  manager?: string;
  detail?: string;
}

export async function fetchAuditLog(limit = 50): Promise<AuditEntry[]> {
  const { data } = await api.get<{ timestamp_utc: string; action: string; actor?: string; detail?: string }[]>(
    "/api/audit",
    { params: { limit } },
  );
  return data.map((e) => ({ ts: e.timestamp_utc, action: e.action, manager: e.actor, detail: e.detail }));
}

export type { FrameSnapshot, AttendanceStatus, ExportPreview, FrameCheckResult };
