import math
import sys
import time
import threading

from PyObjCTools import AppHelper
from Cocoa import NSApplication, NSEvent
from hud_window import LiquidHUDWindow
from state_machine import AssistantStateMachine, AssistantState

def main():
    print("\n" + "="*50)
    print("🦢 SWAN NOTCH HUD PREVIEW & TEST HARNESS")
    print("="*50)
    print("Launching top-bezel notch HUD on your screen...\n")

    cocoa_app = NSApplication.sharedApplication()
    cocoa_app.setActivationPolicy_(0)

    hud = LiquidHUDWindow()
    sm = AssistantStateMachine()

    def on_sm_update(state: AssistantState, label: str, detail: str):
        print(f"👉 [State Transition] State: {state.value.upper()} | Label: '{label}'")
        hud.set_state(state.value, status=state.value.upper(), subtitle=label)

    sm.add_listener(on_sm_update)

    # Simulated audio energy driver for realistic wave animations
    sim_running = True
    current_sim_mode = "idle"

    def audio_sim_loop():
        t = 0.0
        while sim_running:
            t += 0.05
            if current_sim_mode == "listening":
                # Realistic voice cadence with pauses
                val = max(0.08, (math.sin(t * 3.5) * 0.45 + math.sin(t * 7.2) * 0.35 + 0.5) * (0.8 + 0.2 * math.cos(t * 1.2)))
                hud.set_audio_energy(min(1.0, val))
            elif current_sim_mode == "speaking":
                # Rhythmic speech cadence
                val = max(0.1, (math.sin(t * 4.2) * 0.5 + math.sin(t * 8.8) * 0.4 + 0.5))
                hud.set_audio_energy(min(1.0, val))
            elif current_sim_mode == "thinking":
                hud.set_audio_energy(0.06)
            else:
                hud.set_audio_energy(0.04)
            time.sleep(0.04)

    sim_thread = threading.Thread(target=audio_sim_loop, daemon=True)
    sim_thread.start()

    # Step-by-step showcase sequence
    def step_wake():
        nonlocal current_sim_mode
        current_sim_mode = "wake"
        print("\n✨ Step 1: Wake Word Invocation ('Swan!')")
        sm.on_wake("Tayyorman, Janob")
        hud.show(state="wake", status="SWAN", subtitle="Tayyorman, Janob")
        AppHelper.callLater(3.0, step_listening)

    def step_listening():
        nonlocal current_sim_mode
        current_sim_mode = "listening"
        print("\n🎙️ Step 2: User Speaking ('Swan, tell me about black holes')")
        sm.on_listening("Listening...")
        AppHelper.callLater(3.8, step_thinking)

    def step_thinking():
        nonlocal current_sim_mode
        current_sim_mode = "thinking"
        print("\n⚡ Step 3: Model Thinking & Reasoning (Dynamic Synaptic Pulse)")
        sm.on_thinking()
        AppHelper.callLater(3.5, step_action)

    def step_action():
        nonlocal current_sim_mode
        current_sim_mode = "action"
        print("\n⚙️ Step 4: Model Executing Tool / Agent Action")
        sm.on_action("Searching Web: Black Holes...")
        AppHelper.callLater(3.2, step_speaking)

    def step_speaking():
        nonlocal current_sim_mode
        current_sim_mode = "speaking"
        print("\n🔊 Step 5: Gemini Speaking Response with Audio Waveform")
        sm.on_speaking("Speaking...")
        AppHelper.callLater(4.0, step_loop)

    def step_loop():
        print("\n🔄 Demo cycle finished. Looping to showcase again in 2s...")
        AppHelper.callLater(2.0, step_wake)

    # Keyboard monitor in terminal for manual state toggling
    def keyboard_input_loop():
        print("💡 Interactive Keyboard Controls (type in terminal + Enter):")
        print("   1 : Wake ('Tayyorman, Janob')")
        print("   2 : Listening ('Listening...')")
        print("   3 : Thinking ('Thinking...')")
        print("   4 : Action ('Opening Safari...')")
        print("   5 : Speaking ('Speaking...')")
        print("   h : Toggle Hide/Show")
        print("   q : Quit Preview\n")
        while sim_running:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                cmd = line.strip().lower()
                if cmd == '1':
                    nonlocal current_sim_mode
                    current_sim_mode = "wake"
                    AppHelper.callAfter(lambda: (sm.on_wake("Tayyorman, Janob"), hud.show(state="wake", status="SWAN", subtitle="Tayyorman, Janob")))
                elif cmd == '2':
                    current_sim_mode = "listening"
                    AppHelper.callAfter(lambda: (sm.on_listening("Listening..."), hud.show(state="listening", status="LISTENING", subtitle="Listening...")))
                elif cmd == '3':
                    current_sim_mode = "thinking"
                    AppHelper.callAfter(lambda: sm.on_thinking())
                elif cmd == '4':
                    current_sim_mode = "action"
                    AppHelper.callAfter(lambda: sm.on_action("Opening Safari..."))
                elif cmd == '5':
                    current_sim_mode = "speaking"
                    AppHelper.callAfter(lambda: sm.on_speaking("Speaking..."))
                elif cmd == 'h':
                    if hud._is_visible:
                        AppHelper.callAfter(lambda: (sm.on_idle(), hud.hide(delay=0.0)))
                    else:
                        AppHelper.callAfter(lambda: (sm.on_wake("Tayyorman, Janob"), hud.show(state="wake", status="SWAN", subtitle="Tayyorman, Janob")))
                elif cmd == 'q':
                    print("Quitting preview...")
                    AppHelper.callAfter(AppHelper.stopEventLoop)
                    break
            except Exception:
                break

    input_thread = threading.Thread(target=keyboard_input_loop, daemon=True)
    input_thread.start()

    # Start automated demo sequence
    AppHelper.callLater(0.5, step_wake)
    AppHelper.runConsoleEventLoop()

if __name__ == "__main__":
    main()
