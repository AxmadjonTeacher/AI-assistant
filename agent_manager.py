import asyncio
import json
import os
import socket
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

from config import config

def _update_hud_working(title: str, subtitle: str):
    try:
        from agent_hud import get_agent_hud
        hud = get_agent_hud()
        if hud:
            hud.show_working(title, subtitle)
    except Exception:
        pass

def _update_hud_completed(title: str, subtitle: str, auto_hide_seconds: float = 4.0):
    try:
        from agent_hud import get_agent_hud
        hud = get_agent_hud()
        if hud:
            hud.show_completed(title, subtitle, auto_hide_seconds)
    except Exception:
        pass

def _update_hud_hide():
    try:
        from agent_hud import get_agent_hud
        hud = get_agent_hud()
        if hud:
            hud.hide()
    except Exception:
        pass

@dataclass
class AgentTask:
    task_id: str
    agent_type: str
    title: str
    prompt: str
    status: str = "running" # "running", "completed", "failed"
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    result_message: Optional[str] = None
    error: Optional[str] = None

class AgentManager:
    """Manages background agent tasks and coordinates visual HUD feedback."""
    def __init__(self):
        self.tasks: Dict[str, AgentTask] = {}
        self._lock = threading.Lock()

    def launch_blender_scene(self, prompt: str, style: str = "cinematic") -> Dict[str, Any]:
        """Launches an autonomous 3D director agent to build a scene in Blender."""
        short_title = prompt[:30] + ("..." if len(prompt) > 30 else "")
        task_id = f"bld-{uuid.uuid4().hex[:6]}"
        task = AgentTask(
            task_id=task_id,
            agent_type="blender",
            title=f"Blender: {short_title}",
            prompt=prompt
        )

        with self._lock:
            self.tasks[task_id] = task

        # 1. Update top-right corner HUD immediately
        _update_hud_working("Agent working...", f"Blender: {short_title}")

        # 2. Run execution in background thread so Swan is never blocked
        thread = threading.Thread(target=self._run_blender_worker, args=(task, style), daemon=True)
        thread.start()

        return {
            "status": "launched",
            "task_id": task_id,
            "agent": "Blender 3D Director",
            "message": "Blender agent launched in the background. The top-right indicator is active. You can continue giving Swan other commands."
        }

    def launch_generic_agent(self, agent_type: str, task_description: str, details: str = "") -> Dict[str, Any]:
        """Launches a general background agent for research, scripts, or long tasks."""
        short_title = task_description[:30] + ("..." if len(task_description) > 30 else "")
        task_id = f"agt-{uuid.uuid4().hex[:6]}"
        task = AgentTask(
            task_id=task_id,
            agent_type=agent_type,
            title=f"{agent_type.capitalize()}: {short_title}",
            prompt=task_description
        )

        with self._lock:
            self.tasks[task_id] = task

        _update_hud_working("Agent working...", f"{agent_type.capitalize()}: {short_title}")

        thread = threading.Thread(target=self._run_generic_worker, args=(task, details), daemon=True)
        thread.start()

        return {
            "status": "launched",
            "task_id": task_id,
            "agent": agent_type,
            "message": f"{agent_type.capitalize()} agent launched in background. Visual indicator active in top-right corner."
        }

    def _play_chime(self):
        """Plays subtle macOS completion chime."""
        try:
            sound_path = "/System/Library/Sounds/Glass.aiff"
            if os.path.exists(sound_path):
                subprocess.Popen(["afplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _ensure_blender_running(self) -> bool:
        """Checks if Blender socket is listening or launches Blender app."""
        # Check socket 9876
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect(("127.0.0.1", 9876))
            s.close()
            return True
        except Exception:
            pass

        # Try launching Blender
        try:
            print("🎨 [AgentManager] Blender not connected on port 9876. Launching Blender.app...", flush=True)
            subprocess.Popen(["open", "-a", "Blender"])
            # Wait up to 5 seconds for socket
            for _ in range(10):
                time.sleep(0.5)
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(0.5)
                    s.connect(("127.0.0.1", 9876))
                    s.close()
                    return True
                except Exception:
                    continue
        except Exception as e:
            print(f"⚠️ [AgentManager] Failed to launch Blender: {e}", flush=True)

        return False

    def _execute_in_blender_socket(self, code_str: str, timeout: float = 60.0) -> Dict[str, Any]:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", 9876))

        wrapped_code = (
            "import bpy, math\n"
            "result = {'status': 'completed'}\n"
            + code_str
            + "\n"
            "# Tag 3D viewport redraw\n"
            "for wm in bpy.data.window_managers:\n"
            "    for win in wm.windows:\n"
            "        for area in win.screen.areas:\n"
            "            if area.type == 'VIEW_3D':\n"
            "                area.tag_redraw()\n"
        )

        payload = json.dumps({
            "type": "execute",
            "code": wrapped_code,
            "strict_json": False
        }) + "\0"

        s.sendall(payload.encode("utf-8"))

        data = b""
        while True:
            chunk = s.recv(8192)
            if not chunk:
                break
            data += chunk
            if b"\0" in chunk:
                break
        s.close()

        raw_response = data.decode("utf-8").rstrip("\0")
        return json.loads(raw_response)

    def _run_blender_worker(self, task: AgentTask, style: str):
        print(f"🎨 [Blender Agent] Generating 3D scene for prompt: '{task.prompt}'", flush=True)
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=config.api_key)

            system_instruction = (
                "You are an elite Hollywood 3D Director and master Blender Python developer. "
                "The user will give you a scene or 3D concept prompt. "
                "Generate COMPLETE, FLAWLESS, ROBUST Python code executable in Blender (bpy). "
                "RULES:\n"
                "1. Clean slate: remove existing default meshes if starting new, or construct on existing scene cleanly.\n"
                "2. Create rich geometry, evocative materials (Principled BSDF with metallic, roughness, emission colors), and dramatic lighting (key lights, rim lights, area lights with vibrant colors).\n"
                "3. Set up a Camera with cinematic framing, depth, or animated camera orbit/travel.\n"
                "4. Standardize fps: bpy.context.scene.render.fps = 24. Set frame_start=1 and frame_end=120.\n"
                "5. Ensure all transforms, constraints, and collections are cleanly created.\n"
                "6. Output ONLY raw executable Python code inside ```python ``` markdown block. No conversational filler."
            )

            user_msg = f"Build this 3D scene in Blender with {style} cinematography:\nPrompt: {task.prompt}"

            cfg = types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.4
            )

            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=user_msg,
                config=cfg
            )

            raw_text = response.text or ""
            # Extract python code
            code = raw_text
            if "```python" in raw_text:
                code = raw_text.split("```python")[1].split("```")[0].strip()
            elif "```" in raw_text:
                code = raw_text.split("```")[1].split("```")[0].strip()

            if not self._ensure_blender_running():
                raise RuntimeError("Could not connect to Blender on 127.0.0.1:9876. Please ensure Blender is running.")

            # Send code to Blender
            exec_res = self._execute_in_blender_socket(code)
            print(f"🎨 [Blender Agent] Code executed in Blender: {exec_res}", flush=True)

            task.status = "completed"
            task.finished_at = time.time()
            task.result_message = "3D scene created successfully in Blender!"

            # Update HUD to completed
            _update_hud_completed("Agent finished ✅", f"Blender: {task.prompt[:25]}", auto_hide_seconds=4.0)
            self._play_chime()

        except Exception as e:
            print(f"❌ [Blender Agent Error]: {e}", flush=True)
            task.status = "failed"
            task.finished_at = time.time()
            task.error = str(e)
            _update_hud_completed("Agent failed ⚠️", f"Blender error: {str(e)[:22]}", auto_hide_seconds=5.0)

    def _run_generic_worker(self, task: AgentTask, details: str):
        print(f"🤖 [Generic Agent] Starting task: '{task.title}'", flush=True)
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=config.api_key)

            prompt = f"Perform this autonomous task thoroughly:\nTask: {task.prompt}\nDetails: {details}"
            cfg = types.GenerateContentConfig(temperature=0.3)
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config=cfg
            )

            task.status = "completed"
            task.finished_at = time.time()
            task.result_message = response.text or "Task completed"

            _update_hud_completed("Agent finished ✅", task.title[:25], auto_hide_seconds=4.0)
            self._play_chime()
        except Exception as e:
            print(f"❌ [Generic Agent Error]: {e}", flush=True)
            task.status = "failed"
            task.finished_at = time.time()
            task.error = str(e)
            _update_hud_completed("Agent failed ⚠️", f"Error: {str(e)[:22]}", auto_hide_seconds=5.0)

    def get_status(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if task_id and task_id in self.tasks:
                t = self.tasks[task_id]
                return {
                    "task_id": t.task_id,
                    "agent_type": t.agent_type,
                    "title": t.title,
                    "status": t.status,
                    "duration": f"{time.time() - t.started_at:.1f}s" if t.status == "running" else f"{t.finished_at - t.started_at:.1f}s",
                    "result": t.result_message,
                    "error": t.error
                }
            # Return summary of all recent tasks
            running_tasks = [t for t in self.tasks.values() if t.status == "running"]
            completed_tasks = [t for t in self.tasks.values() if t.status == "completed"]
            return {
                "active_agents_count": len(running_tasks),
                "running": [{"task_id": t.task_id, "title": t.title, "type": t.agent_type} for t in running_tasks],
                "recent_completed": [{"task_id": t.task_id, "title": t.title} for t in completed_tasks[-3:]]
            }

agent_manager = AgentManager()
