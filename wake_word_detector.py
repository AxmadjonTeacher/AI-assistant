import json
import time
import os
import threading
from collections import deque
from typing import Callable, Optional
import numpy as np
import vosk

# Strictly legitimate wake phrases and words
WAKE_PHRASES = ["hey swan", "hay swan", "hi swan", "hello swan", "ok swan", "okay swan"]
WAKE_WORDS = {"swan"}

# Comprehensive vocabulary with phonetic distractors so Vosk doesn't force-map YouTube speech to "swan"
GRAMMAR_WORDS = [
    # Wake targets
    "swan", "hey", "hay", "hi", "hello", "ok", "okay",
    # Phonetic distractors for 'swan' and '-on' / '-un' sounds
    "one", "on", "sound", "son", "sun", "so", "some", "soon", "someone", "upon",
    "spawn", "spin", "sworn", "swim", "swam", "strong", "stone", "stand", "stop",
    "fun", "done", "run", "man", "won", "can", "fan", "fine", "phone", "sign",
    "dawn", "down", "drawn", "gone", "lawn", "pawn", "fawn", "born", "warn",
    # Frequent conversational, video and media words
    "the", "a", "an", "is", "it", "to", "in", "and", "that", "this", "you", "what",
    "there", "here", "video", "youtube", "play", "like", "subscribe", "channel",
    "watch", "people", "know", "think", "good", "great", "see", "look", "now",
    "just", "about", "how", "all", "will", "would", "could", "should", "not", "no",
    "yes", "right", "well", "why", "who", "which", "when", "where", "them", "then",
    "their", "they", "we", "he", "she", "me", "my", "your", "our", "[unk]"
]

RMS_THRESHOLDS = {
    "low": 240.0,    # Strictly near-field direct user speech
    "medium": 120.0, # Balanced responsive default
    "high": 40.0     # Sensitive
}

class WakeWordDetector:
    def __init__(
        self,
        on_wake_callback: Callable[[], None],
        model_dir: Optional[str] = None,
        sample_rate: int = 16000,
        sensitivity: str = "medium"
    ):
        self.on_wake = on_wake_callback
        self.sample_rate = sample_rate
        self.enabled = True
        self.sensitivity = sensitivity if sensitivity in RMS_THRESHOLDS else "medium"
        self._lock = threading.RLock()
        self._last_trigger_time = 0.0
        self.cooldown_seconds = 2.0
        self._partial_swan_count = 0
        self._recent_rms = deque(maxlen=35)  # ~2.24s energy memory (never decays to zero prematurely)

        if model_dir is None:
            model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "vosk-model-small-en-us-0.15")
        
        self.model_dir = model_dir
        self.model = None
        self.grammar = json.dumps(GRAMMAR_WORDS)
        self.recognizer = None

        self._init_model()

    def set_sensitivity(self, sensitivity: str):
        if sensitivity in RMS_THRESHOLDS:
            self.sensitivity = sensitivity
            print(f"🎙️ [Wake Sensitivity] Set to: {self.sensitivity.upper()} (RMS threshold: {RMS_THRESHOLDS[self.sensitivity]})", flush=True)

    def _init_model(self):
        if not os.path.exists(self.model_dir):
            print(f"[WARN] Wake word model directory not found: {self.model_dir}", flush=True)
            return
        try:
            vosk.SetLogLevel(-1)
            self.model = vosk.Model(self.model_dir)
            self.recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate, self.grammar)
        except Exception as e:
            print(f"[ERROR] Failed to initialize Vosk model: {e}", flush=True)

    def reset(self):
        with self._lock:
            self._partial_swan_count = 0
            self._recent_rms.clear()
            if self.model:
                try:
                    self.recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate, self.grammar)
                except Exception:
                    pass

    def _compute_rms(self, pcm_bytes: bytes) -> float:
        if not pcm_bytes or len(pcm_bytes) < 2:
            return 0.0
        data = np.frombuffer(pcm_bytes, dtype=np.int16)
        if len(data) == 0:
            return 0.0
        return float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))

    def _match_wake_word(self, text: str, is_final: bool) -> tuple[bool, str, str]:
        if not text:
            return False, "", ""
        clean = text.lower().strip()
        words = clean.split()
        if not words or words == ["[unk]"]:
            return False, "", ""

        # 1. Multi-word wake phrases ("hey swan", "hi swan", "ok swan", "hello swan")
        for phrase in WAKE_PHRASES:
            if phrase in clean:
                idx = clean.find(phrase)
                prefix = clean[:idx].strip()
                # If there are preceding words, reject if mid-sentence (more than 1 word or contains [unk])
                if prefix and (len(prefix.split()) > 1 or "[unk]" in prefix):
                    continue
                suffix = clean[idx + len(phrase):].strip().replace("[unk]", "").strip()
                return True, phrase, suffix

        # 2. Standalone single word "swan" or continuous sentence ("swan open safari")
        if words[0] == "swan":
            suffix = " ".join(words[1:]).replace("[unk]", "").strip()
            return True, "swan", suffix
        elif len(words) >= 2 and words[0] == "[unk]" and words[1] == "swan":
            suffix = " ".join(words[2:]).replace("[unk]", "").strip()
            return True, "swan", suffix

        return False, "", ""

    def process_audio(self, pcm_bytes: bytes):
        if not self.enabled or self.recognizer is None or not pcm_bytes:
            return

        rms = self._compute_rms(pcm_bytes)
        self._recent_rms.append(rms)
        peak_rms = max(self._recent_rms) if self._recent_rms else rms
        min_rms = RMS_THRESHOLDS.get(self.sensitivity, 200.0)

        with self._lock:
            try:
                if self.recognizer.AcceptWaveform(pcm_bytes):
                    res = json.loads(self.recognizer.Result())
                    text = res.get("text", "").lower()
                    matched, token, suffix = self._match_wake_word(text, is_final=True)
                    if matched and peak_rms >= min_rms:
                        print(f"🎙️ [Wake Word Confirmed] '{text}' (matched: '{token}', suffix: '{suffix}', peak_RMS: {peak_rms:.1f})", flush=True)
                        self._handle_trigger(suffix)
                        return
                else:
                    partial = json.loads(self.recognizer.PartialResult())
                    partial_text = partial.get("partial", "").lower()
                    if partial_text:
                        matched, token, suffix = self._match_wake_word(partial_text, is_final=False)
                        if matched and peak_rms >= min_rms:
                            print(f"⚡ [Wake Word Instant Detected] '{partial_text}' (matched: '{token}', suffix: '{suffix}', peak_RMS: {peak_rms:.1f})", flush=True)
                            self._handle_trigger(suffix)
                            return
            except Exception:
                pass

    def _handle_trigger(self, suffix: str = ""):
        now = time.time()
        if now - self._last_trigger_time < self.cooldown_seconds:
            return
        self._last_trigger_time = now
        self.reset()
        if self.on_wake:
            try:
                self.on_wake(suffix)
            except TypeError:
                self.on_wake()

