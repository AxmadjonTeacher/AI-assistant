import asyncio
import signal
import sys
import time
import os
import fcntl
import threading
from typing import Optional

LOCK_FILE = "/tmp/swan_assistant.lock"
_lock_fd = None

def acquire_single_instance_lock() -> bool:
    global _lock_fd
    try:
        _lock_fd = open(LOCK_FILE, "w")
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fd.write(f"{os.getpid()}\n")
        _lock_fd.flush()
        return True
    except (IOError, BlockingIOError):
        return False

from Cocoa import (
    NSApplication, NSDate, NSDefaultRunLoopMode, NSEventMaskAny,
    NSMenu, NSMenuItem, NSObject
)
import objc
from PyObjCTools import AppHelper

class SwanAppDelegate(NSObject):
    app_ref = None

    def applicationDockMenu_(self, sender):
        menu = NSMenu.alloc().init()
        item_ask = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Ask Swan", "askSwanFromDock:", "")
        item_ask.setTarget_(self)
        menu.addItem_(item_ask)

        item_settings = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Settings...", "openSettingsFromDock:", "")
        item_settings.setTarget_(self)
        menu.addItem_(item_settings)

        menu.addItem_(NSMenuItem.separatorItem())

        item_quit = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit Swan", "quitFromDock:", "q")
        item_quit.setTarget_(self)
        menu.addItem_(item_quit)
        return menu

    @objc.IBAction
    def askSwanFromDock_(self, sender):
        if self.app_ref:
            self.app_ref.trigger_assistant()

    @objc.IBAction
    def openSettingsFromDock_(self, sender):
        if self.app_ref:
            self.app_ref._open_settings()

    @objc.IBAction
    def quitFromDock_(self, sender):
        if self.app_ref:
            self.app_ref._quit()

    def applicationShouldHandleReopen_hasVisibleWindows_(self, sender, flag):
        # Trigger assistant (liquid pill) immediately when Dock icon is clicked!
        if self.app_ref:
            self.app_ref.trigger_assistant()
        return True

    def applicationShouldTerminate_(self, sender):
        if self.app_ref:
            self.app_ref._quit()
        return 1

from config import config
from audio_manager import AudioManager
from hotkey_manager import HotkeyManager
from gemini_client import GeminiLiveClient
from tools import set_mode_callback, set_dismiss_callback, set_language_callback
from hud_window import LiquidHUDWindow
from menu_bar import SwanMenuBar
from settings_window import SettingsWindow
from wake_word_detector import WakeWordDetector
from audio_prompts import audio_prompts

class SwanApp:
    def __init__(self):
        # 1. Cocoa Application
        self.cocoa_app = NSApplication.sharedApplication()
        # Set activation policy to regular (0) so Dock shows proper Quit and Settings
        self.cocoa_app.setActivationPolicy_(0)
        self.app_delegate = SwanAppDelegate.alloc().init()
        self.app_delegate.app_ref = self
        self.cocoa_app.setDelegate_(self.app_delegate)
        self.cocoa_app.finishLaunching()

        # 2. UI Components
        self.settings_window = SettingsWindow(
            on_mode_toggle=self._toggle_mode,
            on_mode_change=self._handle_mode_change,
            on_wake_toggle=self._toggle_wake_word,
            on_language_change=self._handle_language_change,
            on_sensitivity_change=self._handle_sensitivity_change,
            on_voice_change=self._handle_voice_change,
            on_respectful_toggle=self._handle_respectful_toggle,
            on_quit=self._quit
        )
        self.hud = LiquidHUDWindow()
        self.menu_bar = SwanMenuBar(
            on_ask_swan=self.trigger_assistant,
            on_mode_toggle=self._toggle_mode,
            on_wake_toggle=self._toggle_wake_word,
            on_language_change=self._handle_language_change,
            on_sensitivity_change=self._handle_sensitivity_change,
            on_voice_change=self._handle_voice_change,
            on_respectful_toggle=self._handle_respectful_toggle,
            on_open_settings=self._open_settings,
            on_quit=self._quit
        )

        # Greet on launch so user visually sees the liquid pill immediately
        AppHelper.callLater(0.5, lambda: self.hud.show(state="wake", status="SWAN", subtitle="Tayyorman, Janob"))
        AppHelper.callLater(2.8, lambda: self.hud.hide())

        # 3. Audio & AI Core
        self.audio_manager = AudioManager()
        self.client = GeminiLiveClient(initial_mode=config.mode)
        self.client.on_tool_executed = self._handle_tool_executed
        set_dismiss_callback(self.dismiss)

        # 4. Wake Word & Hotkey
        self.wake_detector = WakeWordDetector(
            on_wake_callback=self._on_wake_word_triggered,
            on_interrupt_callback=self._on_speech_interrupted,
            sample_rate=config.sample_rate_in,
            sensitivity=config.wake_sensitivity
        )
        self.audio_manager.set_wake_word_callback(self.wake_detector.process_audio)
        self.audio_manager.set_interruption_callback(self.wake_detector.process_interruption)

        self.hotkey_manager = HotkeyManager(
            on_press=self._on_hotkey_press,
            on_release=self._on_hotkey_release,
            on_dismiss=self.dismiss,
            on_toggle_wake=self._toggle_wake_word,
            is_active_cb=self._is_active
        )

        # Internal state
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._async_thread: Optional[threading.Thread] = None
        self._running = True
        self._busy = False
        self._cancel_requested = False
        self._interrupted = False
        self._active_turn_future = None
        self._current_client_turn_task: Optional[asyncio.Task] = None
        self._hotkey_recording_start = 0.0
        self._keepalive_task = None
        self._active_transcript = ""
        self._last_assistant_speech = ""
        self._active_prompt_label = "Listening, sir."
        self._active_action = ""
        self._paused_media_on_wake = False
        self._media_explicitly_stopped = False

    def start(self):
        """Starts background asyncio loop and runs Cocoa main event loop."""
        self._loop = asyncio.new_event_loop()
        self._async_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._async_thread.start()

        print(" Running Cocoa main event loop on main thread...")
        AppHelper.runEventLoop()
        print(" Cocoa main event loop stopped.")

    def _run_async_loop(self):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_main())
        except Exception as e:
            print(f"[ERROR in async loop]: {e}")

    async def _async_main(self):
        print("🦢 Swan OS initializing...")

        # Mode change callback
        set_mode_callback(self._handle_mode_change)

        # Language change callback
        set_language_callback(self._handle_language_change)

        # Connect to Gemini Live API
        self.menu_bar.set_status("Connecting to Gemini Live...")
        try:
            await self.client.connect()
            print(" Connected to Gemini Live API.")
        except Exception as e:
            print(f"❌ [WARN] Gemini Live connection failed: {e}. Will retry in background.")

        # Start hotkey manager
        self.hotkey_manager.start()

        # Update initial menu bar
        self.menu_bar.set_status("Ready (Listening for 'Hey Swan')")
        self.menu_bar.set_mode(config.mode)
        self.menu_bar.set_wake_word_enabled(self.wake_detector.enabled)
        self.menu_bar.set_language(config.language)
        self.menu_bar.set_sensitivity(config.wake_sensitivity)
        self.menu_bar.set_voice(config.voice_name)
        self.menu_bar.set_respectful(config.respectful_address)
        print(" Swan is ready! Say 'Swan' or 'Hey Swan', or hold Option + Shift.")

        # Background tasks
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        asyncio.create_task(self._hud_rms_loop())

        while self._running:
            await asyncio.sleep(0.5)

    async def _hud_rms_loop(self):
        """Continuously feeds audio energy RMS into the Liquid HUD when visible."""
        last_rms = 0.0
        while self._running:
            if self.hud._is_visible:
                rms = self.audio_manager.get_active_rms()
                if abs(rms - last_rms) > 0.012 or rms > 0.04:
                    last_rms = rms
                    self.hud.set_audio_energy(rms)
            await asyncio.sleep(0.05)

    def _open_settings(self):
        if hasattr(self, "settings_window") and self.settings_window:
            self.settings_window.update_state(
                mode=self.client.active_mode,
                wake_enabled=self.wake_detector.enabled,
                language=config.language,
                sensitivity=config.wake_sensitivity,
                voice_name=config.voice_name,
                respectful=config.respectful_address
            )
            self.settings_window.show()

    def _toggle_mode(self):
        new_mode = "chat" if self.client.active_mode == "command" else "command"
        self._handle_mode_change(new_mode)

    def _is_active(self) -> bool:
        """Returns True if Swan is currently active, listening, speaking, or visible."""
        hud_vis = getattr(self.hud, "_is_visible", False)
        return self._busy or self.audio_manager.is_recording() or self.audio_manager.is_playing() or hud_vis

    def _on_speech_interrupted(self, reason: str = "", is_dismiss: bool = False):
        """Called immediately when user speaks an interruption or dismiss keyword during assistant playback."""
        print(f"🛑 [Barge-In] Playback interrupted: {reason} (is_dismiss={is_dismiss})", flush=True)

        # 1. Instant Dismissal: Only on explicit command to vanish/disappear
        explicit_dismiss_phrases = [
            "disappear", "vanish", "go away", "get lost", "good bye", "goodbye",
            "yo'qol", "yashirin", "ekrandan ket", "dam ol", "yo'q bo'l"
        ]
        is_explicit_dismiss = is_dismiss and any(w in reason.lower() for w in explicit_dismiss_phrases)
        if is_explicit_dismiss:
            print(f"💨 [Instant Vanish] User voice explicitly dismissed Swan ({reason}). Vanishing immediately.", flush=True)
            self.dismiss()
            return

        # 2. Regular Interruption: stop audio playback immediately and transition to listening for user follow-up
        self._interrupted = True
        self.audio_manager.interrupt_playback()
        self.hud.set_state("listening", "LISTENING", "Listening...")
        self.menu_bar.set_status("Listening...")

        # Immediately abort in-flight Gemini streaming task so assistant transitions to listening without delay
        if self._current_client_turn_task and not self._current_client_turn_task.done() and self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._current_client_turn_task.cancel)

    def dismiss(self):
        """Immediately interrupts and dismisses Swan (via Escape or Option + Escape)."""
        print("🛑 [Dismiss] Hotkey/Escape triggered instant dismiss.", flush=True)
        self._cancel_requested = True
        self._interrupted = True

        # 1. Stop audio playback immediately
        self.audio_manager.interrupt_playback()

        # 2. Stop microphone recording
        if self.audio_manager.is_recording():
            self.audio_manager.stop_recording(play_chime=False)

        # 3. Cancel active turn task if running
        if self._active_turn_future and not self._active_turn_future.done():
            self._active_turn_future.cancel()

        # 4. Hide HUD with zero delay
        self.hud.hide(delay=0.0)

        # 5. Reset menu bar status
        status_text = "Ready (Listening for 'Hey Swan')" if self.wake_detector.enabled else "Wake Word: OFF"
        self.menu_bar.set_status(status_text)

        # 6. Re-arm wake detector
        self.wake_detector.reset()
        self._busy = False
        self._resume_media_if_appropriate()

    def _pause_media_if_playing(self) -> bool:
        """Pauses playing media (Spotify or Apple Music) on macOS so user and assistant can communicate clearly."""
        script = '''
        set wasPlaying to false
        if application "Spotify" is running then
            try
                tell application "Spotify"
                    if player state is playing then
                        pause
                        set wasPlaying to true
                    end if
                end tell
            end try
        end if
        if application "Music" is running then
            try
                tell application "Music"
                    if player state is playing then
                        pause
                        set wasPlaying to true
                    end if
                end tell
            end try
        end if
        return wasPlaying
        '''
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=1.5)
            was_playing = res.stdout.strip().lower() == "true"
            if was_playing:
                print("🎵 [Media Auto-Paused] Paused playing media so assistant can hear user clearly.", flush=True)
            return was_playing
        except Exception:
            return False

    def _resume_media_if_appropriate(self):
        """Resumes media playback if it was paused on wake and user didn't explicitly ask to stop/pause."""
        if getattr(self, "_paused_media_on_wake", False) and not getattr(self, "_media_explicitly_stopped", False):
            self._paused_media_on_wake = False
            script = '''
            if application "Spotify" is running then
                try
                    tell application "Spotify" to play
                end try
            else if application "Music" is running then
                try
                    tell application "Music" to play
                end try
            end if
            '''
            try:
                subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=1.5)
                print("🎵 [Media Resumed] Resumed playback after conversation concluded.", flush=True)
            except Exception:
                pass

    def _toggle_wake_word(self):
        new_state = not self.wake_detector.enabled
        self.wake_detector.enabled = new_state
        self.menu_bar.set_wake_word_enabled(new_state)
        if hasattr(self, "settings_window") and self.settings_window:
            self.settings_window.update_state(
                mode=self.client.active_mode,
                wake_enabled=new_state,
                language=config.language,
                sensitivity=config.wake_sensitivity,
                voice_name=config.voice_name,
                respectful=config.respectful_address
            )
        label = "Wake Word: ON" if new_state else "Wake Word: OFF"
        print(f"🎙️ [Wake Word Toggled] {label}", flush=True)
        self.menu_bar.set_status("Ready (Listening for 'Hey Swan')" if new_state else "Wake Word: OFF")

    def trigger_assistant(self):
        print("🎙️ [Trigger Assistant] Summoning Swan Liquid Pill...", flush=True)
        if not self._running:
            return
        if self._busy:
            self.hud.show(state="speaking", status="SWAN", subtitle=self._active_action or "Gapirmoqda...")
            return

        self._on_wake_word_triggered(suffix="")

    def _quit(self):
        print(" [DEBUG] _quit() invoked from MenuBar/Dock")
        self._running = False
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.shutdown(), self._loop)
        AppHelper.callLater(0.3, AppHelper.stopEventLoop)
        AppHelper.callLater(0.5, lambda: NSApplication.sharedApplication().terminate_(None))

    def _handle_mode_change(self, new_mode: str):
        config.mode = new_mode
        config.save_persisted_settings()
        if self.client:
            self.client.set_mode(new_mode)
        self.menu_bar.set_mode(new_mode)
        if hasattr(self, "settings_window") and self.settings_window:
            self.settings_window.update_state(
                mode=new_mode,
                wake_enabled=self.wake_detector.enabled,
                language=config.language,
                sensitivity=config.wake_sensitivity,
                voice_name=config.voice_name,
                respectful=config.respectful_address
            )
        print(f" Switched mode to: {new_mode.upper()}")

    def _handle_language_change(self, new_lang: str):
        if new_lang not in ["uz", "en", "tr"]:
            return
        config.language = new_lang
        config.save_persisted_settings()
        if self.client:
            self.client.set_language(new_lang)
        self.menu_bar.set_language(new_lang)
        if hasattr(self, "settings_window") and self.settings_window:
            self.settings_window.update_state(
                mode=self.client.active_mode,
                wake_enabled=self.wake_detector.enabled,
                language=new_lang,
                sensitivity=config.wake_sensitivity,
                voice_name=config.voice_name,
                respectful=config.respectful_address
            )
        lang_names = {"uz": "O'zbek tili", "en": "English", "tr": "Türkçe"}
        disp = lang_names.get(new_lang, new_lang)
        print(f"🌐 [Language Changed] Default language set to: {disp}", flush=True)

    def _handle_sensitivity_change(self, new_sens: str):
        if new_sens not in ["low", "medium", "high"]:
            return
        config.wake_sensitivity = new_sens
        config.save_persisted_settings()
        if hasattr(self, "wake_detector") and self.wake_detector:
            self.wake_detector.set_sensitivity(new_sens)
        self.menu_bar.set_sensitivity(new_sens)
        if hasattr(self, "settings_window") and self.settings_window:
            self.settings_window.update_state(
                mode=self.client.active_mode,
                wake_enabled=self.wake_detector.enabled,
                language=config.language,
                sensitivity=new_sens,
                voice_name=config.voice_name,
                respectful=config.respectful_address
            )
        sens_names = {"low": "Low (Media Safe)", "medium": "Medium", "high": "High"}
        disp = sens_names.get(new_sens, new_sens)
        print(f"🎚️ [Wake Sensitivity Changed] Set to: {disp}", flush=True)

    def _handle_voice_change(self, new_voice: str):
        if new_voice not in ["Aoede", "Charon"]:
            return
        config.voice_name = new_voice
        config.save_persisted_settings()
        if self.client:
            self.client.set_voice(new_voice)
        self.menu_bar.set_voice(new_voice)
        if hasattr(self, "settings_window") and self.settings_window:
            self.settings_window.update_state(
                mode=self.client.active_mode,
                wake_enabled=self.wake_detector.enabled,
                language=config.language,
                sensitivity=config.wake_sensitivity,
                voice_name=new_voice,
                respectful=config.respectful_address
            )
        print(f"🎙️ [Voice Model Changed] Selected: {new_voice}", flush=True)

    def _handle_accent_change(self, new_accent: str):
        # Deprecated: Accent feature removed in favor of natural native pronunciation
        pass

    def _handle_respectful_toggle(self):
        new_state = not config.respectful_address
        config.respectful_address = new_state
        config.save_persisted_settings()
        if self.client:
            self.client.set_respectful(new_state)
        self.menu_bar.set_respectful(new_state)
        if hasattr(self, "settings_window") and self.settings_window:
            self.settings_window.update_state(
                mode=self.client.active_mode,
                wake_enabled=self.wake_detector.enabled,
                language=config.language,
                sensitivity=config.wake_sensitivity,
                voice_name=config.voice_name,
                respectful=new_state
            )
        label = "Enabled ('sir' / 'Janob' / 'efendim')" if new_state else "Disabled (Direct / No titles)"
        print(f"🎩 [Respectful Address Toggled] {label}", flush=True)

    def _format_action_label(self, name: str, args: dict) -> str:
        args = args or {}
        if name == "open_app":
            app = args.get("app_name", "").strip()
            return f"Opening {app}..." if app else "Opening Application..."
        elif name in ["close_app", "quit_app"]:
            app = args.get("app_name", "").strip()
            if not app or app.lower() in ["current", "this", "this app", "this window", "window"]:
                return "Closing Window..."
            return f"Closing {app}..."
        elif name == "open_folder":
            f = args.get("folder_path", "").strip()
            return f"Opening {f.title()}..." if f else "Opening Folder..."
        elif name == "create_folder":
            f = args.get("folder_name", "").strip()
            return f"Creating Folder '{f}'..." if f else "Creating Folder..."
        elif name in ["rename_file_or_folder", "rename_folder"]:
            new_n = args.get("new_name", "").strip()
            return f"Renaming to '{new_n}'..." if new_n else "Renaming Item..."
        elif name in ["move_file_or_folder", "move_folder", "move_files"]:
            dest = args.get("destination", "").strip()
            return f"Moving to {dest.title()}..." if dest else "Moving Items..."
        elif name in ["delete_file_or_folder", "delete_folder", "delete_file", "remove_folder", "remove_file", "trash_folder", "trash_file"]:
            target = args.get("target", "").strip()
            return f"Moving '{target}' to Trash..." if target else "Moving to Trash..."
        elif name == "search_google":
            q = args.get("query", "").strip()
            if len(q) > 22:
                q = q[:20] + "..."
            return f"Searching '{q}'..." if q else "Searching Google..."
        elif name == "open_url":
            url = args.get("url", "").strip()
            clean = url.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
            return f"Opening {clean}..." if clean else "Opening Website..."
        elif name == "create_note":
            title = args.get("title", "").strip()
            return f"Writing Note '{title[:16]}'..." if title else "Writing Note..."
        elif name == "clipboard_action":
            action = args.get("action", "copy").lower()
            text = args.get("text", "") or ""
            if action in ["copy", "write"]:
                if any(w in text.lower() for w in ["prompt", "cinematic", "photorealistic", "portrait", "render", "illustration", "detailed", "lighting"]) or len(text) > 40:
                    return "Writing Prompt..."
                return "Copying to Clipboard..."
            return "Reading Clipboard..."
        elif name == "create_reminder":
            return "Creating Reminder..."
        elif name == "take_screenshot":
            return "Taking Screenshot..."
        elif name == "switch_mode":
            mode = args.get("target_mode", "Chat").strip().title()
            return f"Switching to {mode} Mode..."
        elif name in ["switch_language", "set_language", "change_language"]:
            t_lang = args.get("target_language", "English").strip().title()
            return f"Switching Language to {t_lang}..."
        elif name == "system_control":
            act = args.get("action", "").replace("_", " ").strip().title()
            return f"Adjusting {act}..."
        elif name == "get_current_time":
            return "Checking Local Time..."
        elif name in ["spotify_control", "play_music", "control_spotify"]:
            act = args.get("action", "play").lower()
            q = args.get("query", "").strip()
            if act in ["play", "resume", "start"]:
                if q:
                    clean_q = q[:20] + "..." if len(q) > 22 else q
                    return f"Playing '{clean_q}' on Spotify..."
                return "Playing Spotify..."
            elif act in ["pause", "stop"]:
                return "Pausing Spotify..."
            elif act in ["next", "skip"]:
                return "Skipping Track..."
            elif act in ["previous", "back"]:
                return "Previous Track..."
            elif act in ["now_playing", "current", "status"]:
                return "Checking Song..."
            elif act == "volume":
                return "Adjusting Volume..."
            return "Controlling Spotify..."
        elif name in ["switch_tab", "switch_browser_tab", "change_tab", "select_tab", "tab_control"]:
            idx = args.get("tab_index")
            name_val = args.get("tab_name", "")
            act = args.get("action", "switch")
            if name_val:
                return f"Switching to '{name_val}' Tab..."
            elif idx is not None:
                return f"Switching to Tab {idx}..."
            elif act == "new":
                return "Opening New Tab..."
            elif act == "close":
                return "Closing Tab..."
            return "Switching Tab..."
        elif name in ["switch_window", "cycle_windows", "change_window", "next_window", "switch_open_windows"]:
            app_n = args.get("app_name")
            if app_n:
                return f"Switching {app_n} Window..."
            return "Switching Window..."
        elif name in ["switch_desktop", "switch_space", "change_desktop", "change_space", "switch_workspace"]:
            idx = args.get("desktop_index")
            dir_val = (args.get("direction") or "").lower()
            act = (args.get("action") or "").lower()
            if idx:
                return f"Switching to Desktop {idx}..."
            elif dir_val in ["next", "right", "forward"]:
                return "Next Desktop..."
            elif dir_val in ["previous", "prev", "left", "back"]:
                return "Previous Desktop..."
            elif act in ["mission_control", "spaces", "overview"]:
                return "Mission Control..."
            elif act in ["show_desktop", "desktop_view"]:
                return "Showing Desktop..."
            return "Switching Desktop..."
        elif name in ["dismiss_assistant", "dismiss", "hide_assistant", "disappear", "close_assistant"]:
            return "Dismissing..."
        else:
            return f"{name.replace('_', ' ').title()}..."

    def _handle_tool_call(self, name: str, args: dict):
        if name in ["dismiss_assistant", "dismiss", "hide_assistant", "disappear", "close_assistant"]:
            print(f"💨 [Tool Call Dismiss] Assistant dismissed via tool: {name}", flush=True)
            self.dismiss()
            return
        action_label = self._format_action_label(name, args)
        self._active_action = action_label
        print(f"⚙️ [Action Display] {action_label}", flush=True)
        self.hud.set_state("speaking", "ACTION", action_label)
        self.menu_bar.set_status(f"Action: {action_label}")

    def _handle_tool_executed(self, name: str, args: dict, result: dict):
        if name in ["dismiss_assistant", "dismiss", "hide_assistant", "disappear", "close_assistant"]:
            self.dismiss()
            return
        action_label = self._format_action_label(name, args)
        self._active_action = action_label
        self.hud.set_state("speaking", "ACTION", action_label)
        self.menu_bar.set_status(f"Action: {action_label}")
        if name in ["spotify_control", "system_control"]:
            act = str((args or {}).get("action", "")).lower()
            if act in ["pause", "stop"]:
                self._media_explicitly_stopped = True

    # --- WAKE WORD FLOW ---
    def _on_wake_word_triggered(self, suffix: str = ""):
        print(f"🎙️ [WakeWord callback fired] running={self._running}, busy={self._busy}, recording={self.audio_manager.is_recording()}, suffix='{suffix}'", flush=True)
        if not self._running or self._busy or self.audio_manager.is_recording():
            return

        # Immediate dismissal from wake suffix ("Swan, disappear", "Hey Swan, yo'qol")
        clean_suffix = suffix.lower().strip()
        dismiss_tokens = ["disappear", "go away", "get lost", "vanish", "yo'qol", "yashirin", "ekrandan ket", "dam ol", "yo'q bo'l"]
        if any(tok == clean_suffix or clean_suffix.startswith(tok) for tok in dismiss_tokens):
            print(f"💨 [Wake Suffix Dismiss] Immediate dismissal from wake phrase suffix: '{clean_suffix}'", flush=True)
            self.dismiss()
            return

        self._busy = True
        self._cancel_requested = False
        self._interrupted = False
        self.wake_detector.enabled = False
        has_immediate_command = bool(suffix and len(suffix.strip().split()) >= 1 and suffix.strip() != "[unk]")
        if self._loop and self._loop.is_running():
            self._active_turn_future = asyncio.run_coroutine_threadsafe(
                self._handle_wake_cycle(has_immediate_command=has_immediate_command),
                self._loop
            )

    async def _handle_wake_cycle(self, has_immediate_command: bool = False):
        try:
            self._cancel_requested = False
            self._interrupted = False
            self._media_explicitly_stopped = False
            self._paused_media_on_wake = await asyncio.to_thread(self._pause_media_if_playing)
            self.menu_bar.set_status("Listening...")

            # Proactively ensure the Gemini Live session is fresh
            if self.client:
                asyncio.create_task(self.client.ensure_active_session())

            if has_immediate_command:
                # User spoke command together with wake word ("Swan, open Safari")!
                print(f"⚡ [Immediate Command Mode] Continuous command detected. Streaming immediately.", flush=True)
                self.hud.show(state="listening", status="LISTENING", subtitle="Listening...")
            else:
                # 1. Random voice prompt matching selected language, voice model and respectful preference
                pcm_np, label = audio_prompts.get_random_prompt(
                    language=config.language,
                    voice_name=config.voice_name,
                    respectful=config.respectful_address
                )
                self._active_prompt_label = label
                self._active_action = ""
                print(f"🎙️ [Wake Word Detected] Acknowledging with: '{label}'", flush=True)

                # 2. Show top liquid bar immediately
                self.hud.show(state="wake", status="SWAN", subtitle=label)

                # 3. Play voice acknowledgment (trimmed, crisp ~1.0s)
                if pcm_np is not None:
                    self.audio_manager.set_interruption_callback(None)
                    self.audio_manager.play_prompt(pcm_np)
                    while self.audio_manager.is_playing() and not self._cancel_requested:
                        await asyncio.sleep(0.02)
                    self.audio_manager.set_interruption_callback(self.wake_detector.process_interruption)

                if self._cancel_requested:
                    return

                # Clean 220ms decay buffer to prevent speaker hardware buffer/echo bleed into mic
                if not self._interrupted:
                    await asyncio.sleep(0.22)

            # 4. Multi-turn conversational loop (back-and-forth)
            conversation_active = True
            turn_number = 1
            last_reply = ""

            while conversation_active and self._running and not self._cancel_requested:
                was_interrupted = self._interrupted
                self._interrupted = False

                if was_interrupted:
                    # User interrupted Swan! Active listening with crisp 3.5s timeout
                    await asyncio.sleep(0.20)  # Let interruption utterance and echo clear
                    self.hud.set_state("listening", "LISTENING", "Listening...")
                    self.menu_bar.set_status("Listening...")
                    turn_timeout = 3.5
                elif turn_number > 1:
                    # Check if Gemini asked a clarifying question or ended with a question
                    is_question = "?" in last_reply or any(w in last_reply.lower() for w in ["what", "which", "how", "could you", "would you", "tell me", "please tell"])
                    if is_question:
                        self.hud.set_state("listening", "LISTENING", "Listening for reply...")
                        self.menu_bar.set_status("Listening for reply...")
                        turn_timeout = 6.5  # Ample time for user to think and answer Gemini's question
                    elif not last_reply:
                        self.hud.set_state("listening", "LISTENING", "Listening...")
                        self.menu_bar.set_status("Listening...")
                        turn_timeout = 5.0
                    else:
                        self.hud.set_state("listening", "LISTENING", "Listening for follow-up...")
                        self.menu_bar.set_status("Listening for follow-up...")
                        turn_timeout = 4.0
                else:
                    self.hud.set_state("listening", "LISTENING", "Listening...")
                    turn_timeout = 5.5

                # Record user speech with adaptive pause detection
                # Do NOT include preroll on interruption (to avoid capturing old playback or the word 'Stop')
                include_preroll = (has_immediate_command and turn_number == 1)
                pcm_bytes, live_speech = await self._listen_for_speech(
                    initial_timeout=turn_timeout,
                    include_preroll=include_preroll,
                    max_duration=12.0
                )

                if self._cancel_requested:
                    break

                if has_immediate_command and turn_number == 1:
                    has_command = self.audio_manager.has_speech(pcm_bytes, energy_threshold=0.015, min_speech_duration=0.25)
                else:
                    has_command = live_speech and len(pcm_bytes) >= 9600 and self.audio_manager.has_speech(
                        pcm_bytes, energy_threshold=0.016, min_speech_duration=0.28
                    )

                if has_command:
                    last_reply = await self._process_gemini_turn(pcm_bytes)
                    if self._cancel_requested:
                        break
                    turn_number += 1

                    # Wait for audio to finish playing
                    while self.audio_manager.is_playing() and not self._cancel_requested and not self._interrupted:
                        await asyncio.sleep(0.02)
                    if self._cancel_requested:
                        break
                    if not self._interrupted:
                        await asyncio.sleep(0.08) # Rapid 80ms decay

                    # Keep conversation loop alive for natural back-and-forth!
                else:
                    if was_interrupted:
                        print(f"🛑 [Interruption Closed] Swan stopped by user with no further command. Dismissing.", flush=True)
                    else:
                        print(f"⏱️ [Silence/Inactivity] No speech command detected (completed {turn_number - 1} turns). Dismissing.", flush=True)
                    conversation_active = False

            # Auto-hide HUD when conversation ends
            if not self._cancel_requested:
                self.hud.hide(delay=0.35)
                self.menu_bar.set_status("Ready (Listening for 'Hey Swan')")

        except asyncio.CancelledError:
            print("🛑 [Wake Cycle] Task cancelled cleanly.", flush=True)
        finally:
            self._resume_media_if_appropriate()
            self.wake_detector.reset()
            self.wake_detector.enabled = True
            self._busy = False

    async def _listen_for_speech(
        self,
        initial_timeout: float = 5.0,
        include_preroll: bool = False,
        max_duration: float = 12.0
    ) -> tuple[bytes, bool]:
        """
        Listens cleanly for user speech with real-time adaptive noise-floor calibration.
        Dynamically tracks background noise, room acoustics, or playing music, ensuring speech
        activity and natural pause boundaries are accurately distinguished from ambient sound.
        """
        self.audio_manager.start_recording(play_chime=False, include_preroll=include_preroll)
        start_time = time.time()
        speech_started = False
        speech_start_time = time.time()
        speech_frames = 0
        last_speech_time = time.time()

        # Dynamic ambient noise floor tracker
        ambient_floor = max(0.010, self.audio_manager.current_rms)
        calibrated_samples = []

        while time.time() - start_time < max_duration:
            if self._cancel_requested:
                print("🛑 [Listen Cancelled] User dismissed.", flush=True)
                break

            await asyncio.sleep(0.02)
            rms = self.audio_manager.current_rms

            # Continuously adapt ambient noise floor before speech starts or during silences
            if not speech_started:
                calibrated_samples.append(rms)
                if len(calibrated_samples) <= 8:
                    ambient_floor = min(calibrated_samples)
                else:
                    if rms < ambient_floor:
                        ambient_floor = 0.85 * ambient_floor + 0.15 * rms
                    elif rms < ambient_floor * 1.4:
                        ambient_floor = 0.96 * ambient_floor + 0.04 * rms

            # Adaptive dynamic thresholds relative to measured ambient floor
            speech_trigger = max(0.024, ambient_floor * 1.50 + 0.006)
            silence_threshold = max(0.018, ambient_floor * 1.20 + 0.003)

            if rms > speech_trigger:
                speech_frames += 1
                if speech_frames >= 3 and not speech_started:
                    speech_started = True
                    speech_start_time = time.time()
                    print(f"🎙️ [Speech Detected] User speaking... (rms: {rms:.3f}, ambient floor: {ambient_floor:.3f})", flush=True)
                if speech_started:
                    last_speech_time = time.time()
            elif rms > silence_threshold and speech_started:
                # Soft connecting speech or vowels above ambient noise
                last_speech_time = time.time()
            else:
                speech_frames = max(0, speech_frames - 1)
                if speech_started:
                    speech_len = last_speech_time - speech_start_time
                    if speech_len < 1.0:
                        effective_pause = 1.15 # Room for natural pauses after wake word
                    elif speech_len < 3.5:
                        effective_pause = 0.80 # Snappy responsive trigger
                    else:
                        effective_pause = 0.90
                    if time.time() - last_speech_time > effective_pause:
                        if speech_len < 0.35:
                            # False start / breath / click / mic tap - reset and keep waiting for real speech
                            speech_started = False
                            speech_frames = 0
                            continue
                        print(f"🎙️ [End of Speech] Natural pause detected ({effective_pause:.2f}s, speech len: {speech_len:.2f}s, ambient floor: {ambient_floor:.3f}).", flush=True)
                        break
                elif time.time() - start_time > initial_timeout:
                    # User said nothing
                    print(f"⏱️ [Inactivity] No speech started within {initial_timeout:.1f}s (ambient floor: {ambient_floor:.3f}).", flush=True)
                    break

        if time.time() - start_time >= max_duration and speech_started:
            print(f"⏱️ [Max Duration Limit] Finished recording after {max_duration:.1f}s cap.", flush=True)

        return self.audio_manager.stop_recording(play_chime=False), speech_started

    # --- PUSH-TO-TALK HOTKEY FLOW ---
    def _on_hotkey_press(self):
        print(f"⌨️ [Hotkey press] running={self._running}, busy={self._busy}", flush=True)
        if not self._running:
            return

        # If Swan is currently speaking or processing, interrupt immediately and take over!
        if self._busy:
            self._interrupted = True
            self.audio_manager.interrupt_playback()
            if self._active_turn_future and not self._active_turn_future.done():
                self._active_turn_future.cancel()
            self._busy = False

        self.wake_detector.enabled = False
        self._active_action = ""
        if config.respectful_address:
            self._active_prompt_label = "Eshtaman janob"
        else:
            self._active_prompt_label = "Eshtaman"
        self._hotkey_recording_start = time.time()
        self.audio_manager.start_recording()
        self.menu_bar.set_status("Tinglanmoqda (Hotkey)...")
        self.hud.show(state="listening", status="LISTENING", subtitle="Gapiring...")

    def _on_hotkey_release(self):
        print(f"⌨️ [Hotkey release] running={self._running}, busy={self._busy}", flush=True)
        if not self._running or self._busy:
            return
        duration = time.time() - self._hotkey_recording_start
        pcm = self.audio_manager.stop_recording()
        print(f"⌨️ [Hotkey release] duration={duration:.2f}s, pcm_len={len(pcm)}, has_speech={self.audio_manager.has_speech(pcm)}", flush=True)

        if duration < config.min_recording_seconds or len(pcm) < 3200 or not self.audio_manager.has_speech(pcm):
            self.hud.hide(delay=0.2)
            self.menu_bar.set_status("Ready (Listening for 'Hey Swan')")
            self.wake_detector.reset()
            self.wake_detector.enabled = True
            return

        self._busy = True
        self._cancel_requested = False
        if self._loop and self._loop.is_running():
            self._active_turn_future = asyncio.run_coroutine_threadsafe(self._handle_hotkey_turn(pcm), self._loop)

    async def _handle_hotkey_turn(self, pcm_bytes: bytes):
        try:
            self._interrupted = False
            reply = await self._process_gemini_turn(pcm_bytes)
            if self._cancel_requested or self._interrupted:
                return
            while self.audio_manager.is_playing() and not self._cancel_requested and not self._interrupted:
                await asyncio.sleep(0.02)
            if self._cancel_requested or self._interrupted:
                return
            await asyncio.sleep(0.32)

            # If Gemini asked a question, listen for the follow-up answer hands-free!
            is_question = reply and ("?" in reply or any(w in reply.lower() for w in ["what", "which", "how", "could you", "would you", "tell me", "please tell"]))
            if is_question and not self._cancel_requested and not self._interrupted:
                self.hud.set_state("listening", "LISTENING", "Listening for reply...")
                followup_pcm, live_speech = await self._listen_for_speech(initial_timeout=6.5, max_duration=12.0)
                if not self._cancel_requested and not self._interrupted and live_speech and followup_pcm and self.audio_manager.has_speech(followup_pcm, energy_threshold=0.013, min_speech_duration=0.18):
                    await self._process_gemini_turn(followup_pcm)
                    while self.audio_manager.is_playing() and not self._cancel_requested and not self._interrupted:
                        await asyncio.sleep(0.02)
                    await asyncio.sleep(0.08)

            if not self._cancel_requested and not self._interrupted:
                self.hud.hide(delay=0.4)
                self.menu_bar.set_status("Ready (Listening for 'Hey Swan')")

        except asyncio.CancelledError:
            print("🛑 [Hotkey Turn] Task cancelled cleanly.", flush=True)
        finally:
            self.wake_detector.reset()
            self.wake_detector.enabled = True
            self._busy = False


    # --- GEMINI TURN PROCESSING ---
    async def _process_gemini_turn(self, pcm_bytes: bytes) -> str:
        try:
            self._interrupted = False
            self.wake_detector.reset_interruption()
            self.hud.set_state("thinking", "THINKING", "Processing...")
            self.menu_bar.set_status("Thinking...")
            self._active_transcript = ""
            self._active_action = ""
            has_first_audio = False

            def on_audio_chunk(chunk: bytes):
                nonlocal has_first_audio
                if self._interrupted or self._cancel_requested:
                    return
                if not has_first_audio:
                    has_first_audio = True
                    # Only show the action if an action took place, otherwise show the acknowledgment label.
                    # Strictly do NOT show raw transcription text in the liquid pill HUD!
                    display_text = self._active_action if self._active_action else self._active_prompt_label
                    display_status = "ACTION" if self._active_action else "SWAN"
                    self.hud.set_state("speaking", display_status, display_text)
                self.audio_manager.play_audio_chunk(chunk)

            def on_transcript_chunk(text: str):
                self._active_transcript += text
                # We strictly do NOT put streaming transcription text into the liquid pill HUD!
                if not self._active_action and not self._interrupted:
                    self.menu_bar.set_status("Swan: Speaking...")

            def on_tool_call(name: str, args: dict):
                self._handle_tool_call(name, args)

            turn_task = asyncio.create_task(
                self.client.send_audio_turn(
                    pcm_bytes=pcm_bytes,
                    on_audio_chunk=on_audio_chunk,
                    on_transcript_chunk=on_transcript_chunk,
                    on_tool_call=on_tool_call
                )
            )
            self._current_client_turn_task = turn_task

            try:
                latency = await turn_task
                print(f"⚡ [Swan Response] Latency: {latency:.2f}s | Reply: {self._active_transcript}", flush=True)
                if self._active_transcript:
                    self._last_assistant_speech = self._active_transcript
                    try:
                        from memory_manager import memory_manager
                        asyncio.create_task(memory_manager.maybe_extract_and_remember(self._active_transcript, self._active_transcript))
                    except Exception:
                        pass
                elif self._active_action and not self._interrupted and not self._cancel_requested:
                    action_confirm = "Buyrug'ingiz bajarildi, Janob."
                    self._active_transcript = action_confirm
                    self._last_assistant_speech = action_confirm
                    print(f"ℹ️ [Auto Confirmation] Action was executed: {self._active_action}", flush=True)
            except asyncio.CancelledError:
                print("🛑 [Turn Task] Gemini turn streaming aborted by user interruption.", flush=True)
                if self._active_transcript:
                    self._last_assistant_speech = self._active_transcript
                if self.client:
                    self.client._needs_reconnect = True
                return ""
            finally:
                self._current_client_turn_task = None

            # Wait for spoken audio to finish playing
            while self.audio_manager.is_playing() and not self._cancel_requested and not self._interrupted:
                await asyncio.sleep(0.02)

            return self._active_transcript

        except Exception as e:
            print(f"❌ [ERROR] Turn execution error: {e}", flush=True)
            self.hud.set_state("thinking", "ERROR", str(e)[:30])
            if self.client:
                asyncio.create_task(self.client.ensure_active_session())
            await asyncio.sleep(1.5)
            return ""

    async def _keepalive_loop(self):
        """Sends periodic websocket pings to prevent idle timeout."""
        while self._running:
            await asyncio.sleep(20.0)
            if self.client and self._running and not self._busy:
                if self.client.is_healthy():
                    await self.client.ping()
                else:
                    try:
                        await self.client.connect()
                    except Exception:
                        pass

    async def shutdown(self):
        self._running = False
        if self._keepalive_task:
            self._keepalive_task.cancel()
        if self.hotkey_manager:
            self.hotkey_manager.stop()
        if self.audio_manager:
            self.audio_manager.close()
        if self.client:
            await self.client.disconnect()
        if self.hud:
            self.hud.hide(delay=0.0)

if __name__ == "__main__":
    if not acquire_single_instance_lock():
        print("❌ Another instance of Swan is already running! Exiting immediately.", flush=True)
        sys.exit(0)

    app = SwanApp()

    def _sig_handler(sig, frame):
        print(f"\n🛑 Received signal {sig}, shutting down cleanly...", flush=True)
        app._quit()

    try:
        signal.signal(signal.SIGINT, _sig_handler)
        signal.signal(signal.SIGTERM, _sig_handler)
    except Exception:
        pass

    try:
        app.start()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Exited: {e}", flush=True)
    finally:
        try:
            if _lock_fd:
                fcntl.flock(_lock_fd, fcntl.LOCK_UN)
                _lock_fd.close()
        except Exception:
            pass
        if os.path.exists(LOCK_FILE):
            try:
                os.remove(LOCK_FILE)
            except Exception:
                pass
