import os
import json
import threading
from typing import Optional, Callable

import objc
from Cocoa import (
    NSObject, NSWindow, NSBackingStoreBuffered, NSColor, NSRect, NSPoint, NSSize,
    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable, NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskFullSizeContentView, NSURL, NSApp
)
from WebKit import WKWebView, WKWebViewConfiguration
from PyObjCTools import AppHelper

class SettingsWindowDelegate(NSObject):
    def windowShouldClose_(self, sender):
        sender.orderOut_(None)
        return False

class SettingsNavDelegate(NSObject):
    def init(self):
        self = objc.super(SettingsNavDelegate, self).init()
        if self is None:
            return None
        self.on_close = None
        self.on_mode_toggle = None
        self.on_mode_change = None
        self.on_wake_toggle = None
        self.on_language_change = None
        self.on_sensitivity_change = None
        self.on_voice_change = None
        self.on_respectful_toggle = None
        self.on_quit = None
        return self

    def webView_decidePolicyForNavigationAction_decisionHandler_(self, webview, action, handler):
        url = action.request().URL().absoluteString()
        if url.startswith("swan://"):
            command = url[7:] # strip "swan://"
            if command == "closeWindow":
                if hasattr(self, "on_close") and self.on_close:
                    self.on_close()
            elif command.startswith("setLanguage/"):
                lang = command.split("/")[1]
                if hasattr(self, "on_language_change") and self.on_language_change:
                    self.on_language_change(lang)
            elif command.startswith("setSensitivity/"):
                sens = command.split("/")[1]
                if hasattr(self, "on_sensitivity_change") and self.on_sensitivity_change:
                    self.on_sensitivity_change(sens)
            elif command.startswith("setVoice/"):
                voice = command.split("/")[1]
                if hasattr(self, "on_voice_change") and self.on_voice_change:
                    self.on_voice_change(voice)
            elif command == "toggleRespectful":
                if hasattr(self, "on_respectful_toggle") and self.on_respectful_toggle:
                    self.on_respectful_toggle()
            elif command.startswith("setMode/"):
                mode = command.split("/")[1]
                if hasattr(self, "on_mode_change") and self.on_mode_change:
                    self.on_mode_change(mode)
            elif command == "toggleMode":
                if hasattr(self, "on_mode_toggle") and self.on_mode_toggle:
                    self.on_mode_toggle()
            elif command == "toggleWakeWord":
                if hasattr(self, "on_wake_toggle") and self.on_wake_toggle:
                    self.on_wake_toggle()
            elif command == "quitApp":
                if hasattr(self, "on_quit") and self.on_quit:
                    self.on_quit()
            elif command == "clearMemory":
                try:
                    from memory_manager import memory_manager
                    memory_manager.clear_memory()
                    if hasattr(self, "on_memory_cleared") and self.on_memory_cleared:
                        self.on_memory_cleared()
                except Exception as e:
                    print(f"Error clearing memory: {e}", flush=True)
            handler(0) # WKNavigationActionPolicyCancel
            return
        handler(1) # WKNavigationActionPolicyAllow

class SettingsWindow:
    def __init__(
        self,
        on_mode_toggle: Optional[Callable[[], None]] = None,
        on_mode_change: Optional[Callable[[str], None]] = None,
        on_wake_toggle: Optional[Callable[[], None]] = None,
        on_language_change: Optional[Callable[[str], None]] = None,
        on_sensitivity_change: Optional[Callable[[str], None]] = None,
        on_voice_change: Optional[Callable[[str], None]] = None,
        on_respectful_toggle: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None
    ):
        self.on_mode_toggle = on_mode_toggle
        self.on_mode_change = on_mode_change
        self.on_wake_toggle = on_wake_toggle
        self.on_language_change = on_language_change
        self.on_sensitivity_change = on_sensitivity_change
        self.on_voice_change = on_voice_change
        self.on_respectful_toggle = on_respectful_toggle
        self.on_quit = on_quit

        self.window = None
        self.webview = None
        self.delegate = None
        self.nav_delegate = None

        from resource_helper import get_resource_path
        self._template_path = get_resource_path("settings_template.html")
        self._current_mode = "command"
        self._current_wake = True
        self._current_lang = "uz"
        self._current_sens = "medium"
        self._current_voice = "Aoede"
        self._current_respectful = True

        self._init_window()

    def _init_window(self):
        width = 720
        height = 540
        rect = NSRect(NSPoint(0, 0), NSSize(width, height))
        
        style_mask = (
            NSWindowStyleMaskTitled |
            NSWindowStyleMaskClosable |
            NSWindowStyleMaskMiniaturizable |
            NSWindowStyleMaskFullSizeContentView
        )
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style_mask, NSBackingStoreBuffered, False
        )
        self.window.setTitle_("Swan Settings & Preferences")
        self.window.setTitlebarAppearsTransparent_(True)
        self.window.setTitleVisibility_(1)
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(NSColor.clearColor())
        self.window.setMovableByWindowBackground_(True)
        self.window.setLevel_(3)

        self.delegate = SettingsWindowDelegate.alloc().init()
        self.window.setDelegate_(self.delegate)

        config = WKWebViewConfiguration.alloc().init()
        self.webview = WKWebView.alloc().initWithFrame_configuration_(rect, config)
        self.webview.setValue_forKey_(False, "drawsBackground")
        if hasattr(self.webview, "setUnderPageBackgroundColor_"):
            self.webview.setUnderPageBackgroundColor_(NSColor.clearColor())

        self.nav_delegate = SettingsNavDelegate.alloc().init()
        self.nav_delegate.on_close = self.hide
        self.nav_delegate.on_mode_toggle = self.on_mode_toggle
        self.nav_delegate.on_mode_change = self.on_mode_change
        self.nav_delegate.on_wake_toggle = self.on_wake_toggle
        self.nav_delegate.on_language_change = self.on_language_change
        self.nav_delegate.on_sensitivity_change = self.on_sensitivity_change
        self.nav_delegate.on_voice_change = self.on_voice_change
        self.nav_delegate.on_respectful_toggle = self.on_respectful_toggle
        self.nav_delegate.on_quit = self.on_quit
        self.webview.setNavigationDelegate_(self.nav_delegate)

        file_url = NSURL.fileURLWithPath_(self._template_path)
        base_dir_url = NSURL.fileURLWithPath_(os.path.dirname(self._template_path))
        self.webview.loadFileURL_allowingReadAccessToURL_(file_url, base_dir_url)

        self.window.setContentView_(self.webview)

    def show(self):
        AppHelper.callAfter(self._main_show)

    def _main_show(self):
        if self.window:
            NSApp.activateIgnoringOtherApps_(True)
            self.window.center()
            self.window.makeKeyAndOrderFront_(None)
            self._main_update_state(
                self._current_mode, self._current_wake, self._current_lang,
                self._current_sens, self._current_voice, self._current_respectful
            )

    def hide(self):
        AppHelper.callAfter(self._main_hide)

    def _main_hide(self):
        if self.window:
            self.window.orderOut_(None)

    def update_state(
        self, mode: str, wake_enabled: bool, language: str = None,
        sensitivity: str = None, voice_name: str = None, respectful: bool = None
    ):
        self._current_mode = mode
        self._current_wake = wake_enabled
        if language:
            self._current_lang = language
        if sensitivity:
            self._current_sens = sensitivity
        if voice_name:
            self._current_voice = voice_name
        if respectful is not None:
            self._current_respectful = respectful
        AppHelper.callAfter(
            self._main_update_state, self._current_mode, self._current_wake,
            self._current_lang, self._current_sens, self._current_voice, self._current_respectful
        )

    def _main_update_state(
        self, mode: str, wake_enabled: bool, language: str,
        sensitivity: str, voice_name: str, respectful: bool
    ):
        if self.webview:
            wake_bool = "true" if wake_enabled else "false"
            resp_bool = "true" if respectful else "false"
            facts_json = "[]"
            try:
                from memory_manager import memory_manager
                facts_json = json.dumps(memory_manager.get_learned_facts())
            except Exception:
                pass
            js = (
                f"if (window.updateSettingsState) updateSettingsState("
                f"'{mode}', {wake_bool}, '{language}', '{sensitivity}', '{voice_name}', {resp_bool}, {facts_json});"
            )
            self.webview.evaluateJavaScript_completionHandler_(js, None)
