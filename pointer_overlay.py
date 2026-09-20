import json
import os
import threading
import time
from typing import Optional

import objc
from Cocoa import (
    NSApplication, NSPanel, NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSBackingStoreBuffered, NSColor, NSScreen, NSRect, NSPoint, NSSize,
    NSStatusWindowLevel, NSPopUpMenuWindowLevel,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSURL, NSObject, NSEvent, NSPointInRect
)
from WebKit import WKWebView, WKWebViewConfiguration
from PyObjCTools import AppHelper


class PointerNavDelegate(NSObject):
    def init(self):
        self = objc.super(PointerNavDelegate, self).init()
        if self is None:
            return None
        self.on_loaded = None
        return self

    def webView_didFinishNavigation_(self, webview, navigation):
        if hasattr(self, "on_loaded") and self.on_loaded:
            self.on_loaded()


class SwanPointerOverlay:
    """Independent cyber-hand cursor overlay that emerges from the screen's top bezel

    to point at target coordinates, buttons, code errors, or regions on the user's display,
    pulsing with sonar rings, and then retracts back into the top bezel.
    Never intercepts or blocks mouse clicks (ignoresMouseEvents = True).
    """

    def __init__(self, template_path: Optional[str] = None):
        if template_path is None:
            from resource_helper import get_resource_path
            template_path = get_resource_path("pointer_template.html")
        self.template_path = template_path

        self.panel = None
        self.webview = None
        self.nav_delegate = None
        self._page_loaded = False
        self._pending_evals = []
        self._lock = threading.Lock()

        self._init_window()

    def _get_target_screen_frame(self) -> NSRect:
        screen = NSScreen.mainScreen()
        if not screen and NSScreen.screens():
            screen = NSScreen.screens()[0]
        return screen.frame() if screen else NSRect(NSPoint(0, 0), NSSize(1440, 900))

    def _init_window(self):
        screen_frame = self._get_target_screen_frame()

        style_mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            screen_frame,
            style_mask,
            NSBackingStoreBuffered,
            False
        )

        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(False)
        self.panel.setIgnoresMouseEvents_(True)
        self.panel.setLevel_(NSPopUpMenuWindowLevel)

        collection_behavior = (
            NSWindowCollectionBehaviorCanJoinAllSpaces |
            NSWindowCollectionBehaviorStationary |
            NSWindowCollectionBehaviorIgnoresCycle |
            NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        self.panel.setCollectionBehavior_(collection_behavior)

        # WebKit Transparent View
        config = WKWebViewConfiguration.alloc().init()
        self.webview = WKWebView.alloc().initWithFrame_configuration_(screen_frame, config)
        self.webview.setValue_forKey_(False, "drawsBackground")
        if hasattr(self.webview, "setUnderPageBackgroundColor_"):
            self.webview.setUnderPageBackgroundColor_(NSColor.clearColor())

        self.nav_delegate = PointerNavDelegate.alloc().init()
        self.nav_delegate.on_loaded = self._on_web_loaded
        self.webview.setNavigationDelegate_(self.nav_delegate)

        self.panel.setContentView_(self.webview)

        # Load pointer template HTML
        if os.path.exists(self.template_path):
            file_url = NSURL.fileURLWithPath_(self.template_path)
            self.webview.loadFileURL_allowingReadAccessToURL_(file_url, file_url)
        else:
            print(f"⚠️ [PointerOverlay] Template file not found: {self.template_path}", flush=True)

        self.panel.orderFrontRegardless()

    def _on_web_loaded(self):
        self._page_loaded = True
        with self._lock:
            for script in self._pending_evals:
                self._eval_js(script)
            self._pending_evals.clear()

    def _eval_js(self, script: str):
        if not self._page_loaded:
            with self._lock:
                self._pending_evals.append(script)
            return
        if self.webview:
            self.webview.evaluateJavaScript_completionHandler_(script, None)

    def point_at(self, x: int, y: int, duration: float = 3.8, action: str = "point", label: str = ""):
        """Slides the custom cyber-hand cursor from the top notch down to (x, y) on screen.

        Args:
            x: Screen X in pixels (0 is left).
            y: Screen Y in pixels (0 is top).
            duration: Seconds to hold pointer before retracting (default: 3.8s).
            action: 'point', 'tap', or 'circle'.
            label: Optional text badge displayed next to pointer.
        """
        def _main_point():
            screen_frame = self._get_target_screen_frame()
            self.panel.setFrame_display_(screen_frame, True)
            self.panel.orderFrontRegardless()

            clean_label = json.dumps(label or "")
            clean_action = json.dumps(action or "point")
            js = f"window.pointAt({int(x)}, {int(y)}, {float(duration)}, {clean_action}, {clean_label});"
            self._eval_js(js)

        AppHelper.callAfter(_main_point)

    def point_at_percent(self, px: float, py: float, duration: float = 3.8, action: str = "point", label: str = ""):
        """Points at relative percentage of the screen (0.0 to 1.0).

        e.g. px=0.5, py=0.5 points dead-center.
        """
        screen_frame = self._get_target_screen_frame()
        w = screen_frame.size.width
        h = screen_frame.size.height
        x = int(px * w)
        y = int(py * h)
        self.point_at(x, y, duration=duration, action=action, label=label)

    def retract(self):
        """Immediately commands the hand to slide back up into the top bezel notch."""
        def _main_retract():
            self._eval_js("window.retract();")
        AppHelper.callAfter(_main_retract)


# Global singleton instance
pointer_overlay: Optional[SwanPointerOverlay] = None

def get_pointer_overlay() -> SwanPointerOverlay:
    global pointer_overlay
    if pointer_overlay is None:
        pointer_overlay = SwanPointerOverlay()
    return pointer_overlay
