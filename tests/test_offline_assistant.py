import unittest
import numpy as np
from offline_assistant import (
    OfflineTTS,
    AudioCapture,
    OllamaBrain,
    OSController,
    OfflineVoiceAssistant,
    SYSTEM_PROMPT
)

class TestOfflineAssistant(unittest.TestCase):
    def test_os_controller_hotkey(self):
        ctrl = OSController()
        # Hotkey execution test
        success, msg = ctrl.execute({"action": "hotkey", "target": ["command", "c"]})
        self.assertTrue(success)
        self.assertIn("command+c", msg)

    def test_os_controller_volume(self):
        ctrl = OSController()
        success, msg = ctrl.execute({"action": "volume", "target": "up"})
        self.assertTrue(success)

    def test_tts_initialization(self):
        tts = OfflineTTS()
        self.assertIsNotNone(tts)

    def test_ollama_brain_initialization(self):
        brain = OllamaBrain(model_name="swan:latest")
        self.assertIsNotNone(brain.host)
        self.assertTrue(len(SYSTEM_PROMPT) > 50)

if __name__ == "__main__":
    unittest.main()
