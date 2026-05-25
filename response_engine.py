"""
Centralized response engine — subscribes to events and drives UI, voice, memory, effects.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from behavior_sequence_engine import BehaviorSequenceEngine, SequenceStep
from event_system import (
    AttentionShifted,
    Event,
    EventBus,
    FaceDetected,
    FaceLost,
    FaceRecognized,
    InteractionStarted,
    StateChanged,
    UnknownFaceDetected,
    UserCommandIntent,
)
from local_conversation import LocalConversation
from personality_engine import Mood, PersonalityEngine
from personality_rules import PersonalityRules
from response_throttler import ResponseThrottler
from state_machine import AIState, StateMachine
from ui.theme import HUD_KNOWN, HUD_UNKNOWN
from ui_effects import UIEffects
from voice_system import VoiceSystem


class LlmResponseHandler:
    """Optional hook for ENGAGED-state LLM replies (wraps LocalConversation)."""

    def __init__(self, settings: dict):
        self.settings = settings
        self.llm = LocalConversation(settings)
        self._checked = False
        self._available = False

    def available(self) -> bool:
        if not self._checked:
            self._available = self.llm.enabled and self.llm.available()
            self._checked = True
        return self._available

    def respond(self, prompt: str, name: str, mood: str, memory_line: str) -> str:
        if not self.available():
            return ""
        return self.llm.reply(prompt, name, mood, memory_line) or ""


@dataclass
class RecognizedFlowContext:
    """Payload for multi-step face_recognized sequence."""

    event: FaceRecognized
    name: str
    tier: str
    memory_line: str
    familiar: bool
    track_id: int


@dataclass
class ResponseContext:
    """HUD / UI context (compatible with ui_overlay.draw_all brain_ctx)."""

    state: str = AIState.IDLE.value
    mood: Mood = Mood.CALM
    last_spoken: str = ""
    greeting_bar: str = ""
    status_line: str = ""
    active_tid: Optional[int] = None
    active_bbox: Optional[tuple] = None
    secondary_track_ids: List[int] = field(default_factory=list)
    familiar: bool = False
    ui_motion: str = "minimal"
    track_themes: Dict[int, dict] = field(default_factory=dict)
    memory_lines: Dict[int, str] = field(default_factory=dict)


class ResponseEngine:
    def __init__(
        self,
        settings: dict,
        event_bus: EventBus,
        state_machine: StateMachine,
        memory,
    ):
        self.settings = settings
        self.bus = event_bus
        self.fsm = state_machine
        self.memory = memory
        self.personality_enabled = bool(settings.get("personality_enabled", False))
        self.greetings_enabled = bool(settings.get("greetings_enabled", False))
        self.greeting_bar_enabled = bool(settings.get("greeting_bar_enabled", False))
        self.personality = PersonalityEngine(settings)
        self.voice = VoiceSystem(settings)
        self.llm_handler = LlmResponseHandler(settings)
        self.llm = self.llm_handler.llm
        self.effects = UIEffects(settings)
        self.rules = PersonalityRules(settings)
        self.throttler = ResponseThrottler(settings)
        self.sequences = BehaviorSequenceEngine(settings)
        self._track_manager = None
        self._primary_tid: Optional[int] = None
        self._ctx = ResponseContext()
        self._tracks: List[dict] = []
        self._profiles: dict = {}
        self._frame_count = 0
        self._greeted_session: set = set()
        self._conversed_session: set = set()
        self._last_sighting: Dict[str, float] = {}
        self._llm_busy = False
        self._async_greeting_bar = ""
        self._ollama_checked = False
        self._ollama_ok = False
        self._ui_callbacks: List = []

        self.bus.subscribe_all(self._on_event)

    def register_ui_callback(self, callback):
        """callback(ctx: ResponseContext) — refresh Tk labels."""
        self._ui_callbacks.append(callback)

    def set_track_manager(self, track_manager):
        self._track_manager = track_manager

    def _notify_ui(self):
        for cb in self._ui_callbacks:
            try:
                cb(self._ctx)
            except Exception:
                pass

    @property
    def context(self) -> ResponseContext:
        return self._ctx

    def set_frame_context(
        self,
        tracks: List[dict],
        profiles: dict,
        frame_count: int,
        *,
        primary_track_id: Optional[int] = None,
        secondary_track_ids: Optional[List[int]] = None,
        familiar: bool = False,
    ):
        self._tracks = tracks
        self._profiles = profiles
        self._frame_count = frame_count
        self._primary_tid = primary_track_id
        self._ctx.secondary_track_ids = list(secondary_track_ids or [])
        self._ctx.familiar = familiar

    def process_frame(self, frame, primary_track: Optional[dict]):
        """Apply effects and build per-track HUD context after events processed."""
        self.sequences.tick()
        self._rebuild_track_context(primary_track)
        if self.personality_enabled:
            tone = self.rules.profile_for_state(self._ctx.state, familiar=self._ctx.familiar)
            self._ctx.ui_motion = tone.ui_motion.value
            self._ctx.status_line = self.rules.compose_status_line(
                self._ctx.state, self._ctx.mood, familiar=self._ctx.familiar
            )
        else:
            self._ctx.ui_motion = "minimal"
            self._ctx.status_line = self._ctx.state
            self._ctx.greeting_bar = ""

        if not self.greeting_bar_enabled:
            self._ctx.greeting_bar = ""
            self._async_greeting_bar = ""

        bbox = None
        tid = None
        if primary_track:
            tid = primary_track["id"]
            bbox = primary_track.get("smooth_bbox") or primary_track.get("bbox")

        self._ctx.active_tid = tid
        self._ctx.active_bbox = bbox

        if self.greeting_bar_enabled and self._async_greeting_bar:
            self._ctx.greeting_bar = self._async_greeting_bar

        frame = self.effects.draw(
            frame,
            self._ctx.state,
            self._ctx.mood.value,
            bbox,
            self._ctx.greeting_bar,
            self._frame_count,
        )
        self._notify_ui()
        return frame, self._ctx

    def _rebuild_track_context(self, primary: Optional[dict]):
        state_enum = AIState(self.fsm.state.value) if self.fsm.state.value in AIState.__members__ else AIState.IDLE
        name = primary.get("locked_name", "UNKNOWN") if primary else "UNKNOWN"
        stable = bool(
            primary
            and name != "UNKNOWN"
            and primary.get("stable_count", 0) >= int(self.settings.get("greet_stable_frames", 2))
        )
        tier = self.memory.get_relationship_tier(name, self._profiles) if stable else "UNKNOWN"

        self._ctx.state = self.fsm.state.value
        if stable and tier == "OWNER":
            self._ctx.mood = Mood.FRIENDLY
        elif state_enum == AIState.ALERT:
            self._ctx.mood = Mood.ALERT
        elif name == "UNKNOWN" and self._tracks:
            self._ctx.mood = Mood.SUSPICIOUS
        else:
            self._ctx.mood = Mood.CALM

        themes = {}
        mem_lines = {}
        for t in self._tracks:
            tid = t["id"]
            tname = t.get("locked_name", "UNKNOWN")
            tstable = tname != "UNKNOWN" and t.get("stable_count", 0) >= 2
            themes[tid] = HUD_KNOWN if tname != "UNKNOWN" else HUD_UNKNOWN
            mem_lines[tid] = self.memory.get_visit_summary(tname) if tstable else ""

        self._ctx.track_themes = themes
        self._ctx.memory_lines = mem_lines
        self._ctx.last_spoken = self.voice.last_spoken or self.llm.last_reply or self._ctx.last_spoken

    def _on_event(self, event: Event):
        if isinstance(event, FaceRecognized):
            self._handle_face_recognized(event)
        elif isinstance(event, UnknownFaceDetected):
            self._handle_unknown(event)
        elif isinstance(event, StateChanged):
            self._handle_state_changed(event)
        elif isinstance(event, InteractionStarted):
            self.fsm.trigger_engaged()
        elif isinstance(event, UserCommandIntent):
            self._handle_user_command(event)

    def _handle_face_recognized(self, event: FaceRecognized):
        # Only the attention primary target drives greetings and sequences.
        if self._primary_tid is not None and event.track_id != self._primary_tid:
            return

        if not self.greetings_enabled:
            return

        name = event.name
        event_key = f"face_recognized:{name}:{event.track_id}"
        if not self.throttler.allow_event_reaction(event_key):
            return

        profiles = self._profiles
        tier = self.memory.get_relationship_tier(name, profiles)
        familiar = self._ctx.familiar

        if name in self._greeted_session:
            now = time.time()
            interval = float(self.settings.get("sighting_log_interval_seconds", 30.0))
            if now - self._last_sighting.get(name, 0) > interval:
                self.memory.record_event(name, "seen", self._ctx.mood.value, profiles)
                self._last_sighting[name] = now
            return

        if not self.throttler.allow_greeting(name, familiar=familiar):
            return

        if self.sequences.busy:
            self.throttler.queue_batch(event_key, event)
            return

        self.throttler.mark_event_handled(event_key)
        flow = RecognizedFlowContext(
            event=event,
            name=name,
            tier=tier,
            memory_line="",
            familiar=familiar,
            track_id=event.track_id,
        )
        self._start_recognized_sequence(flow)

    def _start_recognized_sequence(self, flow: RecognizedFlowContext):
        profiles = self._profiles
        self.memory.ensure_person(flow.name, profiles)
        flow.memory_line = self.memory.get_visit_summary(flow.name)
        tone = self.rules.profile_for_state(self.fsm.state.value, familiar=flow.familiar)

        steps = [
            SequenceStep(
                "confirm_identity",
                tone.greeting_delay_ms * 0.35,
                lambda ctx: self._seq_confirm_identity(ctx),
            ),
            SequenceStep(
                "update_ui",
                120,
                lambda ctx: self._seq_update_ui(ctx),
            ),
            SequenceStep(
                "greet",
                max(80, tone.greeting_delay_ms * 0.25),
                lambda ctx: self._seq_greet(ctx),
            ),
            SequenceStep(
                "record_memory",
                80,
                lambda ctx: self._seq_record_memory(ctx),
            ),
            SequenceStep(
                "engage",
                100,
                lambda ctx: self._seq_engage(ctx),
            ),
        ]
        self.sequences.start("face_recognized", steps, flow, replace=True)

    def _seq_confirm_identity(self, flow: RecognizedFlowContext):
        self._ctx.status_line = f"Confirming {flow.name}…"
        self._notify_ui()

    def _seq_update_ui(self, flow: RecognizedFlowContext):
        for t in self._tracks:
            if t["id"] == flow.track_id:
                self._ctx.memory_lines[t["id"]] = flow.memory_line
                break
        self._notify_ui()

    def _seq_greet(self, flow: RecognizedFlowContext):
        if not self.personality_enabled:
            return
        tone = self.rules.profile_for_state(self.fsm.state.value, familiar=flow.familiar)
        if not tone.speak_enabled or not self.settings.get("voice_enabled", False):
            line = self.personality.compose_greeting(
                flow.name, flow.tier, self._ctx.mood, flow.memory_line
            )
            self._ctx.greeting_bar = line
            self._notify_ui()
            return
        line = self.personality.compose_greeting(
            flow.name, flow.tier, self._ctx.mood, flow.memory_line
        )
        self._ctx.greeting_bar = line
        if self.throttler.allow_voice() and self.voice.speak(line):
            self.throttler.record_voice()
            self._ctx.last_spoken = line
        self._notify_ui()

    def _seq_record_memory(self, flow: RecognizedFlowContext):
        profiles = self._profiles
        self.memory.record_event(
            flow.name, "greeting", self._ctx.mood.value, profiles
        )
        self._greeted_session.add(flow.name)
        self.throttler.record_greeting(flow.name)
        self._last_sighting[flow.name] = time.time()

    def _seq_engage(self, flow: RecognizedFlowContext):
        self.fsm.trigger_engaged()
        self.bus.emit(
            InteractionStarted(track_id=flow.track_id, name=flow.name)
        )
        if self.settings.get("auto_converse_after_greet") and self.llm.enabled:
            self._maybe_start_llm(flow.name, flow.memory_line)
        self._notify_ui()

    def _handle_unknown(self, event: UnknownFaceDetected):
        pass  # FSM + themes handle alert styling

    def _handle_state_changed(self, event: StateChanged):
        self.throttler.on_state_changed(event.new_state)
        self._ctx.state = event.new_state
        if event.new_state == AIState.IDLE.value:
            self._ctx.greeting_bar = ""
            self.sequences.cancel()

    def _handle_user_command(self, event: UserCommandIntent):
        import voice_command_handler

        voice_command_handler.handle_intent(
            event.intent,
            event.raw_text,
            brain=self,
            track_manager=self._track_manager,
            profiles=self._profiles,
        )

    def _maybe_start_llm(self, name: str, memory_line: str):
        if name in self._conversed_session or self._llm_busy:
            return
        if not self._ollama_checked:
            self._ollama_ok = self.llm_handler.available()
            self._ollama_checked = True
        if not self._ollama_ok:
            return
        self._conversed_session.add(name)
        self._start_llm_async(name, memory_line)

    def _start_llm_async(self, name: str, memory_line: str):
        self._llm_busy = True
        mood = self._ctx.mood.value
        state_val = self._ctx.state

        def worker():
            try:
                reply = self.llm_handler.respond(
                    f"Auty is in {state_val} with {name}.",
                    name,
                    mood,
                    memory_line,
                )
                if reply:
                    if self.settings.get("voice_enabled", False):
                        self.voice.speak(reply)
                    self._async_greeting_bar = reply
                    self._ctx.last_spoken = reply
            finally:
                self._llm_busy = False

        threading.Thread(target=worker, daemon=True, name="auty-llm").start()

    def on_profile_saved(self, name: str):
        profiles = self.memory.load_profiles()
        self.memory.ensure_person(name, profiles)
        self.memory.record_event(name, "enrolled", Mood.FRIENDLY.value, profiles)

    # Voice command handler expects .voice on brain
    def _pick_primary(self, tracks: List[dict]):
        if not tracks:
            return None
        known = [t for t in tracks if t.get("locked_name", "UNKNOWN") != "UNKNOWN"]
        pool = known if known else tracks

        def area(t):
            b = t.get("smooth_bbox") or t.get("bbox", (0, 0, 0, 0))
            return b[2] * b[3]

        return max(pool, key=area)
