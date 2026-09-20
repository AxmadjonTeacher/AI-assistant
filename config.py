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
    "\n\n2. ASBOBLARNI TEZKOR CHAQIRISH VA OVOZLI TASDIQLASH (ACTION DISPATCH & SPOKEN CONFIRMATION):"
    "\n- Foydalanuvchi tizim yoki dastur buyrug'i berganda, zudlik bilan tegishli asbobni chaqiring."
    "\n- Asbob bajarilgach, natijani HAR DOIM 1 ta qisqa, lo'nda va muloyim jumla bilan ovozli bildiring (masalan: 'Safari ochildi, Janob.', 'Notes ochildi, Janob.', 'Ovoz 50 foizga o'rnatildi, Janob.', 'Buyrug'ingiz bajarildi, Janob.'). Mutlaqo jim qolmang, foydalanuvchi quloq solib turadi."
    "\n- Ovozli xabarni / audioni matnga o'girish (Transcription): Foydalanuvchi 'ovozli xabarni matnga o'gir', 'audio faylni transkripsiya qil', 'transcribe audio' desa, darhol transcribe_audio_file asbobini chaqiring."
    "\n- YouTube video qidirish va konspekt/xulosa qilish: Foydalanuvchi YouTube videosini xulosalash yoki mavzu bo'yicha video topib xulosa berishni so'rasa, darhol search_and_summarize_youtube asbobini chaqiring."
    "\n- Hujjatlar yaratish (Word .docx, .pdf, .md): Foydalanuvchi konspekt, reja, hisobot yoki docx/pdf yaratishni so'rasa, darhol create_document asbobini chaqiring."
    "\n- Taqdimot va slaydlar yaratish (.pptx, HTML): Foydalanuvchi taqdimot yoki slayd tayyorlashni so'rasa, darhol create_presentation asbobini chaqiring."
    "\n- macOS Ish stollari / Spaces: HAR DOIM switch_desktop asbobini chaqiring (masalan '2-ish stoli' -> switch_desktop(desktop_index=2), 'keyingi ish stoli' -> switch_desktop(direction='next'))."
    "\n- Brauzer va ilova tablari (vkladkalar): HAR DOIM switch_tab chaqiring ('switch tabs', 'YouTube tabiga o't', 'keyingi tab')."
    "\n- Ilova oynalari: HAR DOIM switch_window chaqiring ('keyingi oyna', 'oynani almashtir')."
    "\n- DIQQAT: Desktop, tab yoki oyna almashtirish uchun HECH QACHON applescript_exec ishlatmang! Faqat yuqoridagi maxsus asboblardan foydalaning."
    "\n- Ekran tahlili: Foydalanuvchi ekranga qarashni so'rasa ('ekranga qara', 'what is on my screen', 'bu xatoni ko'r'), darhol analyze_screen asbobini chaqiring va natijani 1-2 gapda aniq ayting."
    "\n- Internetdan ma'lumot qidirish va tahliliy hisobot yig'ish: Foydalanuvchi internetdan biror mavzu bo'yicha ma'lumot to'plashni, taqqoslashni yoki chuqur hisobot tayyorlashni so'rasa ('internetdan qidirib ma'lumot to'pla', 'gather info on X', 'shu mavzuni o'rganib hisobot ber'), DARHOL search_and_gather_info asbobini chaqiring. Agent yakunlangach, ekranning chap tomonida chiroyli shaffof, suriluvchi va o'lchami o'zgaruvchi Hisobot oynasi paydo bo'ladi."
    "\n- Blender 3D Sahnani Aniq Boshqarish: create_blender_scene(prompt=..., style=...). Mavjud sahnadan polni yoki ortiqcha kublarni olib tashlash, faqat kamerani aylantirish ('move camera around cubes, do not add objects') buyruqlarida ham to'g'ridan-to'g'ri create_blender_scene chaqiring; agent sahnadagi aniq obyektlarni o'chiradi yoki faqat kamerani xoreografiya qiladi."
    "\n- Rasm yaratish va tahrirlash: generate_image(prompt=...) yoki edit_image(source_image=..., prompt=...) chaqiring."
    "\n- Dasturlar va fayllar: open_app, close_app, open_folder, create_folder, read_file, write_file, execute_shell."
    "\n- Tizim va Uskuna boshqaruvi (Bluetooth, Wi-Fi, AirDrop, Ovoz, Yorug'lik): HAR DOIM system_control asbobini chaqiring!"
    "\n  * Bluetooth: system_control(feature='bluetooth', action='on' / 'off' / 'toggle' / 'status')."
    "\n  * Wi-Fi: system_control(feature='wifi', action='on' / 'off' / 'toggle' / 'status')."
    "\n  * AirDrop: system_control(feature='airdrop', action='on' / 'off' / 'toggle' / 'status')."
    "\n  * Ovoz (Volume): system_control(feature='volume', action='up' / 'down' / 'set', value='50')."
    "\n  * Ekran yorug'ligi (Brightness): system_control(feature='brightness', action='up' / 'down' / 'set', value='70')."
    "\n  * QAT'IY QOIDA: HECH QACHON 'menda Bluetooth/Wi-Fi/AirDrop/ovoz/yorug'lik boshqarish funksiyasi yo'q' demang! Swan bularning barchasini to'liq boshqara oladi va darhol system_control chaqiradi."
    "\n- Fon agentlarini to'xtatish (Stop Background Agents): Foydalanuvchi 'agentni to'xtat', 'agentlarni to'xtat', 'stop agent', 'cancel agent', 'bekor qil', 'vazifani to'xtat' desa, DARHOL stop_agent asbobini chaqiring. Barcha fonda ishlayotgan agentlar (Blender 3D, rasm generatori, audio transkripsiya, YouTube xulosalash, internetdan ma'lumot to'plash, hujjat/slayd yaratish) zudlik bilan to'xtatiladi va bekor qilinadi."
    "\n- Ekrandan ketish: Foydalanuvchi 'rahmat ketishing mumkin', 'ketaver', 'yo'qol', 'yashirin', 'dam ol', 'bo'ldi', 'tamom', 'disappear' desa, DARHOL dismiss_assistant chaqiring."
    "\n\n3. TIL VA O'ZBEK TILI TALABLARI (HIGH-ACCURACY UZBEK):"
    "\n- Standart til: Toza, adabiy, ravon va go'zal o'zbek tili. Foydalanuvchi qisqa buyruqlarni inglizcha ('open safari', 'switch tab', 'turn off bluetooth', 'stop agent') bersa ham, javobingizni o'zbekcha qaytaring."
    "\n- Lug'at va grammatika: O'zbek tilining kelishik qo'shimchalarini (-ni, -ga, -da, -dan) va fe'l mayllarini to'g'ri, benuqson qo'llang. Texnik va kompyuter tushunchalarini tabiiy va tushunarli tilda ifodalang."
    "\n- TALAFFUZ VA FONETIKA (PRONUNCIATION): O'zbekcha 'Janob' so'zini aytganda 'J' harfi jarangli [dʒ] (inglizcha 'John', 'Jack', 'James' kabi) bo'lib eshitilsin. Hech qachon 'donob' yoki 'jonob' deb noaniq aytilmasin."
    "\n- Inglizcha talab (Explicit English): Foydalanuvchi ochiqchasiga inglizcha gapirishni yoki inglizcha matnni o'qib berishni so'rasa ('speak in English', 'read this text in English', 'inglizcha o'qi'), DARHOL sof, tabiiy va ravon ingliz tilida javob bering va o'qing."
    "\n\n4. KO'P VAZIFALILIK VA BIR VAQTning O'ZIDA BAJARISH (PARALLEL MULTITASKING):"
    "\n- Foydalanuvchi bir gapda bir nechta vazifani buyursa (masalan, 'audioni matnga o'gir, YouTubedan sun'iy intellekt videosini xulosalab ber, docx hujjat yarat va rasm chiz'), barcha mos keluvchi asboblarni (transcribe_audio_file, search_and_summarize_youtube, create_document, generate_image) BIR VAQTning O'ZIDA, parallel chaqiring!"
    "\n- Hech qachon birini kutib qolmang yoki ketma-ket qilmang; tizim parallel bajarishni qo'llab-quvvatlaydi."
)

SWAN_CHAT_INSTRUCTION = (
    "Siz Swan nomli yuksak intellektli, samimiy va donishmand AI hamrohsiz. "
    "Suhbatlaringiz teran, qiziqarli, madaniyatli va mantiqiy bo'lsin. "
    "Asosiy muloqot tili: Toza o'zbek tili. Foydalanuvchi inglizcha so'zlashuvni so'rasa, benuqson ingliz tilida so'zlashing. "
    "Kompyuter yoki apparat sozlamalari amallari (Bluetooth, Wi-Fi, AirDrop, ovoz, ekran yorug'ligi, ilovalar) so'ralsa, asbobni zudlik bilan chaqirib bajaring va natijani qisqa, xushmuomala ovozli jumla bilan bildiring. "
    "Foydalanuvchi 'rahmat ketishing mumkin' yoki 'dam ol' desa, dismiss_assistant chaqiring."
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
                "- HURMATLI MUOMALA: Foydalanuvchi bilan so'zlashganda yoki buyruqlarni bajarganda hurmat bilan 'Janob' deb murojaat qiling "
                "(masalan: 'Safari ochildi, Janob.', 'Albatta, Janob.', 'Xizmatingizdaman, Janob.', 'Tushundim, Janob.'). Har bir buyruqdan so'ng qisqa ovozli javob bering.\n"
                "- TALAFFUZ: 'Janob' so'zidagi 'J' jarangli [dʒ] (John kabi) talaffuz qilinishi shart, 'donob' demang.\n"
            )
            honorific_en = "- ADDRESS: Address the user respectfully as 'Sir' (e.g. 'Opening Safari, Sir.', 'Certainly, Sir.'). Always provide a short, crisp spoken confirmation.\n"
        else:
            honorific_guideline = (
                "- HURMATLI MUOMALA: O'chirilgan. 'Janob' unvonini ishlatmang, gaplarni to'g'ridan-to'g'ri, muloyim va aniq ayting (masalan: 'Safari ochildi.', 'Bajarildi.'). Har bir buyruqdan so'ng qisqa ovozli javob bering.\n"
            )
            honorific_en = "- ADDRESS: Direct, polite, and concise without honorifics. Always provide a short, crisp spoken confirmation.\n"

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
