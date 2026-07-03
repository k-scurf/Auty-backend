export interface Track {
  id: number;
  bbox: [number, number, number, number];
  name: string;
  confidence: number;
  known: boolean;
  stability_pct: number;
  quality_score?: number;
  blur_score?: number;
  vote_ratio?: number;
  distance?: number | null;
  pose_yaw?: number;
  lock_state?: string;
  match_margin?: number;
  reject_reason?: string;
  best_candidate?: string;
}

export interface LogEntry {
  ts: number;
  type: string;
  name?: string;
  confidence?: number;
  track_id?: number;
  detail?: string;
}

export interface EnrollmentPending {
  ready: boolean;
  track_id?: number;
  image_b64?: string;
}

export interface EnrollmentProgress {
  active: boolean;
  phase: string;
  instruction: string;
  captured: number;
  target: number;
  min_auto?: number;
  min_ready?: number;
  percent: number;
  rejected_blur: number;
  rejected_quality?: number;
  rejected_pose?: number;
  rejected_embed?: number;
  tick_count?: number;
  last_reject_reason?: string | null;
  ready_to_save: boolean;
  preview_b64?: string | null;
  auto_committed?: boolean;
  provisional_name?: string | null;
  phase_counts?: Record<string, number>;
  phase_targets?: Record<string, number>;
  phases?: string[];
  // Backend pose-guide stability state (vision/enrollment_pose_guide.py)
  pose_target?: string | null;
  stability_progress?: number;
  ready_to_capture?: boolean;
  // Reason-specific guidance — what's blocking capture right now, if anything
  live_message?: string;
  face_visible?: boolean;
}

// ---------------------------------------------------------------------------
// Attendance / Payroll
// ---------------------------------------------------------------------------

export interface ActiveEmployee {
  employee_id: string;
  name: string;
  clock_in_ts: number;
  clock_in_utc: string;
  duration_seconds: number;
  location_id: string;
}

export interface AttendanceEvent {
  id: string;
  employee_id: string;
  name: string;
  event: "CLOCK_IN" | "CLOCK_OUT";
  timestamp_utc: string;
  timestamp_ts: number;
  location_id: string;
  confidence: number;
  device_id: string;
  snapshot_path?: string | null;
}

export interface AttendanceAlert {
  type: string;
  name: string;
  ts: number;
  detail: string;
}

export interface AttendanceStatus {
  clocked_in: ActiveEmployee[];
  recent_events: AttendanceEvent[];
  alerts: AttendanceAlert[];
}

export type AttendanceStatusValue =
  | "on_time"
  | "late"
  | "absent"
  | "complete"
  | "missing_clockout"
  | "no_schedule"
  | "day_off";

export interface ScheduleDay {
  working: boolean;
  start?: string | null;
  end?: string | null;
}

export interface WeeklySchedule {
  employee_id: string;
  name?: string;
  timezone: string;
  days: Record<string, ScheduleDay>;
}

export interface TodayAttendanceRow {
  employee_id: string;
  name: string;
  status: AttendanceStatusValue;
  shift_start?: string | null;
  shift_end?: string | null;
  timezone: string;
  clock_in_ts?: number | null;
  clock_out_ts?: number | null;
  clock_in_time?: string | null;
  clock_out_time?: string | null;
  hours?: number | null;
  has_schedule: boolean;
  day_off: boolean;
  alert?: string | null;
}

export interface TodayAttendanceStatus {
  date: string;
  timezone: string;
  rows: TodayAttendanceRow[];
}

export interface ExportPreview {
  row_count: number;
  total_hours: number;
  employee_count: number;
  format: string;
  start_date: string;
  end_date: string;
}

export interface FrameCheckResult {
  face_detected: boolean;
  face_count: number;
  lighting_ok: boolean;
  centered: boolean;
  message: string;
}

export interface EnrollmentErrorDetail {
  code: string;
  message: string;
  photo_index?: number;
  confidence?: number;
  action: string;
}

// ---------------------------------------------------------------------------
// Presence (legacy — kept for compatibility with PresenceTracker backend)
// ---------------------------------------------------------------------------

export interface PresencePerson {
  name: string;
  status: string;
  since_ts: number;
  last_seen_ts: number;
  confidence_avg?: number | null;
}

export interface PresenceActivity {
  name: string;
  last_seen_ts: number;
  event: string;
}

export interface PresenceSnapshot {
  in_office: PresencePerson[];
  recent_activity: PresenceActivity[];
  today_totals: Record<string, number>;
  events_tail?: PresenceActivity[];
}

// ---------------------------------------------------------------------------
// WebSocket frame
// ---------------------------------------------------------------------------

export interface FrameSnapshot {
  frame_count: number;
  fps: number;
  fsm_state: string;
  mood: string;
  status_line: string;
  primary_track_id: number | null;
  tracks: Track[];
  log_tail: LogEntry[];
  enrollment: EnrollmentPending;
  enrollment_progress?: EnrollmentProgress;
  presence?: PresenceSnapshot | null;
  recent_attendance?: AttendanceEvent[];
  frame_width: number;
  frame_height: number;
  process_fps?: number;
  camera_fps?: number;
}

export interface HealthStatus {
  engine_ready?: boolean;
  camera_ok: boolean;
  db_loaded: boolean;
  face_count: number;
  profile_count: number;
  fps: number;
  uptime: number;
  frame_count: number;
}

export interface Profile {
  id?: string | null;
  name: string;
  age: string;
  status: string;
  image?: string | null;
  enrolled_at?: string | null;
}
