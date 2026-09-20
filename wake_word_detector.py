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

INTERRUPTION_KEYWORDS = {"stop", "cancel"}
DISMISS_KEYWORDS = {
    "disappear", "vanish"
}

INTERRUPTION_PHRASES = {
    "shut up", "hold on", "be quiet", "stop talking",
    "never mind", "thats enough", "that is enough", "please stop"
}

DISMISS_PHRASES = {
    "go away", "get lost", "disappear now", "go off", "turn off",
    "shut down", "good bye", "goodbye", "dismiss assistant", "close assistant",
    "hide assistant", "vanish now", "yo'qol", "yashirin", "ekrandan ket", "dam ol", "yo'q bo'l"
}

INTERRUPTION_GRAMMAR_WORDS = [
    # Interruption targets
    "stop", "cancel", "shut", "up", "hold", "on", "talking", "quiet", "enough",
    "be", "never", "mind", "thats", "that", "please",
    # Dismissal targets
    "disappear", "vanish",
    "go", "away", "get", "lost", "now", "off", "turn", "down", "good", "bye", "goodbye",
    # Phonetic distractors & conversational common words (so Vosk maps non-command speech to these)
    "leave", "close", "hide", "exit", "dismiss",
    "swan", "wait", "one", "sound", "son", "sun", "so", "some", "soon", "someone", "upon", "quitting", "closing",
    "spawn", "spin", "sworn", "swim", "swam", "strong", "stone", "stand", "step", "command", "telegram",
    "store", "star", "stay", "still", "state", "start", "fun", "done", "run", "man", "mode", "ready",
    "won", "can", "fan", "fine", "phone", "sign", "dawn", "down", "drawn", "gone", "orders", "welcome",
    "lawn", "pawn", "fawn", "born", "warn", "weight", "white", "wide", "wet", "late", "space", "indeed",
    "eight", "hate", "gate", "date", "rate", "the", "a", "an", "is", "it", "to", "in", "sir", "yes", "no",
    "and", "that", "this", "you", "what", "there", "here", "video", "youtube", "play", "pause",
    "like", "subscribe", "channel", "watch", "people", "know", "think", "good", "great", "see", "look",
    "just", "about", "how", "all", "will", "would", "could", "should", "not", "right", "well",
    "why", "who", "which", "when", "where", "them", "then", "their", "they", "we", "he", "she", "me",
    "my", "your", "our", "actually", "hey", "hi", "ok", "okay", "[unk]"
]

COMMAND_GRAMMAR_WORDS = [
    # Verbs
    "open", "close", "launch", "quit", "start", "stop", "cancel", "mute",
    "next", "previous", "switch", "turn", "up", "down",
    # Applications
    "safari", "notes", "telegram", "terminal", "chrome", "google", "code", "finder",
    "spotify", "music", "calculator", "calendar", "settings", "blender", "preview", "mail",
    # System concepts
    "volume", "audio", "sound", "wifi", "bluetooth", "tab", "window", "desktop", "space", "agent",
    # Common words and phonetic tokens from Vosk for Uzbek utterances
    "the", "a", "an", "to", "in", "on", "and", "are", "og", "dirt", "talks", "peseta", "gotta", "gently",
    "please", "swan", "sir", "janob", "app", "[unk]"
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
        on_interrupt_callback: Optional[Callable[[str], None]] = None,
        model_dir: Optional[str] = None,
        sample_rate: int = 16000,
        sensitivity: str = "medium"
    ):
        self.on_wake = on_wake_callback
        self.on_interrupt = on_interrupt_callback
        self.sample_rate = sample_rate
        self.enabled = True
        self.sensitivity = sensitivity if sensitivity in RMS_THRESHOLDS else "medium"
        self._lock = threading.RLock()
        self._last_trigger_time = 0.0
        self.cooldown_seconds = 2.0
        self._partial_swan_count = 0
        self._recent_rms = deque(maxlen=35)  # ~2.24s energy memory (never decays to zero prematurely)

        # Interruption tracking
        self._interruption_gap_frames = 0
        self._interruption_loud_frames = 0
        self._last_interrupt_time = 0.0

        if model_dir is None:
            from resource_helper import get_resource_path
            model_dir = get_resource_path(os.path.join("models", "vosk-model-small-en-us-0.15"))
        
        self.model_dir = model_dir
        self.model = None
        self.grammar = json.dumps(GRAMMAR_WORDS)
        self.interruption_grammar = json.dumps(INTERRUPTION_GRAMMAR_WORDS)
        self.command_grammar = json.dumps(COMMAND_GRAMMAR_WORDS)
        self.recognizer = None
        self.interruption_recognizer = None

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
            self.interruption_recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate, self.interruption_grammar)
        except Exception as e:
            print(f"[ERROR] Failed to initialize Vosk model: {e}", flush=True)

    def create_command_recognizer(self) -> Optional[vosk.KaldiRecognizer]:
        """Creates an ultra-fast streaming command recognizer with focused grammar."""
        if self.model:
            try:
                return vosk.KaldiRecognizer(self.model, self.sample_rate, self.command_grammar)
            except Exception:
                try:
                    return vosk.KaldiRecognizer(self.model, self.sample_rate)
                except Exception as e:
                    print(f"⚠️ [WakeWordDetector] Failed to create command recognizer: {e}", flush=True)
        return None

    def reset(self):
        with self._lock:
            self._partial_swan_count = 0
            self._recent_rms.clear()
            self._interruption_gap_frames = 0
            self._interruption_loud_frames = 0
            if self.model:
                try:
                    self.recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate, self.grammar)
                except Exception:
                    pass
                try:
                    self.interruption_recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate, self.interruption_grammar)
                except Exception:
                    pass

    def reset_interruption(self):
        with self._lock:
            self._interruption_gap_frames = 0
            self._interruption_loud_frames = 0
            if self.model:
                try:
                    self.interruption_recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate, self.interruption_grammar)
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

        # 1. Multi-word wake phrases ("hey swan", "hay swan", "hi swan", "hello swan", "ok swan", "okay swan")
        # Invocations of the assistant are unambiguous. Allow even if preceded by background music / noise tokens.
        for phrase in WAKE_PHRASES:
            if phrase in clean:
                idx = clean.find(phrase)
                suffix = clean[idx + len(phrase):].strip().replace("[unk]", "").strip()
                return True, phrase, suffix

        # 2. Standalone single word "swan" or continuous sentence ("swan open safari")
        # Allowed at start, or preceded only by [unk] / noise or at most one short background distractor
        for i, w in enumerate(words):
            if w == "swan":
                preceding = words[:i]
                non_unk_preceding = [pw for pw in preceding if pw != "[unk]"]
                if len(non_unk_preceding) <= 1:
                    suffix = " ".join(words[i + 1:]).replace("[unk]", "").strip()
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
                    raw_partial = self.recognizer.PartialResult()
                    if not raw_partial or '"partial" : ""' in raw_partial or len(raw_partial) <= 22:
                        return
                    partial = json.loads(raw_partial)
                    partial_text = partial.get("partial", "").lower()
                    if partial_text:
                        matched, token, suffix = self._match_wake_word(partial_text, is_final=False)
                        if matched and peak_rms >= min_rms:
                            print(f"⚡ [Wake Word Instant Detected] '{partial_text}' (matched: '{token}', suffix: '{suffix}', peak_RMS: {peak_rms:.1f})", flush=True)
                            self._handle_trigger(suffix)
                            return
                        # Rolling Lattice Reset during continuous music / noise:
                        # If partial text accumulates 6+ words without matching wake word,
                        # and no candidate wake token is in the last 2 words, flush the recognizer
                        # to prevent lattice bloat and keep detection ultra-responsive (<0.1ms reset).
                        p_words = partial_text.split()
                        if len(p_words) >= 6:
                            wake_candidates = {"hey", "hay", "hi", "hello", "ok", "okay", "swan"}
                            recent_tokens = set(p_words[-2:])
                            if not recent_tokens.intersection(wake_candidates):
                                self.recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate, self.grammar)
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

    def process_interruption(self, pcm_bytes: bytes, mic_rms: float, speaker_rms: float):
        """Processes mic audio chunks during assistant playback to detect interruption or dismissal keywords."""
        if not pcm_bytes or self.on_interrupt is None or not self.interruption_recognizer:
            return

        now = time.time()
        if now - self._last_interrupt_time < 0.8:
            return

        # Proportional Speaker Bleed Suppression:
        # When assistant is playing audio from MacBook speakers, chassis vibration causes
        # the internal microphone to register speaker audio at up to 85%-90% of speaker_rms.
        # To prevent Swan's own voice from falsely interrupting itself:
        # 1. If speakers are active (speaker_rms > 0.020), user speech must be clearly higher
        #    than the acoustic bleed (at least 110% of speaker volume AND >= 0.055).
        # 2. If speakers are quiet, direct user speech must meet minimum mic threshold (>= 0.030).
        if speaker_rms > 0.020:
            min_mic_for_interruption = max(0.055, speaker_rms * 1.10)
            if mic_rms < min_mic_for_interruption:
                return
        elif mic_rms < 0.030:
            return

        def _check_text(text_str: str) -> tuple[bool, str, bool]:
            """Returns (matched: bool, token: str, is_dismiss: bool)."""
            if not text_str:
                return False, "", False
            clean = text_str.lower().strip()
            words = clean.split()
            if not words or words == ["[unk]"]:
                return False, "", False

            # 1. Dismiss phrases ("go away", "get lost", "disappear now", "good bye", "goodbye")
            for phrase in DISMISS_PHRASES:
                if phrase in clean:
                    return True, phrase, True

            # 2. Interruption phrases ("shut up", "hold on", "be quiet", "stop talking", "thats enough")
            for phrase in INTERRUPTION_PHRASES:
                if phrase in clean:
                    return True, phrase, False

            # 3. Dismiss keywords ("disappear", "dismiss", "hide", "leave", "exit", "close", "vanish")
            real_words = [w for w in words if w != "[unk]"]
            if real_words:
                lead_words = set(real_words[:3])
                dismiss_hit = lead_words.intersection(DISMISS_KEYWORDS)
                if dismiss_hit:
                    return True, list(dismiss_hit)[0], True

                # 4. Interruption keywords ("stop", "cancel")
                interrupt_hit = lead_words.intersection(INTERRUPTION_KEYWORDS)
                if interrupt_hit:
                    return True, list(interrupt_hit)[0], False

            return False, "", False

        interrupted = False
        is_dismiss = False
        reason = ""

        with self._lock:
            try:
                if self.interruption_recognizer.AcceptWaveform(pcm_bytes):
                    res = json.loads(self.interruption_recognizer.Result())
                    text = res.get("text", "").lower().strip()
                    matched, token, dismiss_flag = _check_text(text)
                    if matched:
                        interrupted = True
                        is_dismiss = dismiss_flag
                        reason = f"Keyword detected: '{token}' in '{text}'"
                else:
                    raw_partial = self.interruption_recognizer.PartialResult()
                    if not raw_partial or '"partial" : ""' in raw_partial or len(raw_partial) <= 22:
                        return
                    partial = json.loads(raw_partial)
                    p_text = partial.get("partial", "").lower().strip()
                    if p_text:
                        matched, token, dismiss_flag = _check_text(p_text)
                        if matched:
                            interrupted = True
                            is_dismiss = dismiss_flag
                            reason = f"Instant keyword: '{token}' in '{p_text}'"
            except Exception:
                pass

        if interrupted:
            self._last_interrupt_time = now
            prefix = "🛑 [Instant Dismiss Fired]" if is_dismiss else "⚡ [Interruption Fired]"
            print(f"{prefix} {reason} (mic_RMS: {mic_rms:.3f}, spk_RMS: {speaker_rms:.3f}, is_dismiss: {is_dismiss})", flush=True)
            self.reset_interruption()
            try:
                self.on_interrupt(reason, is_dismiss=is_dismiss)
            except TypeError:
                self.on_interrupt(reason)
            except Exception as e:
                print(f"[ERROR in on_interrupt]: {e}", flush=True)

