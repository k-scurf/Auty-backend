# Enrollment

## Guided enrollment (recommended)

1. Dashboard auto-starts capture when a stable **unknown** face appears (or `POST /api/enrollment/start`).
2. Follow pose prompts (front, left, right, up, down). Quality gates reject blur; pose bands are **relaxed during capture only**.
3. Progress over WebSocket: `enrollment_progress` (`captured`, `min_auto`, `target`).

### Partial / security desk enroll

You do **not** need all 25 photos.

| Setting | Default | Meaning |
|---------|---------|---------|
| `enrollment_min_auto_save` | 8 | Auto-commit to DB and start recognition |
| `enrollment_target_total` | 25 | Ideal progress denominator (UI) |
| `enrollment_relaxed_pose` | true | Wider yaw tolerance while capturing |
| `quality_min_enroll_capture` | 55 | Capture quality bar (live recognition stays stricter) |
| `enrollment_phase_timeout_sec` | 12 | Skip a stuck pose after this many seconds |
| `enrollment_provisional_prefix` | Guest | Auto name before optional rename |

After **8** good samples, Auty:

1. Saves embeddings as `Guest-{trackId}` (e.g. `Guest-3`)
2. Locks the track immediately so recognition works in the same session
3. Opens an **optional** name wizard (Skip keeps the guest name)

Rename: saving a different name in the wizard calls `rename_profile` (same embeddings, new display name).

Matching uses **all** stored embeddings (max score per person), with a slightly stricter threshold when fewer than `enrollment_min_auto_save` samples were collected (`sparse_enroll` calibration).

API: `GET /api/enrollment/status`, `POST /api/enrollment/cancel`.

**Debug → Security desk** preset applies the recommended enrollment settings.

## Legacy auto-capture

When guided mode is off, a stable **unknown** face triggers silent sample collection and the enroll modal.

## Save profile

- Captures a reference image to `data/captures/{name}.jpg`
- Writes metadata to `data/profiles.json`
- Stores embeddings under `data/identities/{uuid}/`
- Response engine records a social memory event

## Tips

- Face the camera with even lighting
- Fill in **Status** (e.g. `FRIEND`, `OWNER`) for greeting tier
- After auto-enroll, the same person should show as `Guest-N` within a few frames

## Skip

**Not now** / **Skip** sets a cooldown so enrollment does not immediately restart.

## Ghost boxes / false enroll prompts

Auty only shows tracks and starts enrollment when `track_require_verified_det` is true: a strict InsightFace detection with valid landmarks, score, and quality. Unverified ByteTrack coasting boxes are removed within ~2 frames. Restart `python main.py` after changing settings.
