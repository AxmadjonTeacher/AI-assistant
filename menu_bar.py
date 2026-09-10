import objc
from Cocoa import (
    NSStatusBar, NSMenu, NSMenuItem, NSObject
)
from typing import Callable, Optional
from PyObjCTools import AppHelper

class MenuBarActionTarget(NSObject):
    @objc.IBAction
    def toggleMode_(self, sender):
        if hasattr(self, "on_mode_toggle") and self.on_mode_toggle:
            self.on_mode_toggle()

    @objc.IBAction
    def toggleWakeWord_(self, sender):
        if hasattr(self, "on_wake_toggle") and self.on_wake_toggle:
            self.on_wake_toggle()

    @objc.IBAction
    def setLanguageUz_(self, sender):
        if hasattr(self, "on_language_change") and self.on_language_change:
            self.on_language_change("uz")

    @objc.IBAction
    def setLanguageEn_(self, sender):
        if hasattr(self, "on_language_change") and self.on_language_change:
            self.on_language_change("en")

    @objc.IBAction
    def setLanguageTr_(self, sender):
        if hasattr(self, "on_language_change") and self.on_language_change:
            self.on_language_change("tr")

    @objc.IBAction
    def setSensitivityLow_(self, sender):
        if hasattr(self, "on_sensitivity_change") and self.on_sensitivity_change:
            self.on_sensitivity_change("low")

    @objc.IBAction
    def setSensitivityMedium_(self, sender):
        if hasattr(self, "on_sensitivity_change") and self.on_sensitivity_change:
            self.on_sensitivity_change("medium")

    @objc.IBAction
    def setSensitivityHigh_(self, sender):
        if hasattr(self, "on_sensitivity_change") and self.on_sensitivity_change:
            self.on_sensitivity_change("high")

    @objc.IBAction
    def setVoiceAoede_(self, sender):
        if hasattr(self, "on_voice_change") and self.on_voice_change:
            self.on_voice_change("Aoede")

    @objc.IBAction
    def setVoiceCharon_(self, sender):
        if hasattr(self, "on_voice_change") and self.on_voice_change:
            self.on_voice_change("Charon")

    @objc.IBAction
    def setVoiceKore_(self, sender):
        if hasattr(self, "on_voice_change") and self.on_voice_change:
            self.on_voice_change("Kore")

    @objc.IBAction
    def setVoiceFenrir_(self, sender):
        if hasattr(self, "on_voice_change") and self.on_voice_change:
            self.on_voice_change("Fenrir")

    @objc.IBAction
    def setVoicePuck_(self, sender):
        if hasattr(self, "on_voice_change") and self.on_voice_change:
            self.on_voice_change("Puck")

    @objc.IBAction
    def setAccentBritish_(self, sender):
        if hasattr(self, "on_accent_change") and self.on_accent_change:
            self.on_accent_change("british")

    @objc.IBAction
    def setAccentAmerican_(self, sender):
        if hasattr(self, "on_accent_change") and self.on_accent_change:
            self.on_accent_change("american")

    @objc.IBAction
    def setAccentNeutral_(self, sender):
        if hasattr(self, "on_accent_change") and self.on_accent_change:
            self.on_accent_change("neutral")

    @objc.IBAction
    def toggleRespectful_(self, sender):
        if hasattr(self, "on_respectful_toggle") and self.on_respectful_toggle:
            self.on_respectful_toggle()

    @objc.IBAction
    def openSettings_(self, sender):
        if hasattr(self, "on_open_settings") and self.on_open_settings:
            self.on_open_settings()

    @objc.IBAction
    def quitApp_(self, sender):
        if hasattr(self, "on_quit") and self.on_quit:
            self.on_quit()

class SwanMenuBar:
    def __init__(
        self,
        on_mode_toggle: Optional[Callable[[], None]] = None,
        on_wake_toggle: Optional[Callable[[], None]] = None,
        on_language_change: Optional[Callable[[str], None]] = None,
        on_sensitivity_change: Optional[Callable[[str], None]] = None,
        on_voice_change: Optional[Callable[[str], None]] = None,
        on_accent_change: Optional[Callable[[str], None]] = None,
        on_respectful_toggle: Optional[Callable[[], None]] = None,
        on_open_settings: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None
    ):
        self.on_mode_toggle = on_mode_toggle
        self.on_wake_toggle = on_wake_toggle
        self.on_language_change = on_language_change
        self.on_sensitivity_change = on_sensitivity_change
        self.on_voice_change = on_voice_change
        self.on_accent_change = on_accent_change
        self.on_respectful_toggle = on_respectful_toggle
        self.on_open_settings = on_open_settings
        self.on_quit = on_quit

        self.status_item = None
        self.menu = None
        self.status_menu_item = None
        self.mode_menu_item = None
        self.wake_menu_item = None
        self.lang_parent_item = None
        self.sens_parent_item = None
        self.voice_parent_item = None
        self.accent_parent_item = None
        self.respectful_menu_item = None
        self.target = None

        self._lang_items = {}
        self._sens_items = {}
        self._voice_items = {}
        self._accent_items = {}

        self._init_menu_bar()

    def _init_menu_bar(self):
        status_bar = NSStatusBar.systemStatusBar()
        self.status_item = status_bar.statusItemWithLength_(-1)
        self.status_item.button().setTitle_("🦢")

        self.target = MenuBarActionTarget.alloc().init()
        self.target.on_mode_toggle = self.on_mode_toggle
        self.target.on_wake_toggle = self.on_wake_toggle
        self.target.on_language_change = self.on_language_change
        self.target.on_sensitivity_change = self.on_sensitivity_change
        self.target.on_voice_change = self.on_voice_change
        self.target.on_accent_change = self.on_accent_change
        self.target.on_respectful_toggle = self.on_respectful_toggle
        self.target.on_open_settings = self.on_open_settings
        self.target.on_quit = self.on_quit

        self.menu = NSMenu.alloc().init()

        # Item 1: Status
        self.status_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Swan: Ready (Listening for 'Hey Swan')", None, ""
        )
        self.status_menu_item.setEnabled_(False)
        self.menu.addItem_(self.status_menu_item)

        self.menu.addItem_(NSMenuItem.separatorItem())

        # Item 2: Mode Toggle
        self.mode_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Mode: Command (Click to switch)", objc.selector(self.target.toggleMode_, signature=b"v@:@"), ""
        )
        self.mode_menu_item.setTarget_(self.target)
        self.menu.addItem_(self.mode_menu_item)

        # Item 3: Wake Word Toggle
        self.wake_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Wake Word: Enabled ('Swan')", objc.selector(self.target.toggleWakeWord_, signature=b"v@:@"), ""
        )
        self.wake_menu_item.setTarget_(self.target)
        self.menu.addItem_(self.wake_menu_item)

        # Item 3b: Wake Sensitivity Submenu
        sens_menu = NSMenu.alloc().init()
        self._sens_items["low"] = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Low (Anti-YouTube Media Shield)", objc.selector(self.target.setSensitivityLow_, signature=b"v@:@"), ""
        )
        self._sens_items["low"].setTarget_(self.target)
        sens_menu.addItem_(self._sens_items["low"])

        self._sens_items["medium"] = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Medium (Balanced Default)", objc.selector(self.target.setSensitivityMedium_, signature=b"v@:@"), ""
        )
        self._sens_items["medium"].setTarget_(self.target)
        sens_menu.addItem_(self._sens_items["medium"])

        self._sens_items["high"] = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "High (Sensitive)", objc.selector(self.target.setSensitivityHigh_, signature=b"v@:@"), ""
        )
        self._sens_items["high"].setTarget_(self.target)
        sens_menu.addItem_(self._sens_items["high"])

        self.sens_parent_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Wake Sensitivity: Medium", None, ""
        )
        self.sens_parent_item.setSubmenu_(sens_menu)
        self.menu.addItem_(self.sens_parent_item)

        self.menu.addItem_(NSMenuItem.separatorItem())

        # Item 3c: Language Submenu
        lang_menu = NSMenu.alloc().init()
        self._lang_items["uz"] = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "O'zbek tili (Uzbek)", objc.selector(self.target.setLanguageUz_, signature=b"v@:@"), ""
        )
        self._lang_items["uz"].setTarget_(self.target)
        lang_menu.addItem_(self._lang_items["uz"])

        self._lang_items["en"] = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "English", objc.selector(self.target.setLanguageEn_, signature=b"v@:@"), ""
        )
        self._lang_items["en"].setTarget_(self.target)
        lang_menu.addItem_(self._lang_items["en"])

        self._lang_items["tr"] = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Türkçe (Turkish)", objc.selector(self.target.setLanguageTr_, signature=b"v@:@"), ""
        )
        self._lang_items["tr"].setTarget_(self.target)
        lang_menu.addItem_(self._lang_items["tr"])

        self.lang_parent_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Language: O'zbek tili", None, ""
        )
        self.lang_parent_item.setSubmenu_(lang_menu)
        self.menu.addItem_(self.lang_parent_item)

        # Item 3d: Voice Model Submenu
        voice_menu = NSMenu.alloc().init()
        self._voice_items["Aoede"] = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Aoede (Female - Natural & Poised)", objc.selector(self.target.setVoiceAoede_, signature=b"v@:@"), ""
        )
        self._voice_items["Aoede"].setTarget_(self.target)
        voice_menu.addItem_(self._voice_items["Aoede"])

        self._voice_items["Charon"] = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Charon (Male - Distinguished Butler)", objc.selector(self.target.setVoiceCharon_, signature=b"v@:@"), ""
        )
        self._voice_items["Charon"].setTarget_(self.target)
        voice_menu.addItem_(self._voice_items["Charon"])

        self._voice_items["Kore"] = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Kore (Female - Calm & Soothing)", objc.selector(self.target.setVoiceKore_, signature=b"v@:@"), ""
        )
        self._voice_items["Kore"].setTarget_(self.target)
        voice_menu.addItem_(self._voice_items["Kore"])

        self._voice_items["Fenrir"] = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Fenrir (Male - Authoritative)", objc.selector(self.target.setVoiceFenrir_, signature=b"v@:@"), ""
        )
        self._voice_items["Fenrir"].setTarget_(self.target)
        voice_menu.addItem_(self._voice_items["Fenrir"])

        self._voice_items["Puck"] = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Puck (Male - Upbeat & Energetic)", objc.selector(self.target.setVoicePuck_, signature=b"v@:@"), ""
        )
        self._voice_items["Puck"].setTarget_(self.target)
        voice_menu.addItem_(self._voice_items["Puck"])

        self.voice_parent_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Voice: Aoede", None, ""
        )
        self.voice_parent_item.setSubmenu_(voice_menu)
        self.menu.addItem_(self.voice_parent_item)

        # Item 3e: English Accent Submenu
        accent_menu = NSMenu.alloc().init()
        self._accent_items["british"] = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "🇬🇧 British Butler (RP)", objc.selector(self.target.setAccentBritish_, signature=b"v@:@"), ""
        )
        self._accent_items["british"].setTarget_(self.target)
        accent_menu.addItem_(self._accent_items["british"])

        self._accent_items["american"] = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "🇺🇸 American (General American)", objc.selector(self.target.setAccentAmerican_, signature=b"v@:@"), ""
        )
        self._accent_items["american"].setTarget_(self.target)
        accent_menu.addItem_(self._accent_items["american"])

        self._accent_items["neutral"] = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "🌐 Neutral (Clean)", objc.selector(self.target.setAccentNeutral_, signature=b"v@:@"), ""
        )
        self._accent_items["neutral"].setTarget_(self.target)
        accent_menu.addItem_(self._accent_items["neutral"])

        self.accent_parent_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Accent: British", None, ""
        )
        self.accent_parent_item.setSubmenu_(accent_menu)
        self.menu.addItem_(self.accent_parent_item)

        # Item 3f: Respectful Address Toggle
        self.respectful_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Respectful Address: Enabled ('sir' / 'Janob')", objc.selector(self.target.toggleRespectful_, signature=b"v@:@"), ""
        )
        self.respectful_menu_item.setTarget_(self.target)
        self.menu.addItem_(self.respectful_menu_item)

        self.menu.addItem_(NSMenuItem.separatorItem())

        # Item 4: Shortcuts Submenu
        shortcuts_menu = NSMenu.alloc().init()
        
        item_ptt = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Push-to-Talk: ⌥ Option + ⇧ Shift (Hold)", None, ""
        )
        item_ptt.setEnabled_(False)
        shortcuts_menu.addItem_(item_ptt)
        
        item_esc = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Instant Dismiss: Esc (Cancel & Silence)", None, ""
        )
        item_esc.setEnabled_(False)
        shortcuts_menu.addItem_(item_esc)
        
        item_wake = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Wake Words: 'Swan' or 'Hey Swan'", None, ""
        )
        item_wake.setEnabled_(False)
        shortcuts_menu.addItem_(item_wake)

        item_close = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Close Apps: 'Close [App]', 'Quit [App]'", None, ""
        )
        item_close.setEnabled_(False)
        shortcuts_menu.addItem_(item_close)

        item_files = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Files: 'Open [Folder]', 'Create Folder [Name]', 'Move [Files]'", None, ""
        )
        item_files.setEnabled_(False)
        shortcuts_menu.addItem_(item_files)
        
        shortcuts_menu.addItem_(NSMenuItem.separatorItem())

        item_open_guide = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "View All Shortcuts & Commands...", objc.selector(self.target.openSettings_, signature=b"v@:@"), ""
        )
        item_open_guide.setTarget_(self.target)
        shortcuts_menu.addItem_(item_open_guide)

        shortcuts_parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Shortcuts & Voice Guide", None, ""
        )
        shortcuts_parent.setSubmenu_(shortcuts_menu)
        self.menu.addItem_(shortcuts_parent)

        # Item 5: Settings & Customizations
        settings_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Settings & Customizations...", objc.selector(self.target.openSettings_, signature=b"v@:@"), ","
        )
        settings_item.setTarget_(self.target)
        self.menu.addItem_(settings_item)

        self.menu.addItem_(NSMenuItem.separatorItem())

        # Item 6: Quit
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit Swan", objc.selector(self.target.quitApp_, signature=b"v@:@"), "q"
        )
        quit_item.setTarget_(self.target)
        self.menu.addItem_(quit_item)

        self.status_item.setMenu_(self.menu)

    def set_status(self, text: str):
        AppHelper.callAfter(self._main_set_status, text)

    def _main_set_status(self, text: str):
        if self.status_menu_item:
            self.status_menu_item.setTitle_(f"Swan: {text}")

    def set_mode(self, mode: str):
        AppHelper.callAfter(self._main_set_mode, mode)

    def _main_set_mode(self, mode: str):
        if self.mode_menu_item:
            display = mode.capitalize()
            self.mode_menu_item.setTitle_(f"Mode: {display} (Click to switch)")

    def set_wake_word_enabled(self, enabled: bool):
        AppHelper.callAfter(self._main_set_wake_word_enabled, enabled)

    def _main_set_wake_word_enabled(self, enabled: bool):
        if self.wake_menu_item:
            status = "Enabled ('Swan')" if enabled else "Disabled (Hotkey only)"
            self.wake_menu_item.setTitle_(f"Wake Word: {status}")

    def set_language(self, lang: str):
        AppHelper.callAfter(self._main_set_language, lang)

    def _main_set_language(self, lang: str):
        names = {
            "uz": "O'zbek tili",
            "en": "English",
            "tr": "Türkçe"
        }
        name = names.get(lang, "English")
        if self.lang_parent_item:
            self.lang_parent_item.setTitle_(f"Language: {name}")
        for code, item in self._lang_items.items():
            item.setState_(1 if code == lang else 0)

    def set_sensitivity(self, sens: str):
        AppHelper.callAfter(self._main_set_sensitivity, sens)

    def _main_set_sensitivity(self, sens: str):
        names = {
            "low": "Low (Media Safe)",
            "medium": "Medium",
            "high": "High"
        }
        name = names.get(sens, "Medium")
        if self.sens_parent_item:
            self.sens_parent_item.setTitle_(f"Wake Sensitivity: {name}")
        for code, item in self._sens_items.items():
            item.setState_(1 if code == sens else 0)

    def set_voice(self, voice: str):
        AppHelper.callAfter(self._main_set_voice, voice)

    def _main_set_voice(self, voice: str):
        if self.voice_parent_item:
            self.voice_parent_item.setTitle_(f"Voice: {voice}")
        for code, item in self._voice_items.items():
            item.setState_(1 if code == voice else 0)

    def set_accent(self, accent: str):
        AppHelper.callAfter(self._main_set_accent, accent)

    def _main_set_accent(self, accent: str):
        names = {
            "british": "British Butler (RP)",
            "american": "General American",
            "neutral": "Neutral"
        }
        name = names.get(accent, "British")
        if self.accent_parent_item:
            self.accent_parent_item.setTitle_(f"Accent: {name}")
        for code, item in self._accent_items.items():
            item.setState_(1 if code == accent else 0)

    def set_respectful(self, enabled: bool):
        AppHelper.callAfter(self._main_set_respectful, enabled)

    def _main_set_respectful(self, enabled: bool):
        if self.respectful_menu_item:
            title = "Respectful Address: Enabled ('sir' / 'Janob')" if enabled else "Respectful Address: Disabled (No honorifics)"
            self.respectful_menu_item.setTitle_(title)
            self.respectful_menu_item.setState_(1 if enabled else 0)
