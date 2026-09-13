import os
from datetime import datetime
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

SWAN_COMMAND_INSTRUCTION = (
    "Siz Swan nomli macOS tizimidagi eng yuksak intellektli, tezkor va sadoqatli avtonom AI agentisiz. "
    "Muloqot tarzingiz: yuksak ziyoli, vazmin, xushmuomala va o'ta aniq (JARVIS kabi). "
    "\n\n1. INTELLEKT VA SUHBAT MADANIYATI:"
    "\n- Savollarga, tahlillarga yoki suhbatlarga chuqur mantiq, teran bilim va qisqa, go'zal jumlalar bilan javob bering."
    "\n- Hech qachon o'rinsiz uzr so'ramang ('men adashibman', 'kechirasiz' deb o'zingizni kamsitmang), ortiqcha byurokratik gaplardan qoching. Vaziyatni doimo professional, xotirjam va nafis nazorat qiling."
    "\n\n2. ASBOBLARNI TEZKOR CHAQIRISH (ACTION-FIRST DISPATCH):"
    "\n- Foydalanuvchi tizim buyrug'i berganda, zudlik bilan tegishli asbobni chaqiring. Asbob bajarilgach, natijani 1 ta qisqa, lo'nda jumla bilan bildiring."
    "\n- macOS Ish stollari / Spaces: HAR DOIM switch_desktop asbobini chaqiring (masalan '2-ish stoli' -> switch_desktop(desktop_index=2), 'keyingi ish stoli' -> switch_desktop(direction='next'))."
    "\n- Brauzer va ilova tablari (vkladkalar): HAR DOIM switch_tab chaqiring ('switch tabs', 'YouTube tabiga o't', 'keyingi tab')."
    "\n- Ilova oynalari: HAR DOIM switch_window chaqiring ('keyingi oyna', 'oynani almashtir')."
    "\n- DIQQAT: Desktop, tab yoki oyna almashtirish uchun HECH QACHON applescript_exec ishlatmang! Faqat yuqoridagi maxsus asboblardan foydalaning."
    "\n- Ekran tahlili: Foydalanuvchi ekranga qarashni so'rasa ('ekranga qara', 'what is on my screen', 'bu xatoni ko'r'), darhol analyze_screen asbobini chaqiring va natijani 1-2 gapda aniq ayting."
    "\n- Rasm yaratish va tahrirlash: generate_image(prompt=...) yoki edit_image(source_image=..., prompt=...) chaqiring."
    "\n- Blender 3D: create_blender_scene(prompt=..., reference_image=...) chaqiring."
    "\n- Dasturlar va fayllar: open_app, close_app, open_folder, create_folder, read_file, write_file, execute_shell."
    "\n- Musiqa: spotify_control(action='play', query=...)."
    "\n- Ekrandan ketish: Foydalanuvchi 'yo'qol', 'yashirin', 'dam ol', 'disappear' desa, darhol dismiss_assistant chaqiring."
    "\n\n3. TIL QOIDALARI:"
    "\n- Standart til: Toza, adabiy va chiroyli o'zbek tili. Foydalanuvchi qisqa buyruqlarni inglizcha ('open safari', 'switch tab') bersa ham, javobingizni o'zbekcha qaytaring."
    "\n- Inglizcha talab (Explicit English): Foydalanuvchi ochiqchasiga inglizcha gapirishni yoki inglizcha matnni o'qib berishni so'rasa ('speak in English', 'read this text in English', 'inglizcha o'qi'), DARHOL sof, tabiiy va ravon ingliz tilida javob bering va o'qing."
    "\n\n4. KO'P VAZIFALILIK VA FON AGENTLARI:"
    "\n- Orqa fonda biror agent (masalan rasm yoki 3D) ishlayotgan paytda foydalanuvchi yangi buyruq bersa, ishlab turgan agentni to'xtatmang. Yangi buyruq uchun tegishli asbobni parallel ishga tushiring."
)

SWAN_CHAT_INSTRUCTION = (
    "Siz Swan nomli yuksak intellektli, samimiy va donishmand AI hamrohsiz. "
    "Suhbatlaringiz teran, qiziqarli, madaniyatli va mantiqiy bo'lsin. "
    "Asosiy muloqot tili: Toza o'zbek tili. Foydalanuvchi inglizcha so'zlashuvni so'rasa, benuqson ingliz tilida so'zlashing. "
    "Suhbat davomida kompyuter amallari yoki asboblar so'ralsa, ularni zudlik bilan chaqirib bajaring."
)

from resource_helper import get_resource_path, get_data_path, get_data_dir

load_dotenv()
support_env = os.path.join(get_data_dir(), ".env")
if os.path.exists(support_env):
    load_dotenv(support_env)

import json

SETTINGS_FILE = get_data_path("swan_settings.json")

@dataclass
class AppConfig:
    api_key: str = os.getenv("GEMINI_API_KEY", "")
    model: str = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-live-preview")
    voice_name: str = os.getenv("VOICE_NAME", "Aoede")  # 'Aoede' (Female), 'Charon' (Male)
    respectful_address: bool = True  # True: 'sir'/'Janob'/'efendim'; False: no honorific
    user_name: str = os.getenv("USER_NAME", "Janob")
    mode: str = os.getenv("DEFAULT_MODE", "command")  # 'command' or 'chat'
    language: str = os.getenv("DEFAULT_LANGUAGE", "uz")  # 'uz', 'tr', 'en'
    wake_sensitivity: str = os.getenv("WAKE_SENSITIVITY", "medium")  # 'low', 'medium', 'high'
    sample_rate_in: int = 16000
    sample_rate_out: int = 24000
    channels: int = 1
    input_device: str = os.getenv("AUDIO_INPUT_DEVICE", "default")
    output_device: str = os.getenv("AUDIO_OUTPUT_DEVICE", "default")
    min_recording_seconds: float = 0.25
    play_chimes: bool = False

    def __post_init__(self):
        self.load_persisted_settings()

    def load_persisted_settings(self):
        self.language = "uz"
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    data = json.load(f)
                    if "api_key" in data and data["api_key"]:
                        self.api_key = str(data["api_key"]).strip()
                    if "wake_sensitivity" in data and data["wake_sensitivity"] in ["low", "medium", "high"]:
                        self.wake_sensitivity = data["wake_sensitivity"]
                    if "mode" in data and data["mode"] in ["command", "chat"]:
                        self.mode = data["mode"]
                    if "voice_name" in data and data["voice_name"] in ["Aoede", "Charon"]:
                        self.voice_name = data["voice_name"]
                    else:
                        self.voice_name = "Aoede"
                    if "respectful_address" in data:
                        self.respectful_address = bool(data["respectful_address"])
                    if "language" in data and data["language"] in ["uz", "en", "tr"]:
                        self.language = data["language"]
            except Exception as e:
                print(f"[WARN] Could not load settings: {e}")

    def save_persisted_settings(self):
        try:
            data = {
                "language": self.language,
                "wake_sensitivity": self.wake_sensitivity,
                "mode": self.mode,
                "voice_name": self.voice_name,
                "respectful_address": self.respectful_address
            }
            if self.api_key:
                data["api_key"] = self.api_key
            with open(SETTINGS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[WARN] Could not save settings: {e}")

    def get_system_instruction(self, active_mode: str = None, active_language: str = None) -> str:
        current_mode = active_mode or self.mode
        base_instruction = SWAN_CHAT_INSTRUCTION if current_mode == "chat" else SWAN_COMMAND_INSTRUCTION

        # Honorific / Respectful address rule
        if self.respectful_address:
            honorific_guideline = (
                "- HURMATLI MUOMALA: Foydalanuvchiga har doim hurmat bilan 'Janob' deb murojaat qiling "
                "(masalan: 'Safari ochilmoqda, Janob.', 'Xizmatingizdaman, Janob.', 'Tushundim, Janob.').\n"
            )
            honorific_en = "- ADDRESS: Address the user respectfully as 'Sir' (e.g. 'Opening Safari, Sir.', 'At your service, Sir.').\n"
        else:
            honorific_guideline = (
                "- HURMATLI MUOMALA: O'chirilgan. 'Janob' unvonini ishlatmang, gaplarni to'g'ridan-to'g'ri, muloyim va aniq ayting "
                "(masalan: 'Safari ochilmoqda.', 'Tushundim.', 'Bajarildi.').\n"
            )
            honorific_en = "- ADDRESS: Direct, polite, and concise without honorifics.\n"

        target_lang = (active_language or self.language or "uz").lower()
        if target_lang == "en":
            language_instruction = (
                f"\n\nPRIMARY LANGUAGE RULE (ENGLISH):\n"
                f"- Your active language is ENGLISH.\n"
                f"{honorific_en}"
                f"- Speak, read, and respond naturally, politely, and fluently in English.\n"
                f"- When asked to read text or examine screen elements, deliver responses in clear, articulate English.\n"
            )
        else:
            language_instruction = (
                f"\n\nTIL VA MUOMALA:\n"
                f"- Asosiy muloqot tili: Toza, adabiy o'zbek tili.\n"
                f"{honorific_guideline}"
                f"- Foydalanuvchi inglizcha so'zlashuvni yoki inglizcha matn o'qishni so'rasa, to'g'ridan-to'g'ri tabiiy ingliz tilida javob bering.\n"
            )

        now = datetime.now().astimezone()
        time_24 = now.strftime("%H:%M")
        time_12 = now.strftime("%I:%M %p").lstrip("0")
        tz_offset = now.strftime("%z")
        tz_formatted = f"UTC{tz_offset[:3]}:{tz_offset[3:]}" if len(tz_offset) == 5 else f"UTC{tz_offset}"
        date_str = now.strftime("%A, %B %d, %Y")
        time_context = (
            f"\n\nJORIY MAHALLIY VAQT VA SANA:\n"
            f"- Foydalanuvchining mahalliy vaqt mintaqasi: {tz_formatted}\n"
            f"- Hozirgi mahalliy vaqt: {time_24} ({time_12}), {date_str}\n"
            f"- Foydalanuvchi vaqt yoki sanani o'zi so'ragandagina uning REAL mahalliy vaqtini ayting yoki get_current_time asbobini chaqiring. Foydalanuvchi so'ramasa, o'zicha vaqtni aytmang!\n"
            f"- QAT'IYAN TAQIQLANADI: UTC yoki GMT yoki server vaqtini aytmang."
        )

        try:
            from memory_manager import memory_manager
            mem_block = "\n\n" + memory_manager.get_system_prompt_block()
        except Exception:
            mem_block = ""

        return base_instruction + language_instruction + time_context + mem_block

config = AppConfig()
