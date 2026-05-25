# Auty architecture (event-driven)

Perception modules emit **typed events** on the main thread. The **state machine** and **response engine** subscribe via `EventBus`; only the response engine drives HUD, TTS, memory lines, and UI effects.

## Pipeline (each camera frame)

1. `camera.CameraStream.read()` — flip + resize to 960×540
2. `tracking.FaceTrackManager.step()` — detect + track
3. Recognition worker poll / throttled `recognize_track`
4. Emit lifecycle events: `FaceDetected`, `FaceLost`
5. Emit identity events: `FaceRecognized`, `UnknownFaceDetected` (when stable)
6. `attention.AttentionManager.select_primary()` → `AttentionShifted`
7. `EventBus.drain()` → `StateMachine.process_events()` → `dispatch()`
8. `ResponseEngine.process_frame()` → HUD + effects + Tk panel

## AI states (`state_machine.AIState`)

| State | Meaning |
|-------|---------|
| `IDLE` | No face (after timeout) |
| `DETECTING` | Face present, identity not settled |
| `RECOGNIZED` | Known person stable |
| `UNKNOWN` | Unknown face stable |
| `ALERT` | Unknown face persisted past alert timer |
| `ENGAGED` | Greeting / conversation window |

Transitions are timer-driven (`settings.json` → `ai_states`) and event-driven (see `StateMachine`).

## Events (`event_system.py`)

- `FaceDetected`, `FaceLost`
- `FaceRecognized`, `UnknownFaceDetected`
- `AttentionShifted`
- `StateChanged`
- `InteractionStarted`, `UserCommandIntent`

## Adding a response rule

1. Subscribe in `ResponseEngine.__init__` via `event_bus.subscribe(...)` or handle in `_on_event`.
2. Update `ResponseContext` fields used by `ui_overlay.HUDRenderer`.
3. Do **not** add HUD/TTS calls in `main.py` or perception modules.

## Modules

| Module | Role |
|--------|------|
| `camera.py` | Capture + resize |
| `detector.py` / `face_detection.py` | Haar + validation |
| `tracker.py` / `tracking.py` | Multi-face tracks |
| `recognition.py` + `recognition_worker.py` | ArcFace identity |
| `event_system.py` | Event bus |
| `state_machine.py` | 6-state FSM |
| `attention.py` | Primary face selection |
| `memory.py` | Profiles + social memory facade |
| `response_engine.py` | HUD, voice, LLM hook |
| `main.py` | Tk shell + frame loop |

## Settings

Configuration lives in `data/settings.json` (copy from `config/settings.example.json`). Runtime data is under `data/` — see [DATABASE.md](DATABASE.md).

- `event_system_enabled` — master switch for bus/FSM path
- `ai_states.*` — FSM timers
- `async_recognition`, `recognition_locked_seconds` — performance (unchanged)

## Optional LLM

`response_engine.LlmResponseHandler` wraps `local_conversation.LocalConversation` and runs async replies after greet when `local_llm_enabled` is true and state is `ENGAGED`.

## Behavioral layers (sequences, timing, personality)

| Module | Role |
|--------|------|
| `behavior_sequence_engine.py` | Multi-step flows with inter-step delays (e.g. recognize → UI → greet → memory → ENGAGED) |
| `attention_manager.py` | `primary_track_id` + `secondary_track_ids`; size, center, recency, unknown penalty |
| `timing_controller.py` | Per-face/session timers; suggests DETECTING / ENGAGED / IDLE / gradual UNKNOWN→ALERT |
| `personality_rules.py` | State → tone, UI motion, greeting delay, speak gating |
| `response_throttler.py` | Greeting cooldown, voice gap, duplicate event suppression |

**Integration:** `main.update_camera()` → `timing_controller.update()` → `attention_manager.select()` → `response_engine.set_frame_context(primary=…)` → events/FSM → `response_engine.process_frame()` → `sequences.tick()`.

Only the **primary** track triggers `face_recognized` greeting sequences. Settings: `behavior_timing`, `behavior_throttle` in `settings.json`.
