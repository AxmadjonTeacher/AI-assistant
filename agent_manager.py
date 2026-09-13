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

    @staticmethod
    def _clean_code(raw_text: str) -> str:
        if "```python" in raw_text:
            return raw_text.split("```python")[1].split("```")[0].strip()
        elif "```py" in raw_text:
            return raw_text.split("```py")[1].split("```")[0].strip()
        elif "```" in raw_text:
            return raw_text.split("```")[1].split("```")[0].strip()
        return raw_text.strip()

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
            "# Ensure result variable is always a valid dict for Blender MCP bridge\n"
            "if not isinstance(locals().get('result'), dict):\n"
            "    result = {'status': 'completed', 'objects_count': len(bpy.data.objects)}\n"
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

        raw_response = data.decode("utf-8").rstrip("\0").strip()
        res = json.loads(raw_response)
        if isinstance(res, dict) and res.get("status") == "error":
            err_msg = res.get("message") or "Blender execution error"
            raise RuntimeError(err_msg)
        return res

    @staticmethod
    def _generate_with_fallback(client, contents, config, models=("gemini-flash-latest", "gemini-3.5-flash", "gemini-3.6-flash")):
        last_err = None
        for m in models:
            try:
                return client.models.generate_content(model=m, contents=contents, config=config)
            except Exception as e:
                last_err = e
                err_str = str(e)
                if any(kw in err_str for kw in ("429", "RESOURCE_EXHAUSTED", "404", "NOT_FOUND", "503")):
                    print(f"⚠️ [AgentManager] Model '{m}' error ({err_str[:60]}...). Falling back to next model...", flush=True)
                    continue
                raise e
        raise last_err

    def _inspect_blender_scene(self) -> Dict[str, Any]:
        """Queries Blender socket to retrieve live scene metadata before generating code."""
        try:
            inspect_code = (
                "import bpy\n"
                "objs = []\n"
                "for o in bpy.data.objects:\n"
                "    objs.append({'name': o.name, 'type': o.type, 'loc': [round(v, 2) for v in o.location]})\n"
                "active_cam = bpy.context.scene.camera.name if bpy.context.scene.camera else None\n"
                "result = {\n"
                "    'count': len(objs),\n"
                "    'objects': objs,\n"
                "    'active_camera': active_cam,\n"
                "    'frame_start': bpy.context.scene.frame_start,\n"
                "    'frame_end': bpy.context.scene.frame_end,\n"
                "    'fps': bpy.context.scene.render.fps\n"
                "}\n"
            )
            res = self._execute_in_blender_socket(inspect_code, timeout=8.0)
            return res.get("result", {})
        except Exception as e:
            print(f"⚠️ [AgentManager] Scene inspection failed: {e}", flush=True)
            return {}

    def _run_blender_worker(self, task: AgentTask, style: str):
        print(f"🎨 [Blender Agent] Processing 3D task for prompt: '{task.prompt}'", flush=True)
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=config.api_key)

            if not self._ensure_blender_running():
                raise RuntimeError("Could not connect to Blender on 127.0.0.1:9876. Please ensure Blender is running.")

            # 1. Live scene introspection
            scene_info = self._inspect_blender_scene()
            existing_count = scene_info.get("count", 0)
            existing_objs = scene_info.get("objects", [])
            active_cam = scene_info.get("active_camera")

            prompt_lower = task.prompt.lower()
            clean_slate_triggers = [
                "new scene", "brand new", "start over", "clean slate", "clear scene",
                "clear everything", "yangi sahna", "boshidan boshla", "tozala"
            ]
            is_clean_slate_requested = any(trig in prompt_lower for trig in clean_slate_triggers)
            is_modification = (existing_count > 0) and not is_clean_slate_requested

            if is_modification:
                obj_summary = ", ".join([f"{o['name']} ({o['type']})" for o in existing_objs[:15]])
                if len(existing_objs) > 15:
                    obj_summary += f"... (+{len(existing_objs)-15} more)"

                print(f"🎬 [Blender Agent] Mode: SCENE PRESERVATION ({existing_count} existing objects). Updating camera/scene without deleting meshes.", flush=True)

                system_instruction = (
                    "You are an elite Hollywood 3D Director and master Blender Python developer for Blender 5.2.\n"
                    "You are working on an EXISTING Blender 3D scene with existing objects the user loves.\n\n"
                    "CRITICAL PRESERVATION & CAMERA RULES (DO NOT VIOLATE):\n"
                    "1. PRESERVE EXISTING ASSETS (ABSOLUTE RULE):\n"
                    "   - NEVER delete, remove, or unlink existing meshes, curves, or materials! DO NOT run bpy.data.objects.remove().\n"
                    "   - The user asked to change or animate the camera, adjust lighting, or modify the scene.\n"
                    "   - Retain all existing objects in place.\n"
                    "2. CAMERA CHOREOGRAPHY & RIGGING (HOLLYWOOD STANDARD):\n"
                    "   - Identify the hero subject from the existing objects (e.g. the central mesh or focal point).\n"
                    "   - Clear previous animation on the camera: if cam.animation_data: cam.animation_data_clear().\n"
                    "   - Create or locate a `Camera_LookTarget` Empty object positioned at the subject's center coordinates: (scene.collection.objects.link(look_target)).\n"
                    "   - Add/ensure a TRACK_TO constraint on the camera targeting `Camera_LookTarget`: track_axis='TRACK_NEGATIVE_Z', up_axis='UP_Y'.\n"
                    "   - Camera Depth of Field: cam.data.dof.use_dof = True; cam.data.dof.focus_object = look_target; cam.data.dof.aperture_fstop = 2.4 (NEVER use focus_target).\n"
                    "   - Dynamic Camera Paths: Generate smooth mathematical trajectories (360-degree orbital rotation, elevator rise, push-in, crane) using trigonometric curves.\n"
                    "   - Keyframing: cam.keyframe_insert(data_path='location', frame=f). Do NOT access action.fcurves directly.\n"
                    "   - Standardize timeline: scene.frame_start = 1; scene.frame_end = 120; scene.frame_set(1).\n"
                    "3. Render engine: Leave default engine ('BLENDER_EEVEE') as is.\n"
                    "4. NEVER use `bpy.ops.wm.read_factory_settings`, `bpy.ops.wm.read_homefile`, or `sys.exit`.\n"
                    "5. Output ONLY raw executable Python code inside a ```python ``` markdown codeblock."
                )

                user_msg = (
                    f"CURRENT LIVE BLENDER SCENE:\n"
                    f"- Existing Objects ({existing_count}): {obj_summary}\n"
                    f"- Active Camera: {active_cam or 'None'}\n\n"
                    f"USER REQUEST: {task.prompt}\n"
                    f"Cinematography Style: {style}\n"
                    f"TASK: Update camera choreography and scene elements smoothly. DO NOT delete existing objects!"
                )
            else:
                print(f"🎬 [Blender Agent] Mode: CLEAN SLATE / NEW SCENE. Generating complete 3D scene.", flush=True)

                system_instruction = (
                    "You are an elite Hollywood 3D Director and master Blender Python developer for Blender 5.2.\n"
                    "The user is creating a BRAND NEW 3D scene from scratch.\n\n"
                    "CRITICAL BLENDER 5.2 RULES (VIOLATIONS WILL CRASH THE ENGINE):\n"
                    "1. Clean slate: remove existing objects:\n"
                    "   for obj in list(bpy.data.objects): bpy.data.objects.remove(obj, do_unlink=True)\n"
                    "   for mat in list(bpy.data.materials): bpy.data.materials.remove(mat, do_unlink=True)\n"
                    "2. Mesh Primitive Operators (exact names & parameters):\n"
                    "   - bpy.ops.mesh.primitive_cube_add(size=..., location=...)\n"
                    "   - bpy.ops.mesh.primitive_cylinder_add(radius=..., depth=..., vertices=..., location=...)\n"
                    "   - bpy.ops.mesh.primitive_plane_add(size=..., location=...)\n"
                    "   - bpy.ops.mesh.primitive_uv_sphere_add(radius=..., segments=..., ring_count=..., location=...)\n"
                    "   - bpy.ops.mesh.primitive_ico_sphere_add(radius=..., subdivisions=..., location=...) (NOTE: 'ico_sphere' with underscore)\n"
                    "   - bpy.ops.mesh.primitive_torus_add(major_radius=..., minor_radius=..., location=...)\n"
                    "   - bpy.ops.mesh.primitive_cone_add(radius1=..., depth=..., location=...)\n"
                    "3. In Blender 5.x / 4.x, Principled BSDF input sockets are: 'Base Color', 'Metallic', 'Roughness', 'Emission Color', 'Emission Strength', 'Specular IOR Level'.\n"
                    "4. Camera & Cinematic Staging:\n"
                    "   - Create a Camera_LookTarget Empty at subject position.\n"
                    "   - Add TRACK_TO constraint on camera pointing at LookTarget.\n"
                    "   - Depth of field: cam.data.dof.focus_object = look_target.\n"
                    "   - Animate dynamic camera movement: cam.keyframe_insert(data_path='location', frame=f).\n"
                    "   - Master timeline: scene.frame_start = 1, scene.frame_end = 120, scene.frame_set(1).\n"
                    "5. Output ONLY raw executable Python code inside a ```python ``` markdown codeblock. No commentary."
                )

                user_msg = f"Build this brand new 3D scene in Blender with {style} cinematography:\nPrompt: {task.prompt}"

            cfg = types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.35
            )

            response = self._generate_with_fallback(client, user_msg, cfg)
            code = self._clean_code(response.text or "")

            # Send code to Blender with self-healing retry (up to 2 repair attempts)
            current_code = code
            last_err = None
            for attempt in range(3):
                try:
                    exec_res = self._execute_in_blender_socket(current_code)
                    print(f"🎨 [Blender Agent] Code executed successfully (attempt {attempt+1}): {exec_res}", flush=True)
                    last_err = None
                    break
                except RuntimeError as exec_err:
                    last_err = exec_err
                    print(f"⚠️ [Blender Agent] Attempt {attempt+1} failed: {exec_err}", flush=True)
                    if attempt < 2:
                        _update_hud_working("Agent repairing...", f"Self-healing syntax (try {attempt+1})...")
                        repair_prompt = (
                            f"The following Blender Python script failed with this runtime error in Blender 5.2:\n"
                            f"ERROR: {exec_err}\n\n"
                            f"FAILED CODE:\n{current_code}\n\n"
                            f"Please fix the error and output ONLY the corrected complete executable Python code inside a ```python ``` markdown block.\n"
                            f"IMPORTANT RULES FOR BLENDER 5.2:\n"
                            f"- DO NOT delete existing objects if in preservation mode.\n"
                            f"- Camera DOF: use cam.data.dof.focus_object = look_target (NOT focus_target).\n"
                            f"- Keyframing: use cam.keyframe_insert(data_path='location', frame=f). Do NOT access action.fcurves directly.\n"
                            f"- Leave render engine untouched.\n"
                        )
                        repair_resp = self._generate_with_fallback(client, repair_prompt, cfg)
                        current_code = self._clean_code(repair_resp.text or "")
                    else:
                        raise last_err

            if last_err:
                raise last_err

            # Verification: Ensure objects were actually created or preserved
            verify_res = self._execute_in_blender_socket("result = {'count': len(bpy.data.objects), 'names': [o.name for o in bpy.data.objects]}")
            obj_info = verify_res.get("result", {})
            obj_count = obj_info.get("count", 0)

            if obj_count == 0:
                raise RuntimeError("Blender execution finished, but 0 3D objects exist in the scene.")

            # Bring Blender to focus
            try:
                subprocess.run(["osascript", "-e", 'tell application "Blender" to activate'], capture_output=True)
            except Exception:
                pass

            action_desc = "Camera & scene choreography updated" if is_modification else "3D scene created"
            task.status = "completed"
            task.finished_at = time.time()
            task.result_message = f"{action_desc} successfully with {obj_count} objects preserved! Press Spacebar in Blender to play animation."

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
            response = self._generate_with_fallback(client, prompt, cfg)

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
