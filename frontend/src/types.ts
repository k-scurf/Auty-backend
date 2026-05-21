export interface Track {
  id: number;
  bbox: [number, number, number, number];
  name: string;
  confidence: number;
  known: boolean;
  stability_pct: number;
  user_emotion?: string | null;
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
  ready_to_save: boolean;
  preview_b64?: string | null;
  auto_committed?: boolean;
  provisional_name?: string | null;
}

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
