"""
Multi-step behavior sequences — timed steps on the main thread (Tk-safe).
Used by ResponseEngine for face_recognized and similar flows.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


StepFn = Callable[[Any], None]


@dataclass
class SequenceStep:
    name: str
    delay_ms: float  # wait this long after previous step completes
    action: StepFn


@dataclass
class _RunningSequence:
    seq_id: str
    name: str
    steps: List[SequenceStep]
    context: Any
    index: int = 0
    next_run_at: float = 0.0
    on_complete: Optional[Callable[[Any], None]] = None


class BehaviorSequenceEngine:
    """
    Runs queued step lists with inter-step delays.
    Call tick() once per frame from the camera loop / response engine.
    """

    def __init__(self, settings: dict):
        self.settings = settings
        self._active: Optional[_RunningSequence] = None
        self._queue: List[_RunningSequence] = []

    @property
    def busy(self) -> bool:
        return self._active is not None or bool(self._queue)

    def start(
        self,
        name: str,
        steps: List[SequenceStep],
        context: Any,
        *,
        on_complete: Optional[Callable[[Any], None]] = None,
        replace: bool = True,
    ) -> str:
        seq_id = str(uuid.uuid4())[:8]
        run = _RunningSequence(
            seq_id=seq_id,
            name=name,
            steps=steps,
            context=context,
            next_run_at=time.time(),
            on_complete=on_complete,
        )
        if replace and self._active:
            self._queue.clear()
            self._active = run
        elif self._active:
            self._queue.append(run)
        else:
            self._active = run
        return seq_id

    def cancel(self):
        self._active = None
        self._queue.clear()

    def tick(self, now: Optional[float] = None):
        now = now or time.time()
        if self._active is None:
            if self._queue:
                self._active = self._queue.pop(0)
                self._active.next_run_at = now
            else:
                return

        run = self._active
        if now < run.next_run_at:
            return

        if run.index >= len(run.steps):
            cb = run.on_complete
            ctx = run.context
            self._active = None
            if cb:
                cb(ctx)
            return

        step = run.steps[run.index]
        try:
            step.action(run.context)
        except Exception as exc:
            if self.settings.get("debug_scores", False):
                print(f"[sequence] {run.name}/{step.name} error: {exc}")

        run.index += 1
        if run.index < len(run.steps):
            run.next_run_at = now + (step.delay_ms / 1000.0)
        else:
            run.next_run_at = now
