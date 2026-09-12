import os
import random
import wave
import numpy as np

class AudioPromptsManager:
    def __init__(self, sounds_dir: str = "sounds"):
        self.sounds_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), sounds_dir)
        # Structure: prompts[voice_key][lang][respectful: bool]
        self.prompts = {
            "aoede": {
                "en": {True: [], False: []},
                "uz": {True: [], False: []},
                "tr": {True: [], False: []}
            },
            "charon": {
                "en": {True: [], False: []},
                "uz": {True: [], False: []},
                "tr": {True: [], False: []}
            }
        }
        self._load_prompts()

    def _load_file(self, filename: str, label: str):
        path = os.path.join(self.sounds_dir, filename)
        if os.path.isfile(path):
            try:
                with wave.open(path, "rb") as wf:
                    frames = wf.readframes(wf.getnframes())
                    data = np.frombuffer(frames, dtype=np.int16)
                    return {
                        "id": filename,
                        "label": label,
                        "pcm_np": data,
                        "raw_bytes": frames
                    }
            except Exception as e:
                print(f"[WARN] Failed to load sound prompt {filename}: {e}")
        return None

    def _load_prompts(self):
        definitions = [
            # AOEDE (Female - Calm & Soothing)
            ("aoede", "en", True, "ack_yes_sir.wav", "Yes, sir."),
            ("aoede", "en", True, "ack_listening.wav", "Listening, sir."),
            ("aoede", "en", False, "ack_en_listening_plain.wav", "Listening."),

            ("aoede", "uz", True, "ack_uz_eshitaman.wav", "Eshitaman janob"),
            ("aoede", "uz", False, "ack_uz_eshitaman_plain.wav", "Eshitaman"),

            ("aoede", "tr", True, "ack_tr_emredersiniz.wav", "Emredersiniz, efendim."),
            ("aoede", "tr", True, "ack_tr_dinliyorum.wav", "Dinliyorum, efendim."),
            ("aoede", "tr", False, "ack_tr_emredersiniz_plain.wav", "Emredersiniz."),
            ("aoede", "tr", False, "ack_tr_dinliyorum_plain.wav", "Dinliyorum."),

            # CHARON (Male - Distinguished Butler)
            ("charon", "en", True, "charon_en_yes_sir.wav", "Yes, sir."),
            ("charon", "en", True, "charon_en_listening_sir.wav", "Listening, sir."),
            ("charon", "en", False, "charon_en_listening_plain.wav", "Listening."),

            ("charon", "uz", True, "charon_uz_eshitaman.wav", "Eshitaman janob"),
            ("charon", "uz", False, "charon_uz_eshitaman_plain.wav", "Eshitaman"),

            ("charon", "tr", True, "charon_tr_emredersiniz.wav", "Emredersiniz, efendim."),
            ("charon", "tr", True, "charon_tr_dinliyorum.wav", "Dinliyorum, efendim."),
            ("charon", "tr", False, "charon_tr_dinliyorum_plain.wav", "Dinliyorum.")
        ]
        for voice_key, lang, respectful, filename, label in definitions:
            p = self._load_file(filename, label)
            if p and voice_key in self.prompts:
                self.prompts[voice_key][lang][respectful].append(p)

    def get_random_prompt(self, language: str = "uz", voice_name: str = "Aoede", respectful: bool = True):
        """Returns a random acknowledgment prompt matching voice persona, language (Uzbek) and respectful preference: (pcm_numpy_array, text_label)"""
        v_low = (voice_name or "Aoede").lower()

        # Map to Aoede (Female) or Charon (Male)
        if "charon" in v_low:
            primary_key = "charon"
            fallback_key = "aoede"
        else:
            primary_key = "aoede"
            fallback_key = "charon"

        target_lang = "uz"

        # 1. Try primary voice key with requested language and respectful setting
        chosen_list = []
        if primary_key in self.prompts:
            lang_dict = self.prompts[primary_key].get(target_lang, {})
            chosen_list = lang_dict.get(respectful) or []

        # 2. Try primary voice key with opposite respectful setting if empty
        if not chosen_list and primary_key in self.prompts:
            lang_dict = self.prompts[primary_key].get(target_lang, {})
            chosen_list = lang_dict.get(not respectful) or []

        # 3. Fall back to fallback voice key
        if not chosen_list and fallback_key in self.prompts:
            lang_dict = self.prompts[fallback_key].get(target_lang, {})
            chosen_list = lang_dict.get(respectful) or lang_dict.get(not respectful) or []

        if not chosen_list:
            fallback_text = "Eshitaman, Janob." if respectful else "Eshitaman."
            return None, fallback_text

        chosen = random.choice(chosen_list)
        return chosen["pcm_np"], chosen["label"]

audio_prompts = AudioPromptsManager()
