import time
from typing import List, Tuple, Dict, Any, Optional
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.live import Live
from config import config

console = Console()

class AppUI:
    def __init__(self, initial_mode: str = "command"):
        self.state = "CONNECTING"  # CONNECTING, READY, LISTENING, THINKING, SPEAKING, ERROR
        self.mode = initial_mode   # "command" or "chat"
        self.status_message = "Initializing Swan Assistant..."
        self.history: List[Tuple[str, str]] = []  # (role, text)
        self.recent_tool_actions: List[str] = []
        self.current_stream_text = ""
        self.latency_ms: float = 0.0
        self.rms_level: float = 0.0
        self._live = None

    def start(self):
        self._live = Live(self.render(), console=console, refresh_per_second=20, auto_refresh=True)
        self._live.start()

    def stop(self):
        if self._live:
            self._live.stop()

    def set_state(self, state: str, message: str = ""):
        self.state = state
        if message:
            self.status_message = message
        if self._live:
            self._live.update(self.render())

    def set_mode(self, mode: str):
        self.mode = mode
        if self._live:
            self._live.update(self.render())

    def add_tool_action(self, tool_name: str, args: Dict[str, Any], result: Dict[str, Any]):
        args_str = ", ".join(f'{k}="{v}"' for k, v in args.items())
        status_icon = "✅" if result.get("status") == "success" else "⚠️"
        action_msg = f"{status_icon} Action: {tool_name}({args_str})"
        self.recent_tool_actions.append(action_msg)
        if len(self.recent_tool_actions) > 3:
            self.recent_tool_actions.pop(0)
        if self._live:
            self._live.update(self.render())

    def update_rms(self, rms: float):
        self.rms_level = rms
        if self.state == "LISTENING" and self._live:
            self._live.update(self.render())

    def append_stream_text(self, chunk: str):
        self.current_stream_text += chunk
        if self._live:
            self._live.update(self.render())

    def finalize_turn(self, latency_seconds: float = 0.0):
        if self.current_stream_text.strip():
            self.history.append(("Swan", self.current_stream_text.strip()))
        self.current_stream_text = ""
        self.latency_ms = latency_seconds * 1000
        self.set_state("READY", "Hold Option + Shift to speak to Swan")

    def add_user_turn(self, text: str = "Voice Command"):
        self.history.append(("You", text))
        self.current_stream_text = ""
        if self._live:
            self._live.update(self.render())

    def clear_history(self):
        self.history.clear()
        self.current_stream_text = ""
        self.recent_tool_actions.clear()
        if self._live:
            self._live.update(self.render())

    def _render_meter(self, level: float, width: int = 20) -> str:
        scaled = min(1.0, max(0.0, level * 10.0))
        bars = int(scaled * width)
        return "▰" * bars + "▱" * (width - bars)

    def render(self) -> Group:
        # Header Info Table
        info_table = Table.grid(expand=True)
        info_table.add_column(justify="left", ratio=1)
        info_table.add_column(justify="center", ratio=1)
        info_table.add_column(justify="right", ratio=1)

        mode_badge = (
            Text("🛠️ [COMMAND MODE]", style="bold black on bright_yellow")
            if self.mode == "command"
            else Text("💬 [CHAT MODE]", style="bold white on bright_blue")
        )

        info_table.add_row(
            Text(f"Model: {config.model}", style="bold cyan"),
            mode_badge,
            Text(f"Voice: {config.voice_name} | Hotkey: Option+Shift", style="bold magenta")
        )

        # Status Badge
        if self.state == "CONNECTING":
            status_text = Text(f"🔄 [CONNECTING] {self.status_message}", style="bold yellow")
        elif self.state == "READY":
            status_text = Text(f"🟢 [READY] Press & hold Option + Shift to speak to Swan...", style="bold green")
        elif self.state == "LISTENING":
            meter = self._render_meter(self.rms_level)
            status_text = Text.assemble(
                ("🔴 [LISTENING...] ", "bold red blink"),
                (f"[{meter}] ", "bold red"),
                ("(Release key when done speaking)", "dim")
            )
        elif self.state == "THINKING":
            status_text = Text("⚡ [PROCESSING...] Swan is executing...", style="bold magenta")
        elif self.state == "SPEAKING":
            lat_str = f" | Latency: {self.latency_ms:.0f}ms" if self.latency_ms > 0 else ""
            status_text = Text(f"🔊 [SWAN SPEAKING...]{lat_str}", style="bold cyan")
        elif self.state == "ERROR":
            status_text = Text(f"❌ [ERROR] {self.status_message}", style="bold red")
        else:
            status_text = Text(self.status_message, style="white")

        status_panel = Panel(
            status_text,
            title="🦢 SWAN OS ASSISTANT",
            title_align="left",
            border_style="bright_blue"
        )

        elements = [info_table, status_panel]

        # Recent tool action toasts
        if self.recent_tool_actions:
            tool_texts = [Text(f"⚙️  {act}", style="cyan") for act in self.recent_tool_actions]
            elements.append(
                Panel(Group(*tool_texts), title="Recent System Actions", title_align="left", border_style="cyan")
            )

        # Conversation History
        recent_history = self.history[-5:]
        for role, msg in recent_history:
            if role == "You":
                elements.append(
                    Panel(Text(msg, style="white"), title="🎙️ You", title_align="left", border_style="dim")
                )
            else:
                elements.append(
                    Panel(Text(msg, style="bright_green"), title="🦢 Swan", title_align="left", border_style="green")
                )

        if self.current_stream_text:
            elements.append(
                Panel(Text(self.current_stream_text, style="bright_green"), title="🦢 Swan (speaking)", title_align="left", border_style="yellow")
            )

        footer_text = Text("Hold [Option + Shift] to command Swan • [Ctrl+C] to exit", style="dim center")
        elements.append(footer_text)

        return Group(*elements)
