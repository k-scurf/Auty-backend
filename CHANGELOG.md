# Changelog

All notable changes to the Auty backend are documented here, most recent first.

## 2026-07-03
- Added guided ("Face ID style") pose-capture enrollment: head yaw/pitch/roll
  tracking with hold-steady stability gating per pose step, reason-specific
  live guidance (lighting/blur/size/no-face), a client-camera enrollment-frame
  endpoint, and a provisional-identity rename endpoint.
- Client-frame recognition now shares the same detection path and thresholds
  as enrollment, with aspect-ratio-preserving downscaling instead of
  stretching.
- Added a client-side brightness gate that skips frames too dark for reliable
  recognition.
- The iPad HTTPS URL now auto-detects the LAN IP instead of using a
  hardcoded address.
- Added an employee weekly Schedule page (manual per-day hours grid) with a
  Schedules nav entry.

## 2026-06-03
- Fixed face recognition in poor lighting: lowered the match threshold,
  added multi-photo enrollment, and gated capture on brightness.

## 2026-06-02
- Fixed a crash when deleting an employee and added CLAHE lighting
  normalisation to the recognition pipeline.
- Client frames are now downscaled to pipeline resolution before processing.
- Removed the live camera feed and preview from the dashboard.

## 2026-06-01
- Hardened security: fixed 16 vulnerabilities across auth, API, and storage
  layers.

## 2026-05-30
- Added PostgreSQL multi-tenant storage and JWT authentication.
- Fixed the admin-secret header alias to match the HTTP wire format.

## 2026-05-28
- Fixed profile delete and synced the frontend kiosk and enrollment UI.
- Fixed a Railway OOM crash loop during InsightFace load.
- Skipped the local webcam on Railway and other headless deploys.
- Switched to headless OpenCV and installed the runtime apt libs needed for
  deploy.
- Updated the CORS allowlist to production Auty domains.
- Exposed the ASGI app in the main module and allowed the Vercel origin.
- Pinned Python 3.11 for backend builds and ensured pip build tooling is
  present.

## 2026-05-27
- Pinned Python 3.11 for Railpack via `.python-version`.

## 2026-05-20
- Added the vision pipeline v2, FastAPI/React dashboard, and security
  enrollment flow.

## 2026-05-19
- Initial commit: Auty real-time facial recognition with event AI.
