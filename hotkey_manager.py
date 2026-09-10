import threading
import time
from typing import Callable, Optional
import Quartz

kVK_Escape = 53
kCGEventFlagMaskShift = 0x00020000
kCGEventFlagMaskAlternate = 0x00080000

class HotkeyManager:
    """
    Monitors global keyboard state on macOS using low-level Quartz queries.
    Features:
    1. Option + Shift (held): Push-to-Talk
    2. Escape: Instant Dismiss (when Swan is active)
    3. Option + Escape: Global Instant Dismiss
    4. Option + Shift + Escape: Toggle Wake Word (Privacy Mode)
    """
    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        on_dismiss: Optional[Callable[[], None]] = None,
        on_toggle_wake: Optional[Callable[[], None]] = None,
        is_active_cb: Optional[Callable[[], bool]] = None
    ):
        self.on_press = on_press
        self.on_release = on_release
        self.on_dismiss = on_dismiss
        self.on_toggle_wake = on_toggle_wake
        self.is_active_cb = is_active_cb

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._is_pressed = False
        self._last_state_change = 0.0
        self._esc_was_down = False
        self._last_dismiss_time = 0.0

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)

    def _monitor_loop(self):
        while self._running:
            try:
                # Query window server for combined modifier flags and physical key states
                flags = Quartz.CGEventSourceFlagsState(Quartz.kCGEventSourceStateCombinedSessionState)
                is_shift = bool(flags & kCGEventFlagMaskShift)
                is_opt = bool(flags & kCGEventFlagMaskAlternate)
                is_esc = bool(Quartz.CGEventSourceKeyState(Quartz.kCGEventSourceStateCombinedSessionState, kVK_Escape))

                now = time.time()

                # 1. Check Escape keypresses (rising edge of Escape)
                if is_esc and not self._esc_was_down:
                    self._esc_was_down = True
                    if (now - self._last_dismiss_time) > 0.25:
                        # Case A: Option + Shift + Escape -> Toggle Wake Word
                        if is_opt and is_shift and self.on_toggle_wake:
                            self._last_dismiss_time = now
                            print("⌨️ [Hotkey] Option + Shift + Escape pressed (Toggle Wake Word)", flush=True)
                            self.on_toggle_wake()

                        # Case B: Option + Escape -> Global Instant Dismiss
                        elif is_opt and self.on_dismiss:
                            self._last_dismiss_time = now
                            print("⌨️ [Hotkey] Option + Escape pressed (Global Dismiss)", flush=True)
                            self.on_dismiss()

                        # Case C: Bare Escape -> Dismiss only when Swan is active
                        elif not is_opt and not is_shift and self.on_dismiss:
                            is_active = self.is_active_cb() if self.is_active_cb else False
                            if is_active:
                                self._last_dismiss_time = now
                                print("⌨️ [Hotkey] Escape pressed while Swan is active (Instant Dismiss)", flush=True)
                                self.on_dismiss()

                elif not is_esc and self._esc_was_down:
                    self._esc_was_down = False

                # 2. Check Push-to-Talk (Option + Shift without Escape)
                if not is_esc:
                    hotkey_down = is_shift and is_opt
                    if hotkey_down and not self._is_pressed:
                        if (now - self._last_state_change) > 0.05:
                            self._is_pressed = True
                            self._last_state_change = now
                            if self.on_press:
                                self.on_press()
                    elif not hotkey_down and self._is_pressed:
                        if (now - self._last_state_change) > 0.05:
                            self._is_pressed = False
                            self._last_state_change = now
                            if self.on_release:
                                self.on_release()

            except Exception:
                pass

            time.sleep(0.015)  # ~66 Hz check rate: ultra responsive, negligible CPU

    @property
    def is_pressed(self) -> bool:
        return self._is_pressed
