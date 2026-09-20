"""
laya_engine.py - Non-Autoregressive Neural System 1 Decision Engine for Swan OS
Powered by Laya (ConvAI Innovations) & Apple Silicon MPS / CPU.

Evaluates mid-sentence streaming speech intents in ~33ms with mathematically
calibrated probabilities over structured schemas (choice, score, noul).
Works in cascade with Tier 1 Fast-Path heuristics and Tier 3 Gemini Live deep reasoning.
"""

import os
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional

# Question schemas for Swan native OS reflex decisions
SWAN_DECISION_QUESTIONS: Dict[str, Dict[str, Any]] = {
    "intent": {
        "type": "choice",
        "instructions": "Which immediate native computer action does the user want to perform?",
        "criteria": {
            "open_app": "open, launch, or switch to an application (Chrome, Safari, Terminal, Notes, Code, Finder, etc.)",
            "close_app": "close, quit, or kill an application",
            "stop_agent": "stop, halt, cancel, or abort active background AI agents",
            "media_control": "play, pause, next track, previous track, mute, unmute, volume up, volume down",
            "system_toggle": "toggle wifi, toggle bluetooth, take screenshot",
            "none": "general conversational question, coding, 3D blender modeling, document creation, deep research, or reasoning requiring Gemini"
        }
    },
    "is_reflex": {
        "type": "noul",
        "instructions": "Should this be fired immediately as a native OS reflex action while the user is still speaking?"
    },
    "target_app": {
        "type": "choice",
        "instructions": "If an app is being opened or closed, which one is it?",
        "criteria": {
            "google chrome": "Chrome, Google Chrome, web browser",
            "safari": "Safari, Apple browser",
            "terminal": "Terminal, iTerm, Warp, command line, console",
            "visual studio code": "VS Code, Code, editor, Cursor",
            "notes": "Notes, Apple Notes, TextEdit, memo",
            "finder": "Finder, files, folders",
            "system settings": "System Settings, Preferences",
            "none": "no specific app mentioned or other task"
        }
    }
}


class LayaStatus(Enum):
    STANDBY = "standby"
    DOWNLOADING = "downloading"
    READY = "ready"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class LayaDecision:
    intent: str
    intent_confidence: float
    is_reflex: bool
    is_reflex_prob: float
    target_app: str
    target_app_confidence: float
    latency_ms: float
    raw_answers: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_confident_reflex(self) -> bool:
        """Returns True if Laya is confident this should execute as a native OS reflex."""
        return (
            self.intent != "none"
            and self.intent_confidence >= 0.85
            and self.is_reflex_prob >= 0.85
        )


class LayaEngine:
    """Singleton managing the Laya Non-Autoregressive Decision Engine."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(LayaEngine, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self.status = LayaStatus.STANDBY
        self.enabled = True
        self.error_message = ""
        self.device = "cpu"
        self.model_type = "multilingual"  # 'multilingual' (mmBERT-base) or 'english' (ModernBERT-large)
        self.agent = None
        self._load_lock = threading.Lock()
        self._load_thread: Optional[threading.Thread] = None

        # Check MPS availability on Apple Silicon
        try:
            import torch
            if torch.backends.mps.is_available():
                self.device = "mps"
            else:
                self.device = "cpu"
        except Exception:
            self.device = "cpu"

    def is_ready(self) -> bool:
        return self.enabled and self.status == LayaStatus.READY and self.agent is not None

    def start_background_loading(self, model_type: str = "multilingual"):
        """Asynchronously downloads/loads Laya model weights in the background."""
        if not self.enabled:
            return

        with self._load_lock:
            if self.status in [LayaStatus.DOWNLOADING, LayaStatus.READY]:
                return
            self.status = LayaStatus.DOWNLOADING
            self.model_type = model_type

            self._load_thread = threading.Thread(
                target=self._load_worker,
                daemon=True,
                name="LayaModelLoader"
            )
            self._load_thread.start()

    def _load_worker(self):
        try:
            print(f"[LayaEngine] Loading Laya model '{self.model_type}' on device '{self.device}'...", flush=True)
            t0 = time.time()
            import laya

            subfolder = "multilingual" if self.model_type == "multilingual" else None
            # laya.load downloads cached weights from Hugging Face if not present
            agent = laya.load(
                "convaiinnovations/laya",
                device=self.device,
                subfolder=subfolder
            )

            with self._load_lock:
                self.agent = agent
                self.status = LayaStatus.READY
                self.error_message = ""

            elapsed = round((time.time() - t0), 2)
            print(f"[LayaEngine] Laya System 1 Decision Engine ready in {elapsed}s on {self.device}!", flush=True)
        except Exception as e:
            with self._load_lock:
                self.status = LayaStatus.ERROR
                self.error_message = str(e)
            print(f"[LayaEngine] Failed to load Laya model: {e}", flush=True)

    def evaluate_speech_intent(self, text: str) -> Optional[LayaDecision]:
        """Evaluates incoming streaming speech text with calibrated probabilities."""
        if not self.is_ready():
            return None

        clean_text = (text or "").strip()
        if len(clean_text) < 3:
            return None

        t0 = time.time()
        try:
            res = self.agent.predict({"utterance": clean_text}, SWAN_DECISION_QUESTIONS)
            latency_ms = round((time.time() - t0) * 1000, 1)

            answers = res.get("answers", {})
            intent_data = answers.get("intent", {})
            reflex_data = answers.get("is_reflex", {})
            target_data = answers.get("target_app", {})

            intent = intent_data.get("choice", "none")
            intent_conf = float(intent_data.get("confidence", 0.0))
            is_reflex_prob = float(reflex_data.get("noul", 0.0))
            is_reflex_bool = is_reflex_prob >= 0.50
            target_app = target_data.get("choice", "none")
            target_app_conf = float(target_data.get("confidence", 0.0))

            decision = LayaDecision(
                intent=intent,
                intent_confidence=intent_conf,
                is_reflex=is_reflex_bool,
                is_reflex_prob=is_reflex_prob,
                target_app=target_app,
                target_app_confidence=target_app_conf,
                latency_ms=latency_ms,
                raw_answers=answers
            )

            print(
                f"[LayaEngine] '{clean_text}' -> intent={decision.intent} ({decision.intent_confidence:.2f}), "
                f"reflex={decision.is_reflex_prob:.2f}, target={decision.target_app}, latency={decision.latency_ms}ms",
                flush=True
            )
            return decision

        except Exception as e:
            print(f"[LayaEngine] Prediction error on '{clean_text}': {e}", flush=True)
            return None

    def get_status_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "enabled": self.enabled,
            "device": self.device,
            "model_type": self.model_type,
            "error": self.error_message
        }


# Global singleton instance
laya_engine = LayaEngine()
