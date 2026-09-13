import json
import os
import threading
import time
from typing import Optional

import objc
from Cocoa import (
    NSApplication, NSPanel, NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSBackingStoreBuffered, NSColor, NSScreen, NSRect, NSPoint, NSSize,
    NSFloatingWindowLevel, NSStatusWindowLevel, NSScreenSaverWindowLevel,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSURL, NSObject, NSEvent, NSPointInRect
)
from WebKit import WKWebView, WKWebViewConfiguration
from PyObjCTools import AppHelper

class HUDNavDelegate(NSObject):
    def init(self):
        self = objc.super(HUDNavDelegate, self).init()
        if self is None:
            return None
        self.on_loaded = None
        self.on_screen_changed = None
        return self

    def webView_didFinishNavigation_(self, webview, navigation):
        if hasattr(self, "on_loaded") and self.on_loaded:
            self.on_loaded()

    def screenDidChange_(self, notification):
        if hasattr(self, "on_screen_changed") and self.on_screen_changed:
            self.on_screen_changed()

class LiquidHUDWindow:
    def __init__(self, template_path: Optional[str] = None):
        if template_path is None:
            from resource_helper import get_resource_path
            template_path = get_resource_path("hud_template.html")
        self.template_path = template_path

        self.panel = None
        self.webview = None
        self.nav_delegate = None
        self._is_visible = True
        self.current_state = "idle"
        self._hide_timer = None
        self._lock = threading.Lock()

        self._page_loaded = False
        self._pending_evals = []
        self._show_token = 0

        # Initialize window on main Cocoa thread
        self._init_window()

        # Register for display resolution/monitor changes
        from Cocoa import NSNotificationCenter, NSApplicationDidChangeScreenParametersNotification
        self.nav_delegate.on_screen_changed = self._on_screen_changed
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self.nav_delegate,
            objc.selector(self.nav_delegate.screenDidChange_, signature=b"v@:@"),
            NSApplicationDidChangeScreenParametersNotification,
            None
        )

    def _on_screen_changed(self):
        AppHelper.callAfter(self._main_update_screen)

    def _main_update_screen(self):
        self._update_frame_for_current_screen()
        if self.panel:
            self.panel.setFrame_display_(self._on_screen_frame, True)
            self.panel.orderFrontRegardless()

    def _update_frame_for_current_screen(self):
        mouse_loc = NSEvent.mouseLocation()
        target_screen = None
        for s in NSScreen.screens():
            if NSPointInRect(mouse_loc, s.frame()):
                target_screen = s
                break
        if not target_screen:
            target_screen = NSScreen.mainScreen() or (NSScreen.screens()[0] if NSScreen.screens() else None)
        screen_frame = target_screen.frame() if target_screen else NSRect(NSPoint(0, 0), NSSize(1440, 900))
        win_w = 460
        win_h = 88
        x = screen_frame.origin.x + (screen_frame.size.width - win_w) / 2.0
        y = screen_frame.origin.y + screen_frame.size.height - win_h - 22.0
        self._on_screen_frame = NSRect(NSPoint(x, y), NSSize(win_w, win_h))

    def _init_window(self):
        win_w = 460
        win_h = 88
        self._update_frame_for_current_screen()

        # Borderless non-activating panel
        style_mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            self._on_screen_frame, style_mask, NSBackingStoreBuffered, False
        )

        # ScreenSaver window level guarantees floating cleanly above ALL apps, full-screen windows and menu bars
        self.panel.setLevel_(NSScreenSaverWindowLevel)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(False)
        self.panel.setIgnoresMouseEvents_(True) # Clicks pass through
        self.panel.setAcceptsMouseMovedEvents_(False)
        self.panel.setHidesOnDeactivate_(False)

        # Float across all virtual spaces, full-screen spaces, and Mission Control
        behavior = (
            NSWindowCollectionBehaviorCanJoinAllSpaces |
            NSWindowCollectionBehaviorStationary |
            NSWindowCollectionBehaviorIgnoresCycle |
            NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        self.panel.setCollectionBehavior_(behavior)

        # Configure transparent WebKit view
        config = WKWebViewConfiguration.alloc().init()
        self.webview = WKWebView.alloc().initWithFrame_configuration_(NSRect(NSPoint(0, 0), NSSize(win_w, win_h)), config)
        self.webview.setValue_forKey_(False, "drawsBackground")
        if hasattr(self.webview, "setUnderPageBackgroundColor_"):
            self.webview.setUnderPageBackgroundColor_(NSColor.clearColor())

        self.nav_delegate = HUDNavDelegate.alloc().init()
        self.nav_delegate.on_loaded = self._on_page_loaded
        self.webview.setNavigationDelegate_(self.nav_delegate)

        # Robust template resolution
        resolved_path = self.template_path
        if not resolved_path or not os.path.exists(resolved_path):
            from resource_helper import get_resource_path
            resolved_path = get_resource_path("hud_template.html")

        try:
            with open(resolved_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            base_dir_url = NSURL.fileURLWithPath_(os.path.dirname(resolved_path))
            self.webview.loadHTMLString_baseURL_(html_content, base_dir_url)
        except Exception as e:
            print(f"[ERROR] Loading HUD template string from {resolved_path}: {e}")

        self.panel.setContentView_(self.webview)
        # Always visible: order front immediately
        self.panel.orderFrontRegardless()

    def _on_page_loaded(self):
        self._page_loaded = True
        self.panel.orderFrontRegardless()
        self._eval_js('window.showHUD("idle", "SWAN", "Ready");')
        for code in self._pending_evals:
            if self.webview:
                self.webview.evaluateJavaScript_completionHandler_(code, None)
        self._pending_evals.clear()

    def _eval_js(self, js_code: str):
        try:
            if not self._page_loaded:
                self._pending_evals.append(js_code)
            if self.webview:
                self.webview.evaluateJavaScript_completionHandler_(js_code, None)
        except Exception:
            pass

    def show(self, state: str = "wake", status: str = "SWAN", subtitle: str = "Listening"):
        self._show_token += 1
        self.current_state = state or "wake"
        AppHelper.callAfter(self._main_show, self._show_token, state, status, subtitle)

    def _main_show(self, token: int, state: str, status: str, subtitle: str):
        with self._lock:
            self._is_visible = True
            self.current_state = state or "wake"

        try:
            # Dynamically place on current focused screen and show on top of all windows
            self._update_frame_for_current_screen()
            self.panel.setFrame_display_(self._on_screen_frame, True)
            self.panel.orderFrontRegardless()
            state_json = json.dumps(state or "wake")
            st_json = json.dumps(status or "SWAN")
            sub_json = json.dumps(subtitle or "")
            self._eval_js(f"window.showHUD({state_json}, {st_json}, {sub_json});")
        except Exception:
            pass

    def hide(self, delay: float = 0.0):
        # Liquid pill is ALWAYS visible: when hide() is requested, smoothly return to resting idle state.
        self._show_token += 1
        token = self._show_token
        if delay <= 0:
            AppHelper.callAfter(self._main_do_idle, token)
        else:
            AppHelper.callLater(delay, self._main_do_idle, token)

    def _main_do_idle(self, token: int):
        with self._lock:
            if token != self._show_token:
                # Stale request from an earlier cycle; ignore!
                return
            self.current_state = "idle"
            self._is_visible = True
        try:
            self.panel.orderFrontRegardless()
            self._eval_js('window.setState("idle", "SWAN", "Ready");')
        except Exception:
            pass

    def order_out(self):
        """Only called on app termination to dismiss window."""
        with self._lock:
            self._is_visible = False
        if self.panel:
            self.panel.orderOut_(None)

    def set_state(self, state: str, status: Optional[str] = None, subtitle: Optional[str] = None):
        self.current_state = state or "idle"
        AppHelper.callAfter(self._main_set_state, state, status, subtitle)

    def _main_set_state(self, state: str, status: Optional[str], subtitle: Optional[str]):
        with self._lock:
            self.current_state = state or "idle"
            self._is_visible = True
        try:
            self.panel.orderFrontRegardless()
            state_json = json.dumps(state or "idle")
            st_arg = json.dumps(status if status is not None else ("SWAN" if state == "idle" else "SWAN"))
            sub_arg = json.dumps(subtitle if subtitle is not None else ("Ready" if state == "idle" else ""))
            self._eval_js(f"window.setState({state_json}, {st_arg}, {sub_arg});")
        except Exception:
            pass

    def set_audio_energy(self, energy: float):
        AppHelper.callAfter(self._main_set_audio_energy, energy)

    def _main_set_audio_energy(self, energy: float):
        try:
            clamped = max(0.0, min(1.0, float(energy)))
            self._eval_js(f"window.setAudioEnergy({clamped});")
        except Exception:
            pass
