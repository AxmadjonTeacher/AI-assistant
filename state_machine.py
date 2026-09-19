import asyncio
import threading
import time
from enum import Enum
from typing import Callable, List, Optional

from config import config

class AssistantState(str, Enum):
    IDLE = "idle"
    WAKE = "wake"
    LISTENING = "listening"
    THINKING = "thinking"
    ACTION = "action"
    SPEAKING = "speaking"
    ERROR = "error"

# Natural translations based on configured language
STATE_LABELS = {
    "en": {
        AssistantState.IDLE: "Ready",
        AssistantState.WAKE: "Ready",
        AssistantState.LISTENING: "Listening...",
        AssistantState.THINKING: "Thinking...",
        AssistantState.SPEAKING: "Speaking...",
        AssistantState.ERROR: "Error",
        "listening_reply": "Listening for reply...",
        "listening_followup": "Listening for follow-up...",
        "thinking_stage2": "Analyzing...",
        "thinking_stage3": "Reasoning...",
    },
    "uz": {
        AssistantState.IDLE: "Tayyor",
        AssistantState.WAKE: "Tayyor",
        AssistantState.LISTENING: "Eshitmoqda...",
        AssistantState.THINKING: "O'ylamoqda...",
        AssistantState.SPEAKING: "Gapirmoqda...",
        AssistantState.ERROR: "Xatolik",
        "listening_reply": "Javob tinglanmoqda...",
        "listening_followup": "Davomi tinglanmoqda...",
        "thinking_stage2": "Tahlil qilmoqda...",
        "thinking_stage3": "Fikrlamoqda...",
    },
    "tr": {
        AssistantState.IDLE: "Hazır",
        AssistantState.WAKE: "Hazır",
        AssistantState.LISTENING: "Dinliyor...",
        AssistantState.THINKING: "Düşünüyor...",
        AssistantState.SPEAKING: "Konuşuyor...",
        AssistantState.ERROR: "Hata",
        "listening_reply": "Cevap dinleniyor...",
        "listening_followup": "Devamı dinleniyor...",
        "thinking_stage2": "Analiz ediyor...",
        "thinking_stage3": "Akıl yürütüyor...",
    }
}

class AssistantStateMachine:
    """Internal state machine coordinating visual status labels and assistant states."""
    def __init__(self):
        self._state: AssistantState = AssistantState.IDLE
        self._label: str = "Ready"
        self._detail: str = ""
        self._state_start_time: float = time.time()
        self._lock = threading.Lock()
        self._listeners: List[Callable[[AssistantState, str, str], None]] = []
        self._thinking_timer_task: Optional[asyncio.Task] = None

    @property
    def state(self) -> AssistantState:
        with self._lock:
            return self._state

    @property
    def label(self) -> str:
        with self._lock:
            return self._label

    def add_listener(self, callback: Callable[[AssistantState, str, str], None]):
        """Registers a listener callback (state, label, detail)."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[AssistantState, str, str], None]):
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _get_lang(self) -> str:
        lang = getattr(config, "language", "uz") or "uz"
        return lang if lang in STATE_LABELS else "en"

    def _default_label(self, key_or_state) -> str:
        lang = self._get_lang()
        table = STATE_LABELS.get(lang, STATE_LABELS["en"])
        return table.get(key_or_state, str(key_or_state).capitalize())

    def _notify_listeners(self, state: AssistantState, label: str, detail: str):
        for cb in list(self._listeners):
            try:
                cb(state, label, detail)
            except Exception as e:
                print(f"⚠️ [StateMachine] Listener error: {e}", flush=True)

    def _cancel_thinking_timer(self):
        if self._thinking_timer_task and not self._thinking_timer_task.done():
            self._thinking_timer_task.cancel()
        self._thinking_timer_task = None

    def transition_to(self, new_state: AssistantState, label: Optional[str] = None, detail: Optional[str] = None):
        """Transitions assistant to a new state and notifies all visual listeners."""
        with self._lock:
            self._cancel_thinking_timer()
            self._state = new_state
            self._state_start_time = time.time()

            if label is None:
                label = self._default_label(new_state)
            self._label = label
            self._detail = detail or ""

        self._notify_listeners(new_state, self._label, self._detail)

    def on_wake(self, acknowledgment_label: Optional[str] = None):
        """Wake word detected."""
        label = acknowledgment_label or self._default_label(AssistantState.WAKE)
        self.transition_to(AssistantState.WAKE, label=label)

    def on_listening(self, context_hint: Optional[str] = None):
        """Microphone active and listening."""
        label = None
        if context_hint:
            if "reply" in context_hint.lower() or "javob" in context_hint.lower():
                label = self._default_label("listening_reply")
            elif "follow" in context_hint.lower() or "davom" in context_hint.lower():
                label = self._default_label("listening_followup")
            else:
                label = context_hint
        if not label:
            label = self._default_label(AssistantState.LISTENING)
        self.transition_to(AssistantState.LISTENING, label=label)

    def on_thinking(self):
        """Turn speech ended, Gemini model is processing / reasoning."""
        initial_label = self._default_label(AssistantState.THINKING)
        self.transition_to(AssistantState.THINKING, label=initial_label)

        # Start background progressive thinking task if in an active event loop
        try:
            loop = asyncio.get_running_loop()
            self._thinking_timer_task = loop.create_task(self._thinking_progression_loop())
        except RuntimeError:
            pass

    async def _thinking_progression_loop(self):
        """Progressively updates thinking label if model processing takes extra time."""
        try:
            # Stage 2 after 1.8 seconds: "Analyzing..."
            await asyncio.sleep(1.8)
            with self._lock:
                if self._state != AssistantState.THINKING:
                    return
                stage2_label = self._default_label("thinking_stage2")
                self._label = stage2_label
            self._notify_listeners(AssistantState.THINKING, stage2_label, "")

            # Stage 3 after another 2.0 seconds (3.8s total): "Reasoning..."
            await asyncio.sleep(2.0)
            with self._lock:
                if self._state != AssistantState.THINKING:
                    return
                stage3_label = self._default_label("thinking_stage3")
                self._label = stage3_label
            self._notify_listeners(AssistantState.THINKING, stage3_label, "")
        except asyncio.CancelledError:
            pass

    def on_action(self, action_label: str):
        """Model or agent is executing an action/tool."""
        self.transition_to(AssistantState.ACTION, label=action_label)

    def on_speaking(self, response_label: Optional[str] = None):
        """Assistant audio response streaming/playing."""
        label = response_label or self._default_label(AssistantState.SPEAKING)
        self.transition_to(AssistantState.SPEAKING, label=label)

    def on_error(self, error_message: str):
        """Error during turn."""
        short_err = str(error_message)[:30]
        self.transition_to(AssistantState.ERROR, label=f"Error: {short_err}")

    def on_idle(self):
        """Turn complete, assistant idle."""
        self.transition_to(AssistantState.IDLE, label=self._default_label(AssistantState.IDLE))
