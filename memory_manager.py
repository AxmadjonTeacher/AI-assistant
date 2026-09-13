import os
import json
import time
import re
from datetime import datetime
from typing import Dict, Any, List, Optional

from resource_helper import get_data_path

MEMORY_FILE = get_data_path("swan_memory.json")

DEFAULT_MEMORY: Dict[str, Any] = {
    "owner": {
        "name": "Ahmet",
        "title": "Janob",
        "language": "uz",
        "role": "Dasturchi / Software Engineer"
    },
    "preferences": [
        "Javoblar har doim toza va adabiy o'zbek tilida bo'lsin.",
        "Javoblar lo'nda, tezkor va aniq harakatga yo'naltirilgan bo'lsin.",
        "Murojaat har doim hurmat bilan 'Janob' deb bo'lsin.",
        "Musiqa tinglash uchun Spotify ishlatiladi.",
        "Ekranni tahlil qilish (Vision) va tezkor brauzer boshqaruvi yoqilgan.",
        "Ochiq oynalar orasida o'tish: Ctrl + Arrow Left / Right orqali boshqariladi."
    ],
    "learned_facts": [
        "Ismi: Ahmet (Janob)",
        "Tizim: macOS",
        "Til: O'zbek tili (mutlaq)",
        "Ish uslubi: Aniq, tezkor buyruqlar, ish stollari va tablar boshqaruvi",
        "Oynalar orasida o'tish: Ctrl + Arrow Left yoki Right"
    ],
    "last_updated": datetime.now().isoformat()
}

class MemoryManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MemoryManager, cls).__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self.file_path = MEMORY_FILE
        self.data = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.isfile(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    if isinstance(content, dict) and "owner" in content:
                        return content
            except Exception as e:
                print(f"[MemoryManager] Error loading memory: {e}, recreating default.", flush=True)
        # Create default
        self._save_to_disk(DEFAULT_MEMORY)
        return dict(DEFAULT_MEMORY)

    def _save_to_disk(self, data: Dict[str, Any]):
        try:
            data["last_updated"] = datetime.now().isoformat()
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[MemoryManager] Error saving memory: {e}", flush=True)

    def save(self):
        self._save_to_disk(self.data)

    def get_owner_info(self) -> Dict[str, str]:
        return self.data.get("owner", DEFAULT_MEMORY["owner"])

    def get_learned_facts(self) -> List[str]:
        return self.data.get("learned_facts", [])

    def get_preferences(self) -> List[str]:
        return self.data.get("preferences", [])

    def add_fact(self, fact: str, category: Optional[str] = None) -> bool:
        """Adds a permanent learned fact about the user or their preferences."""
        fact = fact.strip()
        if not fact:
            return False

        facts = self.data.setdefault("learned_facts", [])
        for existing in facts:
            if existing.lower() == fact.lower():
                return False

        facts.append(fact)
        if len(facts) > 50:
            facts.pop(0)

        self.save()
        print(f"🧠 [Memory] New fact memorized: '{fact}'", flush=True)
        return True

    def remove_fact(self, fact_text: str) -> bool:
        """Removes a specific fact from memory."""
        facts = self.data.get("learned_facts", [])
        new_facts = [f for f in facts if f.lower() != fact_text.strip().lower()]
        if len(new_facts) != len(facts):
            self.data["learned_facts"] = new_facts
            self.save()
            print(f"🧠 [Memory] Fact removed: '{fact_text}'", flush=True)
            return True
        return False

    def clear_memory(self):
        """Resets learned memory to baseline."""
        self.data = dict(DEFAULT_MEMORY)
        self.save()
        print("🧠 [Memory] Long-term memory reset to baseline.", flush=True)

    def get_system_prompt_block(self) -> str:
        """Generates a concise contextual memory injection block for Gemini's system instruction."""
        owner = self.get_owner_info()
        name = owner.get("name", "Ahmet")
        title = owner.get("title", "Janob")
        
        facts = self.get_learned_facts()
        prefs = self.get_preferences()

        lines = [
            f"FOYDALANUVCHI HAQIDA BILIMLAR VA XOTIRA (LONG-TERM MEMORY):",
            f"- Ega: {name} (Murojaat: '{title}').",
            f"- Til: Har doim toza va adabiy o'zbek tilida so'zlash.",
            "- Foydalanuvchi afzalliklari:"
        ]
        for p in prefs[:4]:
            lines.append(f"  * {p}")

        if facts:
            lines.append("- Eslab qolingan muhim faktlar:")
            for f in facts[-8:]:
                lines.append(f"  * {f}")

        lines.append(
            "Siz egangizni juda yaxshi taniysiz, uning uslubiga moslashasiz va "
            "u bergan oldingi ko'rsatmalar hamda afzalliklarni hech qachon unutmaysiz."
        )
        return "\n".join(lines)

    async def maybe_extract_and_remember(self, user_utterance: str, assistant_reply: str = ""):
        """
        Asynchronously inspects conversation turns to extract long-term preferences
        without blocking real-time voice streaming.
        """
        if not user_utterance or len(user_utterance.strip()) < 4:
            return

        text = user_utterance.strip()

        explicit_patterns = [
            r"(?:eslab qol|yodingda saqla|esingda tut|remember that|remember)\s*[:,]?\s*(.+)",
            r"(?:mening ismim|mening nomim|ismim)\s+([A-Za-zА-Яа-яʻʼ]+)",
            r"(?:men\s+(?:har doim|odatda|faqat)\s+)(.+)",
            r"(?:menga\s+)(.+)(?:\s+yoqadi|\s+ma'qul)",
            r"(?:bundan keyin|keyingi safar)\s*(.+)"
        ]

        for pat in explicit_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                extracted = m.group(1).strip()
                if len(extracted) > 3:
                    fact_str = f"Foydalanuvchi: {extracted}"
                    self.add_fact(fact_str)
                    return

memory_manager = MemoryManager()
