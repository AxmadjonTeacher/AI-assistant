"""
Reflex Engine (System 1) for Swan AI Assistant.
Near-instant, zero-latency on-device intent classifier and action dispatcher.

Evaluates streaming partial speech chunks in <10ms without cloud roundtrips.
If calibrated confidence >= 0.88 for native computer control tasks, it fires
the native OS automation immediately mid-sentence, while delegating deep work
(prose, reasoning, complex instructions) to Gemini (System 2: The Deep Brain).
"""

import re
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple, List

# Supported applications mapping (lowercase aliases -> Canonical Name)
APP_MAP: Dict[str, str] = {
    # System & Productivity
    "terminal": "Terminal",
    "iterm": "iTerm",
    "iterm2": "iTerm",
    "safari": "Safari",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "finder": "Finder",
    "notes": "Notes",
    "calculator": "Calculator",
    "calendar": "Calendar",
    "settings": "System Settings",
    "system settings": "System Settings",
    "reminders": "Reminders",
    "photos": "Photos",
    "mail": "Mail",
    "messages": "Messages",
    "music": "Music",
    "spotify": "Spotify",
    "preview": "Preview",
    "textedit": "TextEdit",
    # Developer & Creative
    "code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "visual studio code": "Visual Studio Code",
    "xcode": "Xcode",
    "blender": "Blender",
    "figma": "Figma",
    "slack": "Slack",
    "telegram": "Telegram",
    "discord": "Discord",
    "zoom": "zoom.us",
    "whatsapp": "WhatsApp",
    # AI & Web Apps
    "chatgpt": "ChatGPT",
    "gemini": "Google Gemini",
    "claude": "Claude",
    "youtube": "YouTube",
    "github": "GitHub",
}

# Substring/stem variations for Uzbek accusative case (e.g., "terminalni", "safarini", "noteni")
UZBEK_APP_STEMS: Dict[str, str] = {
    "terminal": "Terminal",
    "safari": "Safari",
    "xrom": "Google Chrome",
    "chrome": "Google Chrome",
    "faynder": "Finder",
    "finder": "Finder",
    "not": "Notes",
    "note": "Notes",
    "yozuvlar": "Notes",
    "kalkulyator": "Calculator",
    "kalendar": "Calendar",
    "sozlama": "System Settings",
    "sozlamalar": "System Settings",
    "musiqa": "Music",
    "spotify": "Spotify",
    "telegram": "Telegram",
    "kod": "Visual Studio Code",
    "vskod": "Visual Studio Code",
    "blender": "Blender",
    "yutub": "YouTube",
    "youtube": "YouTube",
}

@dataclass
class ReflexDecision:
    choice: str                     # e.g., "open_app", "close_app", "system_control", "media_control", "dismiss", "ask_ai"
    confidence: float              # 0.0 to 1.0 calibrated confidence
    action_type: str               # Canonical tool action
    params: Dict[str, Any]         # Parameters for tools.py
    is_reflex_action: bool         # True if native OS action ready to fire mid-sentence
    display_label: str             # HUD status text (e.g. "Opening Terminal...")
    has_followup: bool = False     # True if speech contains secondary commands
    residual_text: str = ""        # Text following the reflex command (e.g. "and run tests")
    matched_phrase: str = ""

class ReflexEngine:
    """
    Ultra-fast rule-based and phonetic decision engine for streaming partial speech.
    Operates in <5ms on partial transcript buffers.
    """

    def __init__(self):
        self._dispatched_actions: set = set()
        self._lock = threading.Lock()
        self._last_dispatch_time: float = 0.0

    def reset_turn(self):
        """Resets dispatched actions at the start of each speech turn."""
        with self._lock:
            self._dispatched_actions.clear()
            self._last_dispatch_time = 0.0

    def has_dispatched(self, action_key: str) -> bool:
        with self._lock:
            return action_key in self._dispatched_actions

    def mark_dispatched(self, action_key: str):
        with self._lock:
            self._dispatched_actions.add(action_key)
            self._last_dispatch_time = time.time()

    def evaluate(self, partial_text: str, language: str = "en") -> Optional[ReflexDecision]:
        """
        Evaluates partial or full speech chunk and returns a calibrated decision.
        """
        if not partial_text:
            return None

        # Clean and normalize speech artifacts (e.g. "o chir" -> "o'chir", "wi fi" -> "wifi")
        text = partial_text.lower().strip()
        text = re.sub(r"\bo\s+chir\b", "o'chir", text)
        text = re.sub(r"\bo['`ʻ’]chir\b", "o'chir", text)
        text = re.sub(r"\bo\s+t\b", "o't", text)
        text = re.sub(r"\bwi\s+fi\b", "wifi", text)
        text = re.sub(r"\bblue\s+tooth\b", "bluetooth", text)
        text = re.sub(r"\bscreen\s+shot\b", "screenshot", text)

        words = text.split()
        if not words:
            return None

        # 1. Immediate Dismissal ("dismiss", "disappear", "go away", "yo'qol", "rahmat ketishing mumkin")
        dismiss_decision = self._check_dismiss(text)
        if dismiss_decision:
            return dismiss_decision

        # 1b. Stop Background Agent ("stop agent", "cancel agent", "agentni to'xtat", "to'xtat agentni")
        stop_agent_decision = self._check_stop_agent(text)
        if stop_agent_decision:
            return stop_agent_decision

        # 2. Open Application ("open terminal and...", "terminalni och")
        open_decision = self._check_open_app(text, words)
        if open_decision:
            return open_decision

        # 3. Close Application ("close safari", "terminalni yop")
        close_decision = self._check_close_app(text, words)
        if close_decision:
            return close_decision

        # 4. Audio & Volume ("mute", "unmute", "volume up", "ovozni balandlat", "ovozni o'chir")
        volume_decision = self._check_volume(text)
        if volume_decision:
            return volume_decision

        # 5. Media Control ("pause music", "stop music", "next song", "musiqani to'xtat")
        media_decision = self._check_media(text)
        if media_decision:
            return media_decision

        # 6. Bluetooth & WiFi ("turn on bluetooth", "bluetooth-ni yoq", "wifi-ni o'chir")
        connectivity_decision = self._check_connectivity(text)
        if connectivity_decision:
            return connectivity_decision

        # 7. Screenshot ("take a screenshot", "ekranni rasmga ol", "skrinshot qil")
        screenshot_decision = self._check_screenshot(text)
        if screenshot_decision:
            return screenshot_decision

        # 8. Generative / Deep Brain Query ("explain...", "how do I...", "write code...", "tushuntir...")
        ask_ai_decision = self._check_ask_ai(text)
        if ask_ai_decision:
            return ask_ai_decision

        return None

    def _extract_followup(self, full_text: str, trigger_end_idx: int) -> Tuple[bool, str]:
        """Checks if text contains subsequent commands connected by 'and', 'then', 'hamda', etc."""
        after = full_text[trigger_end_idx:].strip()
        # Remove connecting tokens
        connectors = [
            "and also", "and then", "and", "then", "after that",
            "va", "keyin", "hamda", "bilan", "so'ng"
        ]
        for conn in connectors:
            if after.startswith(conn + " ") or after == conn:
                residual = after[len(conn):].strip()
                return bool(residual), residual
        if len(after) > 2:
            return True, after
        return False, ""

    def _check_dismiss(self, text: str) -> Optional[ReflexDecision]:
        dismiss_patterns = [
            r"\b(go away|get lost|disappear|vanish|hide assistant|dismiss assistant)\b",
            r"\b(shut down|turn off|close assistant)\b",
            r"\b(rahmat ketishing mumkin|ketishing mumkin|yo'qol|yashirin|ekrandan ket|dam ol|yo'q bo'l)\b"
        ]
        for pat in dismiss_patterns:
            m = re.search(pat, text)
            if m:
                return ReflexDecision(
                    choice="dismiss",
                    confidence=0.98,
                    action_type="dismiss_assistant",
                    params={},
                    is_reflex_action=True,
                    display_label="Dismissing...",
                    matched_phrase=m.group(0)
                )
        return None

    def _check_stop_agent(self, text: str) -> Optional[ReflexDecision]:
        stop_patterns = [
            r"\b(stop agent|cancel agent|halt agent|abort agent|kill agent|stop background agent|stop task|stop the agent)\b",
            r"\b(agentni to'xtat|agentni to'xtating|agentni bekor qil|agentni to'xtatgin|agentni o'chir|fon agentini to'xtat|to'xtat agentni|bekor qil agentni)\b",
            r"\b(agent to'xtasin|vazifani to'xtat|ishni to'xtat|agentni toxtat|agentni to'xtatib tur)\b"
        ]
        for pat in stop_patterns:
            m = re.search(pat, text)
            if m:
                return ReflexDecision(
                    choice="stop_agent",
                    confidence=0.98,
                    action_type="stop_agent",
                    params={},
                    is_reflex_action=True,
                    display_label="Agent to'xtatilmoqda...",
                    matched_phrase=m.group(0)
                )
        return None

    def _check_open_app(self, text: str, words: List[str]) -> Optional[ReflexDecision]:
        # English patterns: "open [app]", "launch [app]", "start [app]", "switch to [app]"
        open_verbs = ["open", "launch", "start", "run", "switch to"]
        for verb in open_verbs:
            if verb in text:
                pattern = rf"\b{verb}\s+([a-zA-Z0-9\s]+)"
                m = re.search(pattern, text)
                if m:
                    candidate_str = m.group(1).strip()
                    cand_words = candidate_str.split()
                    # Try multi-word apps then single word apps
                    for length in [3, 2, 1]:
                        if len(cand_words) >= length:
                            sub_name = " ".join(cand_words[:length])
                            if sub_name in APP_MAP:
                                app_name = APP_MAP[sub_name]
                                end_pos = m.start(1) + len(sub_name)
                                has_follow, residual = self._extract_followup(text, end_pos)
                                return ReflexDecision(
                                    choice="open_app",
                                    confidence=0.96,
                                    action_type="open_app",
                                    params={"app_name": app_name},
                                    is_reflex_action=True,
                                    display_label=f"{app_name} ochilmoqda...",
                                    has_followup=has_follow,
                                    residual_text=residual,
                                    matched_phrase=f"{verb} {sub_name}"
                                )

        # Uzbek patterns: "[app]ni och", "[app] ilovasini och", "[app] och", "[app]ga o't"
        uz_patterns = [
            r"([a-zA-Z0-9]+)(?:ni|ning|ga)?\s+(?:ilovasini\s+)?(och|ochgin|oching|ochib ber|ishga tushir|ishga tushirgin|boshla|o't)\b",
            r"(och|ochgin|oching|ochib ber|ishga tushir)\s+([a-zA-Z0-9]+)"
        ]
        for pat in uz_patterns:
            m = re.search(pat, text)
            if m:
                groups = m.groups()
                cand = groups[0] if groups[1] in ["och", "ochgin", "oching", "ochib ber", "ishga tushir", "ishga tushirgin", "boshla", "o't"] else groups[1]
                cand = cand.lower().strip()
                # Remove suffixes like "ni", "ga"
                for sfx in ["ni", "ning", "ga", "da"]:
                    if cand.endswith(sfx) and len(cand) > len(sfx) + 2:
                        cand = cand[:-len(sfx)]
                        break
                matched_app = APP_MAP.get(cand) or UZBEK_APP_STEMS.get(cand)
                if matched_app:
                    has_follow, residual = self._extract_followup(text, m.end())
                    return ReflexDecision(
                        choice="open_app",
                        confidence=0.96,
                        action_type="open_app",
                        params={"app_name": matched_app},
                        is_reflex_action=True,
                        display_label=f"{matched_app} ochilmoqda...",
                        has_followup=has_follow,
                        residual_text=residual,
                        matched_phrase=m.group(0)
                    )

        return None

    def _check_close_app(self, text: str, words: List[str]) -> Optional[ReflexDecision]:
        close_verbs = ["close", "quit", "exit", "kill"]
        for verb in close_verbs:
            if verb in text:
                pattern = rf"\b{verb}\s+([a-zA-Z0-9\s]+)"
                m = re.search(pattern, text)
                if m:
                    cand_words = m.group(1).strip().split()
                    for length in [2, 1]:
                        if len(cand_words) >= length:
                            sub_name = " ".join(cand_words[:length])
                            if sub_name in APP_MAP:
                                app_name = APP_MAP[sub_name]
                                return ReflexDecision(
                                    choice="close_app",
                                    confidence=0.95,
                                    action_type="close_app",
                                    params={"app_name": app_name},
                                    is_reflex_action=True,
                                    display_label=f"{app_name} yopilmoqda...",
                                    matched_phrase=f"{verb} {sub_name}"
                                )

        # Uzbek: "[app]ni yop"
        uz_patterns = [
            r"([a-zA-Z0-9]+)(?:ni)?\s+(yop|yopgin|yoping|yopib ber|o'chir|o'chirgin|chiq|to'xtat)\b"
        ]
        for pat in uz_patterns:
            m = re.search(pat, text)
            if m:
                cand = m.group(1).lower().strip()
                matched_app = APP_MAP.get(cand) or UZBEK_APP_STEMS.get(cand)
                if matched_app:
                    return ReflexDecision(
                        choice="close_app",
                        confidence=0.95,
                        action_type="close_app",
                        params={"app_name": matched_app},
                        is_reflex_action=True,
                        display_label=f"{matched_app} yopilmoqda...",
                        matched_phrase=m.group(0)
                    )
        return None

    def _check_volume(self, text: str) -> Optional[ReflexDecision]:
        # Mute
        if re.search(r"\b(mute|mute volume|mute sound|ovozni o'chir|tovushni o'chir|ovozsiz qil)\b", text):
            return ReflexDecision(
                choice="system_control",
                confidence=0.97,
                action_type="system_control",
                params={"action": "set", "feature": "volume", "value": "0"},
                is_reflex_action=True,
                display_label="Ovoz o'chirildi",
                matched_phrase="mute"
            )
        # Unmute
        if re.search(r"\b(unmute|unmute volume|ovozni yoq|tovushni yoq)\b", text):
            return ReflexDecision(
                choice="system_control",
                confidence=0.97,
                action_type="system_control",
                params={"action": "set", "feature": "volume", "value": "50"},
                is_reflex_action=True,
                display_label="Ovoz yoqildi",
                matched_phrase="unmute"
            )
        # Volume Up
        if re.search(r"\b(volume up|increase volume|louder|ovozni balandlat|ovozni oshir|tovushni balandlat)\b", text):
            return ReflexDecision(
                choice="system_control",
                confidence=0.96,
                action_type="system_control",
                params={"action": "up", "feature": "volume"},
                is_reflex_action=True,
                display_label="Ovoz balandlatildi",
                matched_phrase="volume up"
            )
        # Volume Down
        if re.search(r"\b(volume down|decrease volume|quieter|ovozni pasaytir|ovozni kamaytir|tovushni pasaytir)\b", text):
            return ReflexDecision(
                choice="system_control",
                confidence=0.96,
                action_type="system_control",
                params={"action": "down", "feature": "volume"},
                is_reflex_action=True,
                display_label="Ovoz pasaytirildi",
                matched_phrase="volume down"
            )
        return None

    def _check_media(self, text: str) -> Optional[ReflexDecision]:
        # Pause
        if re.search(r"\b(pause music|stop music|pause|musiqani to'xtat|to'xtat musiqani|pauza qil)\b", text):
            return ReflexDecision(
                choice="media_control",
                confidence=0.96,
                action_type="system_control",
                params={"action": "media_control", "value": "pause"},
                is_reflex_action=True,
                display_label="Musiqa to'xtatildi",
                matched_phrase="pause"
            )
        # Play / Resume
        if re.search(r"\b(play music|resume music|play|musiqani qo'y|musiqa qo'y|davom ettir)\b", text):
            return ReflexDecision(
                choice="media_control",
                confidence=0.95,
                action_type="system_control",
                params={"action": "media_control", "value": "play"},
                is_reflex_action=True,
                display_label="Musiqa ijro etilmoqda",
                matched_phrase="play"
            )
        # Next Track
        if re.search(r"\b(next track|next song|skip song|keyingi qo'shiq|keyingisi)\b", text):
            return ReflexDecision(
                choice="media_control",
                confidence=0.95,
                action_type="system_control",
                params={"action": "media_control", "value": "next"},
                is_reflex_action=True,
                display_label="Keyingi qo'shiq",
                matched_phrase="next song"
            )
        return None

    def _check_connectivity(self, text: str) -> Optional[ReflexDecision]:
        # Bluetooth ON
        if re.search(r"\b(turn on bluetooth|enable bluetooth|bluetooth on|bluetooth-ni yoq|bluetoothni yoq)\b", text):
            return ReflexDecision(
                choice="system_control",
                confidence=0.97,
                action_type="system_control",
                params={"action": "on", "feature": "bluetooth"},
                is_reflex_action=True,
                display_label="Bluetooth yoqilmoqda...",
                matched_phrase="bluetooth on"
            )
        # Bluetooth OFF
        if re.search(r"\b(turn off bluetooth|disable bluetooth|bluetooth off|bluetooth-ni o'chir|bluetoothni o'chir)\b", text):
            return ReflexDecision(
                choice="system_control",
                confidence=0.97,
                action_type="system_control",
                params={"action": "off", "feature": "bluetooth"},
                is_reflex_action=True,
                display_label="Bluetooth o'chirilmoqda...",
                matched_phrase="bluetooth off"
            )
        # WiFi ON
        if re.search(r"\b(turn on wifi|enable wifi|wifi on|wi-fi on|wifi-ni yoq|wifini yoq)\b", text):
            return ReflexDecision(
                choice="system_control",
                confidence=0.97,
                action_type="system_control",
                params={"action": "on", "feature": "wifi"},
                is_reflex_action=True,
                display_label="Wi-Fi yoqilmoqda...",
                matched_phrase="wifi on"
            )
        # WiFi OFF
        if re.search(r"\b(turn off wifi|disable wifi|wifi off|wi-fi off|wifi-ni o'chir|wifini o'chir)\b", text):
            return ReflexDecision(
                choice="system_control",
                confidence=0.97,
                action_type="system_control",
                params={"action": "off", "feature": "wifi"},
                is_reflex_action=True,
                display_label="Wi-Fi o'chirilmoqda...",
                matched_phrase="wifi off"
            )
        return None

    def _check_screenshot(self, text: str) -> Optional[ReflexDecision]:
        if re.search(r"\b(take a screenshot|take screenshot|capture screen|ekranni rasmga ol|skrinshot qil|skrinshot ol)\b", text):
            return ReflexDecision(
                choice="take_screenshot",
                confidence=0.96,
                action_type="take_screenshot",
                params={},
                is_reflex_action=True,
                display_label="Skrinshot olinmoqda...",
                matched_phrase="screenshot"
            )
        return None

    def _check_ask_ai(self, text: str) -> Optional[ReflexDecision]:
        """Classifies queries requiring deep reasoning, coding, or prose generation."""
        ai_patterns = [
            r"\b(explain|why|how do i|how can i|what is|tell me about|summarize|help me)\b",
            r"\b(write a|draft a|generate|create a code|code for|debug)\b",
            r"\b(tushuntir|nima uchun|qanday qilib|nima bu|xulosa qil|yozib ber|kod yoz)\b"
        ]
        for pat in ai_patterns:
            if re.search(pat, text):
                return ReflexDecision(
                    choice="ask_ai",
                    confidence=0.92,
                    action_type="gemini_query",
                    params={"query": text},
                    is_reflex_action=False,
                    display_label="O'ylanmoqda...",
                    matched_phrase="ask_ai"
                )
        return None

# Global Singleton Instance
reflex_engine = ReflexEngine()

def execute_reflex_action_sync(decision: ReflexDecision) -> Dict[str, Any]:
    """Executes a native OS action synchronously and returns result."""
    import tools
    action = decision.action_type
    params = decision.params

    print(f"⚡ [Reflex Execution] Triggering native action: {action} with {params}", flush=True)
    if action == "open_app":
        return tools.open_app(params.get("app_name", ""))
    elif action == "close_app":
        return tools.close_app(params.get("app_name", ""))
    elif action == "system_control":
        return tools.system_control(**params)
    elif action == "take_screenshot":
        return tools.take_screenshot()
    elif action == "dismiss_assistant":
        return tools.dismiss_assistant()
    elif action == "stop_agent":
        return tools.stop_agent()
    else:
        return {"status": "error", "message": f"Unknown reflex action: {action}"}
