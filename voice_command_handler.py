"""
Handle parsed voice intents (shared by main UI).
"""

from personality_engine import Mood


def handle_intent(
    intent: str,
    raw_text: str,
    *,
    brain,
    track_manager,
    profiles: dict,
    voice_heard_var=None,
) -> None:
    if voice_heard_var is not None:
        voice_heard_var.set(f"Heard: {raw_text[:48]}")

    tracks = track_manager.active_tracks() if track_manager else []
    primary = brain._pick_primary(tracks) if tracks else None
    name = primary.get("locked_name", "UNKNOWN") if primary else "UNKNOWN"
    tier = brain.memory.get_relationship_tier(name, profiles) if name != "UNKNOWN" else "UNKNOWN"
    mood = brain.context.mood if brain.context else Mood.CALM
    voice = brain.voice

    def say(text: str):
        voice.speak(text, force=True)

    if intent == "whoami":
        if name != "UNKNOWN":
            prof = profiles.get(name, {})
            display = str(prof.get("name", name)).strip() or name
            say(f"You're {display}.")
        else:
            say("I don't recognize you yet. Look at the camera to enroll.")
        return

    if intent == "feeling":
        if primary:
            feeling = brain._feeling_label(primary)
            if feeling != "—":
                say(f"You look {feeling.split('(')[0].strip().lower()} to me.")
            else:
                say("I'm still reading your expression. Hold still a moment.")
        else:
            say("I don't see anyone in frame.")
        return

    if intent == "greet":
        if name != "UNKNOWN":
            if brain.personality_enabled:
                line = brain.personality.compose_greeting(
                    name, tier, mood, brain.memory.get_memory_line(name)
                )
                say(line or f"Hello, {name}.")
            else:
                say(f"Hello, {name}.")
        else:
            say("Hello. Step into view so I can see you.")
        return

    if intent == "repeat":
        last = voice.last_spoken or brain.llm.last_reply
        if last:
            say(last)
        else:
            say("I haven't said anything yet.")
        return

    if intent == "status":
        ctx = brain.context
        state_label = ctx.state if isinstance(ctx.state, str) else ctx.state.value
        say(
            f"I'm {state_label}, mood {ctx.mood.value}. "
            f"{'I see you' if name != 'UNKNOWN' else 'No one recognized'}."
        )
        return

    if intent == "help":
        say(
            "You can say: who am I, how am I feeling, say hello, "
            "repeat, status, mute, or unmute."
        )
        return

    if intent == "mute":
        voice.enabled = False
        say("Okay, I'll stay quiet.")
        return

    if intent == "unmute":
        voice.enabled = True
        if not voice._engine:
            voice._init_engine()
        say("I'm back. You can talk to me again.")
        return

    if intent == "thanks":
        say("You're welcome.")
        return

    if intent == "unknown":
        say("I didn't understand. Say help for commands.")
