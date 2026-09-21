import os
import unittest

def test_pointer_ablation():
    """Verify that pointer overlay and point_on_screen are completely ablated."""
    assert not os.path.exists("pointer_overlay.py"), "pointer_overlay.py should be deleted"
    assert not os.path.exists("pointer_template.html"), "pointer_template.html should be deleted"

    import tools
    assert "point_on_screen" not in tools.TOOL_HANDLERS
    assert "point_at" not in tools.TOOL_HANDLERS
    assert "pointer" not in tools.TOOL_HANDLERS

    tool_declarations = tools.get_jarvis_tools()[0].function_declarations
    declaration_names = [d.name for d in tool_declarations]
    assert "point_on_screen" not in declaration_names, "point_on_screen must not be in Gemini tool declarations"

def test_reflex_fast_paths():
    """Verify that fast-path deterministic rules continue to execute with zero latency."""
    from reflex_engine import reflex_engine

    # Fast-path open app
    d1 = reflex_engine.evaluate("open terminal and run build")
    assert d1 is not None
    assert d1.choice == "open_app"
    assert d1.params.get("app_name") == "Terminal"
    assert d1.confidence >= 0.90

    # Fast-path stop agent
    d2 = reflex_engine.evaluate("agentni to'xtat")
    assert d2 is not None
    assert d2.choice == "stop_agent"
    assert d2.confidence >= 0.90

    # Fast-path mute
    d3 = reflex_engine.evaluate("mute audio")
    assert d3 is not None
    assert d3.choice == "media_control" or d3.choice == "system_control"

def test_laya_engine_standby_and_fallback():
    """Verify that Laya engine operates cleanly in standby with graceful fallbacks."""
    from laya_engine import laya_engine, LayaStatus
    from reflex_engine import reflex_engine

    status = laya_engine.get_status_dict()
    assert "status" in status
    assert "device" in status

    # When Laya is not yet ready, evaluate_speech_intent returns None without raising exceptions
    res = laya_engine.evaluate_speech_intent("open safari")
    # If not ready, should be None
    if not laya_engine.is_ready():
        assert res is None

    # Reflex engine should still gracefully handle unknown queries without crashing
    d = reflex_engine.evaluate("what is quantum entanglement?")
    if d is not None:
        assert d.choice == "ask_ai"

def test_ui_and_spoken_action_rules():
    """Verify that Dynamic Island horn corners are deleted, spoken action instructions are active, and phonetic reflex matches."""
    with open("hud_template.html", "r") as f:
        hud_content = f.read()
    assert ".dynamic-island::before" not in hud_content, "Concave horn pseudo-element must be removed"
    assert ".dynamic-island::after" not in hud_content, "Concave horn pseudo-element must be removed"

    from config import AppConfig
    cfg = AppConfig()
    cmd_inst = cfg.get_system_instruction(active_mode="command")
    assert "SILENT EXECUTION" in cmd_inst or "JIM BAJARISH" in cmd_inst
    assert "Janob" in cmd_inst
    assert "John" in cmd_inst

    chat_inst = cfg.get_system_instruction(active_mode="chat")
    assert "ovozli jumla" in chat_inst

    from reflex_engine import reflex_engine
    assert reflex_engine.evaluate("safari are").params.get("app_name") == "Safari"
    assert reflex_engine.evaluate("the notes").params.get("app_name") == "Notes"
    assert reflex_engine.evaluate("telegram og").params.get("app_name") == "Telegram"
    assert reflex_engine.evaluate("gently talks dirt").choice == "stop_agent"

