import json
import os
import threading
import time
from typing import Optional

import objc
from Cocoa import (
    NSApplication, NSPanel, NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSBackingStoreBuffered, NSColor, NSScreen, NSRect, NSPoint, NSSize,
    NSScreenSaverWindowLevel,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSURL, NSObject, NSEvent, NSPointInRect
)
from WebKit import WKWebView, WKWebViewConfiguration
from PyObjCTools import AppHelper

class AgentHUDNavDelegate(NSObject):
    def init(self):
        self = objc.super(AgentHUDNavDelegate, self).init()
        if self is None:
            return None
        self.on_loaded = None
        self.on_stop = None
        return self

    def webView_didFinishNavigation_(self, webview, navigation):
        if hasattr(self, "on_loaded") and self.on_loaded:
            self.on_loaded()

    def webView_decidePolicyForNavigationAction_decisionHandler_(self, webview, action, handler):
        url = action.request().URL().absoluteString()
        if url.startswith("swan://"):
            command = url[7:]
            if command == "stopAgent":
                if hasattr(self, "on_stop") and self.on_stop:
                    self.on_stop()
            handler(0)  # WKNavigationActionPolicyCancel
            return
        handler(1)  # WKNavigationActionPolicyAllow

class AgentHUDWindow:
    """Floating top-right corner status indicator for active background agents."""
    def __init__(self, template_path: Optional[str] = None):
        if template_path is None:
            from resource_helper import get_resource_path
            template_path = get_resource_path("agent_hud_template.html")
        self.template_path = template_path

        self.panel = None
        self.webview = None
        self.nav_delegate = None
        self._is_visible = False
        self._hide_timer = None
        self._lock = threading.Lock()

        self._page_loaded = False
        self._pending_evals = []

        self._init_window()

    def _on_stop_clicked(self):
        print("🛑 [AgentHUDWindow] User clicked manual Stop button on Agent HUD pill.", flush=True)
        try:
            from agent_manager import get_agent_manager
            get_agent_manager().cancel_all_agents()
        except Exception as e:
            print(f"⚠️ [AgentHUDWindow] Error stopping agents: {e}", flush=True)

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
        win_w = 260
        win_h = 64
        # Position at top-right corner, nicely spaced below macOS menu bar
        x = screen_frame.origin.x + screen_frame.size.width - win_w - 16.0
        y = screen_frame.origin.y + screen_frame.size.height - win_h - 26.0
        self._on_screen_frame = NSRect(NSPoint(x, y), NSSize(win_w, win_h))

    def _init_window(self):
        win_w = 260
        win_h = 64
        self._update_frame_for_current_screen()

        style_mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            self._on_screen_frame, style_mask, NSBackingStoreBuffered, False
        )

        self.panel.setLevel_(NSScreenSaverWindowLevel)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(False)
        self.panel.setIgnoresMouseEvents_(True) # Default ignored until shown
        self.panel.setAcceptsMouseMovedEvents_(False)
        self.panel.setHidesOnDeactivate_(False)

        behavior = (
            NSWindowCollectionBehaviorCanJoinAllSpaces |
            NSWindowCollectionBehaviorStationary |
            NSWindowCollectionBehaviorIgnoresCycle |
            NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        self.panel.setCollectionBehavior_(behavior)

        config = WKWebViewConfiguration.alloc().init()
        self.webview = WKWebView.alloc().initWithFrame_configuration_(NSRect(NSPoint(0, 0), NSSize(win_w, win_h)), config)
        self.webview.setValue_forKey_(False, "drawsBackground")
        if hasattr(self.webview, "setUnderPageBackgroundColor_"):
            self.webview.setUnderPageBackgroundColor_(NSColor.clearColor())

        self.nav_delegate = AgentHUDNavDelegate.alloc().init()
        self.nav_delegate.on_loaded = self._on_page_loaded
        self.nav_delegate.on_stop = self._on_stop_clicked
        self.webview.setNavigationDelegate_(self.nav_delegate)

        resolved_path = self.template_path
        if not resolved_path or not os.path.exists(resolved_path):
            from resource_helper import get_resource_path
            resolved_path = get_resource_path("agent_hud_template.html")

        try:
            with open(resolved_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            base_dir_url = NSURL.fileURLWithPath_(os.path.dirname(resolved_path))
            self.webview.loadHTMLString_baseURL_(html_content, base_dir_url)
        except Exception as e:
            print(f"⚠️ [AgentHUDWindow] Failed to load HTML template: {e}", flush=True)

        self.panel.setContentView_(self.webview)

    def _on_page_loaded(self):
        with self._lock:
            self._page_loaded = True
            for js in self._pending_evals:
                self.webview.evaluateJavaScript_completionHandler_(js, None)
            self._pending_evals.clear()

    def _eval_js(self, js: str):
        with self._lock:
            if self._page_loaded and self.webview:
                self.webview.evaluateJavaScript_completionHandler_(js, None)
            else:
                self._pending_evals.append(js)

    def show_working(self, title: str = "Agent is working...", subtitle: str = ""):
        """Call to display the top-right working indicator."""
        AppHelper.callAfter(self._main_show_working, title, subtitle)

    def _main_show_working(self, title: str, subtitle: str):
        with self._lock:
            if self._hide_timer:
                self._hide_timer.cancel()
                self._hide_timer = None

        self._update_frame_for_current_screen()
        self.panel.setFrame_display_(self._on_screen_frame, True)
        self.panel.setIgnoresMouseEvents_(False)

        js = f"showWorking({json.dumps(title)}, {json.dumps(subtitle)});"
        self._eval_js(js)

        if not self._is_visible:
            self.panel.orderFrontRegardless()
            self._is_visible = True

    def show_completed(self, title: str = "Agent finished ✅", subtitle: str = "", auto_hide_seconds: float = 4.0):
        """Transitions to completed status and automatically hides after auto_hide_seconds."""
        AppHelper.callAfter(self._main_show_completed, title, subtitle, auto_hide_seconds)

    def _main_show_completed(self, title: str, subtitle: str, auto_hide_seconds: float):
        self.panel.setIgnoresMouseEvents_(False)
        js = f"showCompleted({json.dumps(title)}, {json.dumps(subtitle)});"
        self._eval_js(js)

        with self._lock:
            if self._hide_timer:
                self._hide_timer.cancel()
            if auto_hide_seconds > 0:
                self._hide_timer = threading.Timer(auto_hide_seconds, self.hide)
                self._hide_timer.daemon = True
                self._hide_timer.start()

    def hide(self):
        """Hides the top-right HUD with smooth animation."""
        AppHelper.callAfter(self._main_hide)

    def _main_hide(self):
        with self._lock:
            if self._hide_timer:
                self._hide_timer.cancel()
                self._hide_timer = None
        self.panel.setIgnoresMouseEvents_(True)
        self._eval_js("hide();")
        def _order_out():
            time.sleep(0.35)
            AppHelper.callAfter(self.panel.orderOut_, None)
            self._is_visible = False
        threading.Thread(target=_order_out, daemon=True).start()

_agent_hud_instance = None

def get_agent_hud() -> Optional[AgentHUDWindow]:
    global _agent_hud_instance
    return _agent_hud_instance

def init_agent_hud(template_path: Optional[str] = None) -> AgentHUDWindow:
    global _agent_hud_instance
    if _agent_hud_instance is None:
        _agent_hud_instance = AgentHUDWindow(template_path)
    return _agent_hud_instance
