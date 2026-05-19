# Enrollment

When Auty sees a stable **unknown** face, the right panel offers enrollment.

## Flow

1. Unknown track reaches stable recognition state → `UnknownFaceDetected` event.
2. Side panel shows preview and fields: **Name**, **Age**, **Status**.
3. User clicks **Save profile** or **Not now**.

## Save profile

- Captures a reference image to `data/captures/{name}.jpg`
- Writes metadata to `data/profiles.json`
- Appends embeddings from collected samples to `data/face_db.pkl`
- Response engine records a social memory event

## Samples

While unknown, the app collects multiple face crops (`ENROLL_SAMPLE_COUNT`, gap frames) to improve embedding quality before save.

## Tips

- Face the camera with even lighting
- Fill in **Status** (e.g. `FRIEND`, `OWNER`) for greeting tier
- After enrollment, the same person should lock as recognized within a few frames

## Skip

**Not now** sets a cooldown so the panel does not immediately re-open for the same session.
