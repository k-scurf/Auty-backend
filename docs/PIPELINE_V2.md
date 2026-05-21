# Pipeline v2 — Strict desk profile

InsightFace detection + verification, ByteTrack, gallery matching with hysteresis locks.

## Strict mode (`detection_mode: strict`)

Designed for **1–2 people at a desk** with **no false boxes** and **no false UNKNOWN** for enrolled users.

| Layer | Behavior |
|-------|----------|
| Detect | Full-resolution (`detect_full_resolution`), `det_thresh` 0.62+, landmark geometry check, NMS |
| No Haar fallback | Empty frame preferred over phantom boxes |
| Match | Precomputed gallery matrix; per-person threshold from enrollment calibration |
| Lock | **Retain** ≥ 0.40 keeps enrolled ID; **release** &lt; 0.32 for N frames before UNKNOWN |
| Unknown alerts | Only if best gallery score &lt; `unknown_alert_max` (0.35) — suppresses “almost matched” alerts |

## Key settings

See [`config/pipeline.example.json`](../config/pipeline.example.json). Apply presets from **Debug** page (`/debug`) or merge into `data/settings.json`.

## Mac tuning

- `buffalo_l` + `insightface_det_size: 640` for accuracy
- `buffalo_sc` + `320` if CPU-bound (looser strictness may be needed)
- `detect_interval_frames: 15` — balance FPS vs box freshness

## Persistence

Set `reset_db_each_run: false` so identities survive restarts (`data/identities/`).

## Debug metrics (WebSocket `tracks[]`)

- `quality_score`, `blur_score`, `vote_ratio`, `distance`
- `lock_state`, `match_margin`, `reject_reason`, `best_candidate`

## Migration

```bash
python scripts/migrate_identity_v2.py
```
