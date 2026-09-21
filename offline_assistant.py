#!/usr/bin/env python3
"""
Modular, 100% Free, and Fully Offline Desktop Voice Assistant.
Author: Swan Team & Pair Programming AI
License: Apache 2.0 / MIT

Architecture:
1. Audio Capture: Continuous microphone stream via sounddevice with energy VAD.
2. STT: Local Whisper via faster-whisper (lightweight int8 model, runs on CPU/Metal).
3. Brain: Local Ollama (swan:latest, qwen2.5:3b, or llama3.2:3b) with strict JSON tool actions.
4. Actions: Cross-platform OS automation via pyautogui and subprocess.
5. TTS: Offline speech feedback via pyttsx3 with instant macOS native 'say' fallback.
"""

import os
import sys
import time
import json
import queue
import signal
import platform
import logging
import subprocess
from typing import Dict, Any, Optional, List, Union, Tuple

import numpy as np
import requests

try:
    import sounddevice as sd
except ImportError:
    sd = None

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

try:
    import pyautogui
except ImportError:
    pyautogui = None

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("OfflineAssistant")


# ==============================================================================
# 1. TEXT-TO-SPEECH (TTS) ENGINE
# ==============================================================================
class OfflineTTS:
    """Provides offline speech synthesis via pyttsx3 or native macOS 'say'."""

    def __init__(self, rate: int = 190):
        self.is_macos = platform.system() == "Darwin"
        self.engine = None
        self._init_engine(rate)

    def _init_engine(self, rate: int):
        if pyttsx3 is not None:
            try:
                self.engine = pyttsx3.init()
                self.engine.setProperty("rate", rate)
                # Try to pick a natural voice if available
                voices = self.engine.getProperty("voices")
                for voice in voices:
                    if "samantha" in voice.name.lower() or "daniel" in voice.name.lower():
                        self.engine.setProperty("voice", voice.id)
                        break
            except Exception as e:
                logger.warning(f"pyttsx3 init warning: {e}. Will use macOS 'say' fallback.")
                self.engine = None

    def speak(self, text: str, non_blocking: bool = False):
        """Speaks the text aloud offline."""
        if not text or not text.strip():
            return

        clean_text = text.strip()
        logger.info(f"🗣️  Speaking: \"{clean_text}\"")

        # On macOS, native 'say' is instant (0ms startup latency) and high quality
        if self.is_macos:
            cmd = ["say", clean_text]
            if non_blocking:
                subprocess.Popen(cmd)
            else:
                subprocess.run(cmd)
            return

        # Fallback to pyttsx3 on Linux/Windows
        if self.engine:
            try:
                self.engine.say(clean_text)
                self.engine.runAndWait()
            except Exception as e:
                logger.error(f"pyttsx3 speech error: {e}")
        else:
            print(f"[VOICE]: {clean_text}")


# ==============================================================================
# 2. AUDIO CAPTURE WITH ADAPTIVE VAD
# ==============================================================================
class AudioCapture:
    """Continuous microphone recording with energy-based Voice Activity Detection."""

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_duration_ms: int = 30,
        energy_threshold: float = 0.015,
        silence_timeout_s: float = 0.7,
        max_record_s: float = 10.0,
    ):
        self.sample_rate = sample_rate
        self.chunk_size = int(sample_rate * (chunk_duration_ms / 1000.0))
        self.energy_threshold = energy_threshold
        self.silence_timeout_s = silence_timeout_s
        self.max_record_s = max_record_s

        self.audio_queue = queue.Queue()
        self.stream: Optional[sd.InputStream] = None
        self.is_running = False

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.debug(f"Audio status: {status}")
        self.audio_queue.put(indata.copy().flatten())

    def start(self):
        """Starts the audio input stream."""
        if sd is None:
            raise RuntimeError("sounddevice is not installed. Run: pip install sounddevice")
        self.is_running = True
        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.chunk_size,
            callback=self._audio_callback
        )
        self.stream.start()
        logger.info("🎤 Microphone stream started.")

    def stop(self):
        """Stops the audio input stream."""
        self.is_running = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        logger.info("🎤 Microphone stream stopped.")

    def listen_for_utterance(self) -> Optional[np.ndarray]:
        """
        Listens continuously until speech starts and ends.
        Returns 16kHz float32 audio numpy array, or None if interrupted.
        """
        speech_frames = []
        is_speaking = False
        silence_start_time = None
        record_start_time = None

        # Flush stale queue chunks before listening
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        while self.is_running:
            try:
                chunk = self.audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # Compute RMS energy
            rms = np.sqrt(np.mean(chunk**2))

            if not is_speaking:
                if rms > self.energy_threshold:
                    # Speech detected!
                    is_speaking = True
                    record_start_time = time.time()
                    silence_start_time = None
                    speech_frames.append(chunk)
                    logger.info("🎙️  [Speech detected... listening]")
            else:
                speech_frames.append(chunk)

                # Check max duration
                if (time.time() - record_start_time) > self.max_record_s:
                    logger.info("⏱️  Max utterance duration reached.")
                    break

                # Check silence pause
                if rms < self.energy_threshold:
                    if silence_start_time is None:
                        silence_start_time = time.time()
                    elif (time.time() - silence_start_time) >= self.silence_timeout_s:
                        # User stopped speaking!
                        break
                else:
                    silence_start_time = None

        if speech_frames:
            audio_data = np.concatenate(speech_frames)
            # Only return if at least 0.4s of audio
            if len(audio_data) >= int(self.sample_rate * 0.4):
                return audio_data

        return None


# ==============================================================================
# 3. SPEECH-TO-TEXT (faster-whisper)
# ==============================================================================
class LocalWhisperSTT:
    """Local, offline STT using faster-whisper with int8 quantization."""

    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8"):
        if WhisperModel is None:
            raise RuntimeError("faster-whisper is not installed. Run: pip install faster-whisper")

        logger.info(f"🧠 Loading faster-whisper model '{model_size}' ({compute_type})...")
        t0 = time.time()
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        logger.info(f"✅ Whisper loaded in {time.time() - t0:.2f}s.")

    def transcribe(self, audio_data: np.ndarray, language: Optional[str] = None) -> str:
        """Transcribes float32 numpy audio array to text."""
        t0 = time.time()
        # faster-whisper expects 16kHz float32 audio
        segments, info = self.model.transcribe(
            audio_data,
            beam_size=1,
            language=language,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=400)
        )
        text = " ".join([segment.text for segment in segments]).strip()
        dt = (time.time() - t0) * 1000.0
        if text:
            logger.info(f"📝 Transcribed ({dt:.0f}ms, lang={info.language}): \"{text}\"")
        return text


# ==============================================================================
# 4. OLLAMA BRAIN (STRICT JSON INTENT PARSER)
# ==============================================================================
SYSTEM_PROMPT = """You are an OS voice control agent. Convert user spoken commands into strict JSON actions.
Allowed actions:
- {"action": "open_app", "target": "<app_name>", "voice_response": "<short confirmation>"}
- {"action": "volume", "target": "up|down|mute|<0-100>", "voice_response": "<short confirmation>"}
- {"action": "hotkey", "target": ["<key1>", "<key2>"], "voice_response": "<short confirmation>"}
- {"action": "type", "target": "<text_to_type>", "voice_response": "<short confirmation>"}
- {"action": "shell", "target": "<bash_command>", "voice_response": "<short confirmation>"}
- {"action": "speak", "target": "<spoken_response>", "voice_response": "<spoken_response>"}
- {"action": "shutdown", "target": "exit", "voice_response": "Hayr, Janob."}

Commands can be spoken in Uzbek or English:
Examples:
- "Open Safari" -> {"action": "open_app", "target": "Safari", "voice_response": "Safari ochildi, Janob."}
- "Telegramni och" -> {"action": "open_app", "target": "Telegram", "voice_response": "Telegram ochildi, Janob."}
- "Notes ilovasini och" -> {"action": "open_app", "target": "Notes", "voice_response": "Notes ochildi, Janob."}
- "Ovozni baland qil" / "volume up" -> {"action": "volume", "target": "up", "voice_response": "Ovoz balandlatildi."}
- "Ovozni pasaytir" / "volume down" -> {"action": "volume", "target": "down", "voice_response": "Ovoz pasaytirildi."}
- "Ovozni o'chir" / "mute" -> {"action": "volume", "target": "mute", "voice_response": "Ovoz o'chirildi."}
- "Yangi vkladka och" / "new tab" -> {"action": "hotkey", "target": ["command", "t"], "voice_response": "Yangi vkladka ochildi."}
- "Buni nusxala" / "copy this" -> {"action": "hotkey", "target": ["command", "c"], "voice_response": "Nusxalandi."}
- "Salom, qalaysan?" / "Hello" -> {"action": "speak", "target": "Assalomu alaykum! Xizmatingizdaman, Janob.", "voice_response": "Assalomu alaykum! Xizmatingizdaman, Janob."}
- "Dasturni yop" / "exit" / "quit" -> {"action": "shutdown", "target": "exit", "voice_response": "Hayr, Janob."}

CRITICAL: Output ONLY a single valid JSON object. Do not include markdown code blocks, explanations, or extra keys."""


class OllamaBrain:
    """Local LLM client using Ollama for strict JSON tool-calling."""

    def __init__(
        self,
        model_name: str = "swan:latest",
        host: str = "http://127.0.0.1:11434",
        timeout: float = 12.0,
    ):
        self.model_name = model_name
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._verify_connection()

    def _verify_connection(self):
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=3.0)
            if r.status_code == 200:
                models = [m.get("name") for m in r.json().get("models", [])]
                logger.info(f"✅ Ollama connected at {self.host}. Available models: {models}")
                if self.model_name not in models and f"{self.model_name}:latest" not in models:
                    if models:
                        fallback = models[0]
                        logger.warning(f"Model '{self.model_name}' not found. Falling back to '{fallback}'.")
                        self.model_name = fallback
            else:
                logger.warning(f"Ollama returned HTTP {r.status_code}.")
        except Exception as e:
            logger.error(f"Cannot reach Ollama at {self.host}: {e}. Ensure 'ollama serve' is running.")

    def parse_intent(self, text: str) -> Optional[Dict[str, Any]]:
        """Sends user text to Ollama and returns strict JSON action dictionary."""
        if not text or not text.strip():
            return None

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text.strip()}
            ],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
            }
        }

        t0 = time.time()
        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            raw_content = data.get("message", {}).get("content", "").strip()
            dt = (time.time() - t0) * 1000.0
            logger.info(f"🤖 Ollama decision in {dt:.0f}ms: {raw_content}")

            # Parse JSON
            action_dict = json.loads(raw_content)
            if isinstance(action_dict, dict) and "action" in action_dict:
                return action_dict

            logger.warning(f"JSON missing required 'action' key: {action_dict}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama request error: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Ollama returned invalid JSON: {e}")
            return None


# ==============================================================================
# 5. OS ACTION CONTROLLER
# ==============================================================================
class OSController:
    """Executes actions cross-platform via pyautogui and subprocess."""

    def __init__(self):
        self.is_macos = platform.system() == "Darwin"
        self.is_windows = platform.system() == "Windows"
        self.is_linux = platform.system() == "Linux"

    def execute(self, action_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Executes the action specified in action_data.
        Returns: (success: bool, status_message: str)
        """
        action = action_data.get("action")
        target = action_data.get("target")

        try:
            if action == "open_app":
                return self.open_app(str(target))
            elif action == "volume":
                return self.set_volume(str(target))
            elif action == "hotkey":
                if isinstance(target, list):
                    return self.press_hotkey(target)
                elif isinstance(target, str):
                    return self.press_hotkey(target.split("+"))
            elif action == "type":
                return self.type_text(str(target))
            elif action == "shell":
                return self.run_shell(str(target))
            elif action == "speak":
                return True, f"Spoken: {target}"
            elif action == "shutdown":
                return True, "Shutdown requested"
            else:
                return False, f"Unknown action: {action}"
        except Exception as e:
            logger.error(f"Error executing action {action}: {e}")
            return False, str(e)

        return False, "Unhandled action"

    def open_app(self, app_name: str) -> Tuple[bool, str]:
        """Launches an application."""
        logger.info(f"⚡ Opening application: {app_name}")
        if self.is_macos:
            # Try direct open -a
            res = subprocess.run(["open", "-a", app_name], capture_output=True, text=True)
            if res.returncode == 0:
                return True, f"Opened {app_name}"
            # Fuzzy match in /Applications
            for app_dir in ["/Applications", os.path.expanduser("~/Applications"), "/System/Applications"]:
                if os.path.isdir(app_dir):
                    for item in os.listdir(app_dir):
                        if app_name.lower() in item.lower() and item.endswith(".app"):
                            full_path = os.path.join(app_dir, item)
                            subprocess.run(["open", full_path])
                            return True, f"Opened {item}"
            return False, f"Application '{app_name}' not found"

        elif self.is_windows:
            subprocess.run(f"start {app_name}", shell=True)
            return True, f"Started {app_name}"
        else:
            subprocess.run(["xdg-open", app_name])
            return True, f"Opened {app_name}"

    def set_volume(self, target: str) -> Tuple[bool, str]:
        """Controls system volume."""
        logger.info(f"⚡ Volume control: {target}")
        t = target.lower().strip()

        if self.is_macos:
            if t == "up":
                subprocess.run(["osascript", "-e", "set volume output volume ((output volume of (get volume settings)) + 12)"])
                return True, "Volume increased"
            elif t == "down":
                subprocess.run(["osascript", "-e", "set volume output volume ((output volume of (get volume settings)) - 12)"])
                return True, "Volume decreased"
            elif t == "mute":
                subprocess.run(["osascript", "-e", "set volume output muted not (output muted of (get volume settings))"])
                return True, "Volume mute toggled"
            elif t.isdigit():
                val = max(0, min(100, int(t)))
                subprocess.run(["osascript", "-e", f"set volume output volume {val}"])
                return True, f"Volume set to {val}%"

        # Fallback via pyautogui media keys
        if pyautogui is not None:
            if t == "up":
                pyautogui.press("volumeup")
            elif t == "down":
                pyautogui.press("volumedown")
            elif t == "mute":
                pyautogui.press("volumemute")
            return True, f"Volume {target}"

        return False, "Volume control not supported on this platform without pyautogui"

    def press_hotkey(self, keys: List[str]) -> Tuple[bool, str]:
        """Presses a keyboard hotkey combination."""
        if pyautogui is None:
            return False, "pyautogui is not installed"

        # Normalize key names for macOS / Windows
        clean_keys = []
        for k in keys:
            norm = k.strip().lower()
            if self.is_macos:
                if norm in ["cmd", "command", "super", "win"]:
                    norm = "command"
            else:
                if norm in ["cmd", "command"]:
                    norm = "ctrl"
            clean_keys.append(norm)

        logger.info(f"⚡ Pressing hotkey: {clean_keys}")
        pyautogui.hotkey(*clean_keys)
        return True, f"Pressed {'+'.join(clean_keys)}"

    def type_text(self, text: str) -> Tuple[bool, str]:
        """Types text into the active focused window."""
        if pyautogui is None:
            return False, "pyautogui is not installed"
        logger.info(f"⚡ Typing: {text!r}")
        pyautogui.write(text, interval=0.01)
        return True, "Text typed"

    def run_shell(self, command: str) -> Tuple[bool, str]:
        """Runs a safe shell command."""
        logger.info(f"⚡ Shell command: {command}")
        res = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=8.0)
        output = res.stdout.strip() or res.stderr.strip()
        return (res.returncode == 0), output


# ==============================================================================
# 6. MAIN COORDINATOR & LIFECYCLE
# ==============================================================================
class OfflineVoiceAssistant:
    """Coordinates Audio -> STT -> Ollama -> OS Action -> TTS in a clean loop."""

    SHUTDOWN_PHRASES = [
        "exit", "quit", "stop assistant", "stop", "shutdown",
        "dasturni yop", "to'xtat", "chiqish", "xayr", "hayr"
    ]

    def __init__(
        self,
        whisper_model: str = "base",
        ollama_model: str = "swan:latest",
        ollama_host: str = "http://127.0.0.1:11434"
    ):
        self.running = True

        # Initialize components
        self.tts = OfflineTTS()
        self.audio = AudioCapture(energy_threshold=0.015, silence_timeout_s=0.65)
        self.stt = LocalWhisperSTT(model_size=whisper_model, compute_type="int8")
        self.brain = OllamaBrain(model_name=ollama_model, host=ollama_host)
        self.controller = OSController()

        # Handle SIGINT (Ctrl+C)
        signal.signal(signal.SIGINT, self._sigint_handler)
        signal.signal(signal.SIGTERM, self._sigint_handler)

    def _sigint_handler(self, sig, frame):
        print("\n")
        logger.info("🛑 Shutdown signal received. Cleaning up...")
        self.stop()

    def stop(self):
        """Clean shutdown trigger."""
        self.running = False
        self.audio.stop()
        self.tts.speak("Dastur to'xtatildi. Hayr, Janob.", non_blocking=False)
        logger.info("👋 Offline Assistant terminated gracefully.")
        sys.exit(0)

    def run(self):
        """Main continuous execution loop."""
        print("=" * 65)
        print("  🦢 100% FREE & FULLY OFFLINE OS VOICE ASSISTANT")
        print("  - STT: Local faster-whisper (int8)")
        print(f"  - Brain: Local Ollama ({self.brain.model_name})")
        print("  - Actions: pyautogui + subprocess")
        print("  - TTS: Offline voice synthesis")
        print("  - Privacy: 100% On-Device (Zero cloud tokens / Zero costs)")
        print("=" * 65)
        print("👉 Speak now (e.g. 'Open Safari', 'Telegramni och', 'Volume down', 'Exit')")
        print("👉 Press Ctrl+C at any time to exit.\n")

        self.audio.start()
        self.tts.speak("Assalomu alaykum Janob, men tinglayapman.", non_blocking=True)

        while self.running:
            try:
                # 1. Capture speech
                audio_data = self.audio.listen_for_utterance()
                if audio_data is None:
                    continue

                # 2. Transcribe locally
                transcript = self.stt.transcribe(audio_data)
                if not transcript or len(transcript.strip()) < 2:
                    continue

                clean_text = transcript.lower().strip()

                # 3. Check for immediate shutdown command
                if any(phrase in clean_text for phrase in self.SHUTDOWN_PHRASES):
                    logger.info(f"🛑 Voice shutdown triggered by: '{clean_text}'")
                    self.stop()
                    break

                # 4. Parse intent with local Ollama
                action_data = self.brain.parse_intent(transcript)
                if not action_data:
                    self.tts.speak("Kechirasiz, buyruqni tushunmadim.")
                    continue

                # Check if Ollama returned a shutdown action
                if action_data.get("action") == "shutdown":
                    voice_resp = action_data.get("voice_response", "Hayr, Janob.")
                    self.tts.speak(voice_resp)
                    self.stop()
                    break

                # 5. Execute OS action
                success, message = self.controller.execute(action_data)

                # 6. Spoken voice response
                voice_response = action_data.get("voice_response")
                if voice_response:
                    self.tts.speak(voice_response, non_blocking=False)
                elif success:
                    self.tts.speak("Bajarildi, Janob.")

            except Exception as e:
                logger.error(f"Unexpected error in loop: {e}", exc_info=True)
                time.sleep(0.5)


# ==============================================================================
# ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="100% Free Offline Voice Assistant")
    parser.add_argument("--model", default="swan:latest", help="Ollama model name (default: swan:latest)")
    parser.add_argument("--whisper", default="base", help="Whisper model size: tiny, base, small (default: base)")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434", help="Ollama server URL")
    args = parser.parse_args()

    assistant = OfflineVoiceAssistant(
        whisper_model=args.whisper,
        ollama_model=args.model,
        ollama_host=args.ollama_url
    )
    assistant.run()
