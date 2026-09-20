import json
import os
import threading
from typing import Optional

import objc
from Cocoa import (
    NSObject, NSWindow, NSBackingStoreBuffered, NSColor, NSRect, NSPoint, NSSize,
    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable, NSWindowStyleMaskResizable,
    NSWindowStyleMaskFullSizeContentView, NSFloatingWindowLevel,
    NSPasteboard, NSStringPboardType, NSScreen, NSURL, NSApp
)
from WebKit import WKWebView, WKWebViewConfiguration
from PyObjCTools import AppHelper


class ReportWindowDelegate(NSObject):
    def windowShouldClose_(self, sender):
        sender.orderOut_(None)
        return False


class ReportNavDelegate(NSObject):
    def init(self):
        self = objc.super(ReportNavDelegate, self).init()
        if self is None:
            return None
        self.on_close = None
        self.on_copy = None
        self.on_loaded = None
        return self

    def webView_didFinishNavigation_(self, webview, navigation):
        if hasattr(self, "on_loaded") and self.on_loaded:
            self.on_loaded()

    def webView_decidePolicyForNavigationAction_decisionHandler_(self, webview, action, handler):
        url = action.request().URL().absoluteString()
        if url.startswith("swan://"):
            command = url[7:]
            if command == "closeWindow":
                if hasattr(self, "on_close") and self.on_close:
                    self.on_close()
            elif command == "copyContent":
                if hasattr(self, "on_copy") and self.on_copy:
                    self.on_copy()
            handler(0)  # WKNavigationActionPolicyCancel
            return
        handler(1)  # WKNavigationActionPolicyAllow


class SwanReportWindow:
    """A transparent, movable, resizable, floating results/report window located

    on the left side of the screen that displays research findings, internet gather
    results, YouTube video summaries, and documents with single-click clipboard copying.
    """

    def __init__(self, template_path: Optional[str] = None):
        if template_path is None:
            from resource_helper import get_resource_path
            template_path = get_resource_path("report_template.html")
        self.template_path = template_path

        self.window = None
        self.webview = None
        self.delegate = None
        self.nav_delegate = None

        self._page_loaded = False
        self._pending_evals = []
        self._lock = threading.Lock()
        self._current_title = ""
        self._current_content = ""
        self._current_source = "Swan Agent"

        self._init_window()

    def _init_window(self):
        screen = NSScreen.mainScreen()
        if not screen and NSScreen.screens():
            screen = NSScreen.screens()[0]
        screen_frame = screen.frame() if screen else NSRect(NSPoint(0, 0), NSSize(1440, 900))

        # Position on the left side of the screen
        width = 520
        height = 660
        x = screen_frame.origin.x + 36
        y = screen_frame.origin.y + (screen_frame.size.height - height) / 2.0
        rect = NSRect(NSPoint(x, y), NSSize(width, height))

        style_mask = (
            NSWindowStyleMaskTitled |
            NSWindowStyleMaskClosable |
            NSWindowStyleMaskResizable |
            NSWindowStyleMaskFullSizeContentView
        )

        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style_mask, NSBackingStoreBuffered, False
        )
        self.window.setTitle_("Swan Intelligence Report")
        self.window.setTitlebarAppearsTransparent_(True)
        self.window.setTitleVisibility_(1)  # NSWindowTitleHidden
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(NSColor.clearColor())
        self.window.setMovableByWindowBackground_(True)
        self.window.setLevel_(NSFloatingWindowLevel)
        self.window.setMinSize_(NSSize(380, 300))

        self.delegate = ReportWindowDelegate.alloc().init()
        self.window.setDelegate_(self.delegate)

        # Hide native titlebar buttons so custom sleek macOS traffic-light control in HTML header works seamlessly
        for btn_id in [0, 1, 2]:
            btn = self.window.standardWindowButton_(btn_id)
            if btn:
                btn.setHidden_(True)

        config = WKWebViewConfiguration.alloc().init()
        self.webview = WKWebView.alloc().initWithFrame_configuration_(rect, config)
        self.webview.setAutoresizingMask_(18)  # NSViewWidthSizable | NSViewHeightSizable
        self.webview.setValue_forKey_(False, "drawsBackground")
        if hasattr(self.webview, "setUnderPageBackgroundColor_"):
            self.webview.setUnderPageBackgroundColor_(NSColor.clearColor())

        self.nav_delegate = ReportNavDelegate.alloc().init()
        self.nav_delegate.on_close = self.hide
        self.nav_delegate.on_copy = self._copy_to_pasteboard
        self.nav_delegate.on_loaded = self._on_web_loaded
        self.webview.setNavigationDelegate_(self.nav_delegate)

        self.window.setContentView_(self.webview)

        if os.path.exists(self.template_path):
            file_url = NSURL.fileURLWithPath_(self.template_path)
            self.webview.loadFileURL_allowingReadAccessToURL_(file_url, file_url)
        else:
            print(f"⚠️ [ReportWindow] Template file not found: {self.template_path}", flush=True)

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

    def _copy_to_pasteboard(self):
        paste_text = f"# {self._current_title}\n\n{self._current_content}"
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(paste_text, NSStringPboardType)
        print("📋 [ReportWindow] Content copied to macOS clipboard.", flush=True)

    def show_report(self, title: str, content: str, source: str = "Research Agent"):
        """Displays the report window on the left side of the screen with rendered markdown."""
        self._current_title = title or "Intelligence Report"
        self._current_content = content or ""
        self._current_source = source or "Swan Agent"

        def _main_show():
            clean_title = json.dumps(self._current_title)
            clean_content = json.dumps(self._current_content)
            clean_source = json.dumps(self._current_source)
            js = f"window.setReport({clean_title}, {clean_content}, {clean_source});"
            self._eval_js(js)
            self.window.makeKeyAndOrderFront_(None)

        AppHelper.callAfter(_main_show)

    def hide(self):
        def _main_hide():
            if self.window:
                self.window.orderOut_(None)
        AppHelper.callAfter(_main_hide)


# Global singleton instance
report_window: Optional[SwanReportWindow] = None

def get_report_window() -> SwanReportWindow:
    global report_window
    if report_window is None:
        report_window = SwanReportWindow()
    return report_window
