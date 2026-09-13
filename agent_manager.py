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

def resolve_image_file(query: Optional[str] = None, prompt_hint: str = "") -> Optional[str]:
    """Intelligently resolves an image file path from a query or scans the prompt.
    Supports ~/Desktop, ~/Downloads, ~/Pictures, ~/Documents, exact paths, fuzzy names,
    and 'screen' (takes a screenshot).
    """
    import re
    desktop_dir = os.path.expanduser("~/Desktop")
    downloads_dir = os.path.expanduser("~/Downloads")
    pictures_dir = os.path.expanduser("~/Pictures")
    documents_dir = os.path.expanduser("~/Documents")
    search_folders = [desktop_dir, downloads_dir, pictures_dir, documents_dir, os.getcwd()]

    target_str = (query or "").strip()
    if not target_str and prompt_hint:
        # Check quoted filenames
        quoted = re.findall(r'["\']([^"\']+\.(?:png|jpg|jpeg|webp|svg|bmp))["\']', prompt_hint, re.IGNORECASE)
        if quoted:
            target_str = quoted[0]
        else:
            unquoted = re.findall(r'([\w\-_ ]+\.(?:png|jpg|jpeg|webp|svg|bmp))', prompt_hint, re.IGNORECASE)
            if unquoted:
                target_str = unquoted[0].strip()
            elif any(s in prompt_hint.lower() for s in ("screen", "ekran", "screenshot", "active_screen")):
                target_str = "screen"

    if not target_str:
        return None

    target_str = target_str.strip("\"' \t\n")

    # Screen capture check
    if target_str.lower() in ("screen", "screenshot", "active_screen", "ekran", "ekrandagi"):
        try:
            shot_path = f"/tmp/swan_screen_{int(time.time())}.png"
            subprocess.run(["screencapture", "-x", "-C", shot_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.isfile(shot_path):
                return shot_path
        except Exception:
            pass

    expanded = os.path.expanduser(target_str)
    if os.path.isfile(expanded):
        return expanded

    clean_name = os.path.basename(target_str)
    clean_norm = clean_name.lower().replace(" ", "").replace("_", "").replace("-", "")

    for folder in search_folders:
        if not os.path.isdir(folder):
            continue
        cand = os.path.join(folder, clean_name)
        if os.path.isfile(cand):
            return cand
        try:
            items = os.listdir(folder)
            for item in items:
                if item.lower() == clean_name.lower():
                    c = os.path.join(folder, item)
                    if os.path.isfile(c): return c
            for item in items:
                item_norm = item.lower().replace(" ", "").replace("_", "").replace("-", "")
                if item_norm == clean_norm:
                    c = os.path.join(folder, item)
                    if os.path.isfile(c): return c
            base_no_ext = os.path.splitext(clean_name)[0].lower()
            if len(base_no_ext) >= 3:
                for item in items:
                    if item.lower().startswith(base_no_ext) and item.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.svg')):
                        c = os.path.join(folder, item)
                        if os.path.isfile(c): return c
        except Exception:
            pass

    # Keyword search on Desktop for logo/reference/icon
    if any(kw in target_str.lower() or kw in prompt_hint.lower() for kw in ("logo", "reference", "icon")):
        try:
            dt_items = [f for f in os.listdir(desktop_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.svg'))]
            for f in dt_items:
                if "logo" in f.lower() or "reference" in f.lower():
                    return os.path.join(desktop_dir, f)
        except Exception:
            pass

    return None

class AgentManager:
    """Manages background agent tasks and coordinates visual HUD feedback."""
    def __init__(self):
        self.tasks: Dict[str, AgentTask] = {}
        self._lock = threading.Lock()

    def launch_blender_scene(self, prompt: str, style: str = "cinematic", reference_image: Optional[str] = None) -> Dict[str, Any]:
        """Launches an autonomous 3D director agent to build a scene in Blender,
        or reconstructs a 2D reference logo/image into a high-fidelity 3D model.
        """
        resolved_img = resolve_image_file(reference_image, prompt_hint=prompt)
        is_reconstruction = bool(resolved_img and os.path.isfile(resolved_img))

        short_title = prompt[:30] + ("..." if len(prompt) > 30 else "")
        task_id = f"bld-{uuid.uuid4().hex[:6]}"

        if is_reconstruction:
            img_name = os.path.basename(resolved_img)
            task_title = f"3D Logo: {img_name}"
            task_type = "blender_logo_3d"
            hud_text = f"Recreating {img_name} in 3D..."
        else:
            task_title = f"Blender: {short_title}"
            task_type = "blender"
            hud_text = f"Blender: {short_title}"

        task = AgentTask(
            task_id=task_id,
            agent_type=task_type,
            title=task_title,
            prompt=prompt
        )

        with self._lock:
            self.tasks[task_id] = task

        # 1. Update top-right corner HUD immediately
        _update_hud_working("Agent vision active 👁️" if is_reconstruction else "Agent working...", hud_text)

        # 2. Run execution in background thread so Swan is never blocked
        thread = threading.Thread(target=self._run_blender_worker, args=(task, style, resolved_img), daemon=True)
        thread.start()

        return {
            "status": "launched",
            "task_id": task_id,
            "agent": "Blender 3D Vision Artist" if is_reconstruction else "Blender 3D Director",
            "reference_image": resolved_img if is_reconstruction else None,
            "message": f"Blender agent launched to reconstruct '{os.path.basename(resolved_img)}' in 3D." if is_reconstruction else "Blender agent launched in the background. The top-right indicator is active."
        }

    def launch_image_agent(self, prompt: str, source_image_path: Optional[str] = None, aspect_ratio: str = "1:1", model_preference: Optional[str] = None) -> Dict[str, Any]:
        """Launches an autonomous image generation or editing background agent.
        Output is ALWAYS saved directly to the user's Desktop (~/Desktop) and automatically opened.
        """
        is_edit = bool(source_image_path)
        action_name = "Edit Image" if is_edit else "Generate Image"
        short_title = prompt[:30] + ("..." if len(prompt) > 30 else "")
        task_id = f"img-{uuid.uuid4().hex[:6]}"
        task = AgentTask(
            task_id=task_id,
            agent_type="image_edit" if is_edit else "image_gen",
            title=f"{action_name}: {short_title}",
            prompt=prompt
        )

        with self._lock:
            self.tasks[task_id] = task

        hud_label = "Agent editing image..." if is_edit else "Agent generating image..."
        _update_hud_working(hud_label, short_title)

        thread = threading.Thread(
            target=self._run_image_worker,
            args=(task, source_image_path, aspect_ratio, model_preference),
            daemon=True
        )
        thread.start()

        return {
            "status": "launched",
            "task_id": task_id,
            "agent": "Swan Visual Artist",
            "output_directory": os.path.expanduser("~/Desktop"),
            "message": f"Image task started in background. The generated image will appear directly on your Desktop (~/Desktop) and open automatically. Visual HUD active."
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

        # Dynamically load cinematic camera rig helper if present
        rig_helper = ""
        try:
            from resource_helper import get_resource_path
            rig_file = get_resource_path("cinematic_camera_rig.py")
        except Exception:
            rig_file = os.path.join(os.path.dirname(__file__), "cinematic_camera_rig.py")
        if os.path.isfile(rig_file):
            try:
                with open(rig_file, "r", encoding="utf-8") as rf:
                    rig_helper = rf.read() + "\n"
            except Exception:
                pass

        wrapped_code = (
            "import bpy, math\n"
            "result = {'status': 'completed'}\n"
            + rig_helper
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
    def _generate_with_fallback(client, contents, config, models=("gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-flash-latest", "gemini-3.8-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite")):
        last_err = None
        from google.genai import types
        if config and not getattr(config, "http_options", None):
            config.http_options = types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))

        for m in models:
            try:
                return client.models.generate_content(model=m, contents=contents, config=config)
            except Exception as e:
                last_err = e
                err_str = str(e)
                if any(kw in err_str for kw in ("429", "RESOURCE_EXHAUSTED", "404", "NOT_FOUND", "503", "UNAVAILABLE", "Unavailable")):
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

    def _run_blender_worker(self, task: AgentTask, style: str, reference_image_path: Optional[str] = None):
        print(f"🎨 [Blender Agent] Processing 3D task: '{task.prompt}' (reference: {reference_image_path})", flush=True)
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(
                api_key=config.api_key,
                http_options={"retry_options": {"attempts": 1}}
            )

            if not self._ensure_blender_running():
                raise RuntimeError("Could not connect to Blender on 127.0.0.1:9876. Please ensure Blender is running.")

            # MODE A: 2D REFERENCE IMAGE / LOGO TO 3D MODEL RECONSTRUCTION
            if reference_image_path and os.path.isfile(reference_image_path):
                from PIL import Image
                pil_img = Image.open(reference_image_path)
                img_name = os.path.basename(reference_image_path)
                print(f"👁️ [Blender Agent] Mode: 2D REFERENCE LOGO RECONSTRUCTION for '{img_name}'", flush=True)
                _update_hud_working("Agent vision active 👁️", f"Analyzing {img_name}...")

                system_instruction = (
                    "You are a World-Class 3D Technical Artist, Master Sculptor, and Blender 5.2 Python (bpy) Automation Specialist.\n"
                    "Your mission is to analyze this 2D reference logo / graphic image and write a complete, self-contained Blender 5.2 Python script that creates an exact, gorgeous 3D version of it in Blender.\n\n"
                    "CRITICAL BLENDER 5.2 RULES & MODELING PATTERNS:\n"
                    "1. CLEAN SLATE & RESET:\n"
                    "   for obj in list(bpy.data.objects): bpy.data.objects.remove(obj, do_unlink=True)\n"
                    "   for mat in list(bpy.data.materials): bpy.data.materials.remove(mat, do_unlink=True)\n"
                    "   for c in list(bpy.data.curves): bpy.data.curves.remove(c, do_unlink=True)\n\n"
                    "2. 2D CURVE MODELING WITH EXTRUSION & BEVELING (BEST FOR LOGOS):\n"
                    "   - For all shapes, wings, crests, emblems, and outlines, create 2D Curves:\n"
                    "     c = bpy.data.curves.new(name='ShapeName', type='CURVE')\n"
                    "     c.dimensions = '2D'\n"
                    "     c.fill_mode = 'BOTH'\n"
                    "     c.extrude = 0.08  # local Z extrusion depth\n"
                    "     c.bevel_depth = 0.015  # smooth beveled highlight edge\n"
                    "     c.bevel_resolution = 4\n"
                    "   - Spline creation:\n"
                    "     spline = c.splines.new(type='BEZIER')\n"
                    "     spline.use_cyclic_u = True (for closed shapes)\n"
                    "     if len(points) > 1: spline.bezier_points.add(len(points) - 1)\n"
                    "     Set coordinates bp.co = (x, y, 0.0). Keep coordinates centered around (0,0) in range [-2.0, 2.0].\n"
                    "     For sharp/corner points: bp.handle_left_type = 'VECTOR', bp.handle_right_type = 'VECTOR'.\n"
                    "     For curved arcs: bp.handle_left_type = 'AUTO', bp.handle_right_type = 'AUTO'.\n"
                    "   - AUTOMATIC HOLE CUTOUTS:\n"
                    "     If a shape has hollow rings, donut holes, or cutouts (like concentric circles or letters O, P, A), add BOTH the outer contour and the inner cutout splines into the SAME curve object! Blender's 2D curve engine will automatically carve the hole cleanly without buggy booleans.\n\n"
                    "3. GEOMETRIC PRIMITIVES COMPOSITION:\n"
                    "   - If parts are circles, disks, or cylinders, you can use primitives with non-destructive bevel modifier:\n"
                    "     bpy.ops.mesh.primitive_cylinder_add(radius=..., depth=..., vertices=64, location=(...))\n"
                    "     mod = obj.modifiers.new(name='EdgeBevel', type='BEVEL')\n"
                    "     mod.width = 0.03; mod.segments = 4; mod.limit_method = 'ANGLE'\n\n"
                    "4. STEPPED Z-OFFSETS (ZERO Z-FIGHTING):\n"
                    "   - Overlapping shapes MUST have distinct Z-depth offsets (e.g. Base/Shield at Z=0.00, Midground shapes at Z=0.03, Foreground icon/text at Z=0.06).\n\n"
                    "5. EXACT PBR MATERIALS & LINEAR sRGB COLOR SPACE:\n"
                    "   - Extract the exact colors from the logo image.\n"
                    "   - Convert sRGB (0.0 to 1.0) to Linear Scene RGB:\n"
                    "     def srgb_to_linear(c):\n"
                    "         return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4\n"
                    "   - Set Principled BSDF inputs: 'Base Color', 'Roughness' (0.15 for semi-gloss), 'Metallic' (0.15 for subtle sheen or 0.9 for chrome/gold), 'Coat Weight' (0.5 for lacquer finish).\n\n"
                    "6. REFERENCE IMAGE GUIDE OVERLAY (BACKGROUND EMPTY):\n"
                    "   - Add the reference image as a guide empty directly behind the 3D geometry so the user can see 1:1 alignment:\n"
                    f"     ref_path = r'{reference_image_path}'\n"
                    "     if os.path.exists(ref_path):\n"
                    "         img = bpy.data.images.load(ref_path)\n"
                    "         empty = bpy.data.objects.new('Ref_Logo_Guide', None)\n"
                    "         empty.empty_display_type = 'IMAGE'\n"
                    "         empty.data = img\n"
                    "         empty.empty_image_depth = 'BACK'\n"
                    "         empty.empty_image_offset = (-0.5, -0.5)\n"
                    "         empty.scale = (4.0, 4.0, 4.0)\n"
                    "         empty.location = (0.0, 0.0, -0.06)\n"
                    "         empty.color[3] = 0.4\n"
                    "         bpy.context.collection.objects.link(empty)\n\n"
                    "7. STUDIO LIGHTING RIG & REFLECTIVE FLOOR:\n"
                    "   - 3-point studio lighting (Key Area light with warm tone, Fill Area light with soft cool tone, Rim Area light catching the bevel edges).\n"
                    "   - Dark reflective floor plane (Roughness: 0.2, Metallic: 0.3).\n\n"
                    "8. CAMERA & HOLLYWOOD CHOREOGRAPHY:\n"
                    "   - Empty 'Camera_LookTarget' placed at (0, 0, 0).\n"
                    "   - Camera with TRACK_TO constraint pointing at Camera_LookTarget, 85mm telephoto lens, placed at distance ~5.0m to frame the entire logo beautifully.\n"
                    "   - cam.data.dof.use_dof = True, cam.data.dof.focus_object = look_target, cam.data.dof.aperture_fstop = 2.8.\n"
                    "   - Animate smooth orbital move around the 3D logo from frame 1 to 120.\n"
                    "   - scene.frame_start = 1, scene.frame_end = 120, scene.frame_set(1).\n\n"
                    "9. Output ONLY raw executable Python code inside a ```python ``` markdown codeblock without explanations."
                )

                user_msg = f"Recreate this reference logo ({img_name}) as a stunning 3D model in Blender 5.2.\nUser request: {task.prompt}"
                cfg = types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                    http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
                )

                _update_hud_working("Modeling in Blender 3D...", f"Recreating 3D {img_name}...")
                response = self._generate_with_fallback(client, [pil_img, user_msg], cfg)
                code = self._clean_code(response.text or "")
                is_modification = False
            else:
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
                        "CRITICAL SCENE PRESERVATION (ABSOLUTE NON-NEGOTIABLE RULE):\n"
                        "- NEVER delete, remove, unlink, or modify existing meshes, curves, or materials! DO NOT run bpy.data.objects.remove().\n"
                        "- Retain ALL existing objects and scene geometry in place.\n"
                        "- The user wants camera choreography, camera movement, or scene animation.\n\n"
                        "HOLLYWOOD CINEMATOGRAPHY ENGINE & 4 ARCHETYPES:\n"
                        "Map the user's request to the appropriate cinematography archetype:\n"
                        "1. ARCHETYPE 1: CONTINUOUS ONE-SHOT PREVIZ & LIVING LENS (for general flow, orbits, tracking):\n"
                        "   - Single continuous camera move along a smooth organic spline.\n"
                        "   - Living Lens: Animate focal length (cam.data.keyframe_insert(data_path='lens', frame=f)). Widen to 22-24mm during fast movement, tighten to 35-50mm on pauses/accents.\n"
                        "   - Smooth trigonometric orbital path: cx = hero_x + cos(angle)*radius, cy = hero_y + sin(angle)*radius, cz = hero_z + height + sin(t*pi)*tilt.\n"
                        "2. ARCHETYPE 2: DIALOGUE RAILS & OTS COVERAGE (for conversations, multi-character):\n"
                        "   - 21:9 cinematic framing (resolution_x=1920, resolution_y=804).\n"
                        "   - Over-the-shoulder (OTS) shots crawling at shoulder height.\n"
                        "   - Instant cut discipline: camera location and target jump instantly on cut frames with zero transition drift.\n"
                        "3. ARCHETYPE 3: HIGH-CONCEPT ACTION, SURFACE DIVES & ROBO-ARM:\n"
                        "   - Vertical elevator / floor dive: PURE Z-axis movement ONLY, zero rotation (lock X and Y coordinates), smooth ease-in, slowdown in middle with hero dead center.\n"
                        "   - Robo-Arm snaps: Camera whip-arcs to distinct angle, followed by a DEAD STOP with ZERO drift (keyframe identical coordinates at hold start and hold end).\n"
                        "4. ARCHETYPE 4: HYPERMOTION COMMERCIAL:\n"
                        "   - Speed ramping: every shot snaps in hard, sags in the middle, and accelerates into the cut.\n"
                        "   - Packshot composition: hero subject framed on the left third, breathing room on the right.\n\n"
                        "CAMERA RIGGING ARCHITECTURE (BLENDER 5.2 EXACT SYNTAX):\n"
                        "- Identify hero object/center of interest from existing objects.\n"
                        "- Clean old animation on camera: if cam.animation_data: cam.animation_data_clear(). If cam.data.animation_data: cam.data.animation_data_clear().\n"
                        "- Create or locate Empty object named `Camera_LookTarget` placed at subject center: (scene.collection.objects.link(look_target)).\n"
                        "- Ensure TRACK_TO constraint on camera: track_axis='TRACK_NEGATIVE_Z', up_axis='UP_Y', target=look_target.\n"
                        "- Blender 5.2 DOF: cam.data.dof.use_dof = True; cam.data.dof.focus_object = look_target; cam.data.dof.aperture_fstop = 2.8 (NEVER use focus_target).\n"
                        "- Anti-Gimbal Singularity: When passing overhead, maintain minimum horizontal offset (abs(x) >= 0.04 or abs(y) >= 0.04) to prevent 180-degree flip.\n"
                        "- Standardize timeline: scene.render.fps = 24; scene.frame_start = 1; scene.frame_end = 120 (or matched duration); scene.frame_set(1).\n"
                        "- Render engine: Leave existing engine intact.\n"
                        "- NEVER use bpy.ops.wm.read_factory_settings, bpy.ops.wm.read_homefile, or sys.exit.\n"
                        "- Output ONLY executable Python code inside a ```python ``` markdown codeblock without explanations."
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
                    temperature=0.35,
                    http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
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

            if reference_image_path and os.path.isfile(reference_image_path):
                img_bname = os.path.basename(reference_image_path)
                action_desc = f"3D model of '{img_bname}' created"
                hud_msg = f"3D {img_bname} ready"
            elif is_modification:
                action_desc = "Camera & scene choreography updated"
                hud_msg = f"Blender: {task.prompt[:25]}"
            else:
                action_desc = "3D scene created"
                hud_msg = f"Blender: {task.prompt[:25]}"

            task.status = "completed"
            task.finished_at = time.time()
            task.result_message = f"{action_desc} successfully with {obj_count} objects in Blender! Press Spacebar in Blender to play animation."

            # Update HUD to completed
            _update_hud_completed("3D Model Created! ✅" if reference_image_path else "Agent finished ✅", hud_msg, auto_hide_seconds=5.0)
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

    def _run_image_worker(self, task: AgentTask, source_image_path: Optional[str], aspect_ratio: str, model_preference: Optional[str]):
        print(f"🎨 [Image Agent] Starting image task: '{task.title}' (aspect: {aspect_ratio})", flush=True)
        try:
            from datetime import datetime
            desktop_dir = os.path.expanduser("~/Desktop")
            os.makedirs(desktop_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            is_edit = bool(source_image_path)
            if is_edit:
                dest_filename = f"Swan_Edited_{timestamp}.png"
            else:
                dest_filename = f"Swan_Image_{timestamp}.png"
            dest_path = os.path.join(desktop_dir, dest_filename)

            # Resolve source image if editing
            pil_source = None
            resolved_source_path = None
            if is_edit and source_image_path:
                raw_path = os.path.expanduser(source_image_path.strip())
                if os.path.isfile(raw_path):
                    resolved_source_path = raw_path
                elif os.path.isdir(raw_path):
                    exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
                    imgs = [os.path.join(raw_path, f) for f in os.listdir(raw_path) if f.lower().endswith(exts)]
                    if imgs:
                        imgs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                        resolved_source_path = imgs[0]
                else:
                    for folder in [desktop_dir, os.path.expanduser("~/Downloads"), os.path.expanduser("~/Pictures")]:
                        candidate = os.path.join(folder, raw_path.lstrip("/~"))
                        if os.path.isfile(candidate):
                            resolved_source_path = candidate
                            break
                        if raw_path.lower() in folder.lower() and os.path.isdir(folder):
                            exts = (".png", ".jpg", ".jpeg", ".webp")
                            imgs = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(exts)]
                            if imgs:
                                imgs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                                resolved_source_path = imgs[0]
                                break

                if resolved_source_path and os.path.isfile(resolved_source_path):
                    print(f"🖼️ [Image Agent] Loaded source image for editing: {resolved_source_path}", flush=True)
                    from PIL import Image
                    pil_source = Image.open(resolved_source_path)
                else:
                    print(f"⚠️ [Image Agent] Could not locate source image '{source_image_path}'. Proceeding with descriptive generation.", flush=True)

            dim_map = {
                "1:1": (1024, 1024),
                "16:9": (1280, 720),
                "9:16": (720, 1280),
                "4:3": (1024, 768),
                "3:4": (768, 1024)
            }
            norm_ratio = aspect_ratio if aspect_ratio in dim_map else "1:1"
            width, height = dim_map[norm_ratio]

            candidate_models = ["nano-banana-pro-preview", "gemini-3.1-flash-lite-image", "gemini-2.5-flash-image", "gemini-3.1-flash-image"]
            if model_preference:
                pref = model_preference.lower()
                if "lite" in pref:
                    candidate_models = ["gemini-3.1-flash-lite-image", "nano-banana-pro-preview", "gemini-2.5-flash-image"]
                elif "pro" in pref or "banana" in pref or "nano" in pref:
                    candidate_models = ["nano-banana-pro-preview", "gemini-3.1-flash-lite-image", "gemini-2.5-flash-image"]

            success = False
            try:
                from google import genai
                from google.genai import types
                client = genai.Client(api_key=config.api_key)

                contents = [pil_source, task.prompt] if pil_source else task.prompt
                image_cfg = types.ImageConfig(aspect_ratio=norm_ratio)
                gen_cfg = types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=image_cfg
                )

                for m in candidate_models:
                    try:
                        print(f"🎨 [Image Agent] Trying Google GenAI model: '{m}'...", flush=True)
                        resp = client.models.generate_content(model=m, contents=contents, config=gen_cfg)
                        if resp.candidates and resp.candidates[0].content and resp.candidates[0].content.parts:
                            for part in resp.candidates[0].content.parts:
                                if getattr(part, "inline_data", None) and part.inline_data.data:
                                    with open(dest_path, "wb") as f:
                                        f.write(part.inline_data.data)
                                    success = True
                                    print(f"✅ [Image Agent] Successfully generated image via Google GenAI ({m})!", flush=True)
                                    break
                                elif hasattr(part, "as_image"):
                                    part.as_image().save(dest_path, "PNG")
                                    success = True
                                    print(f"✅ [Image Agent] Successfully saved image via Google GenAI ({m})!", flush=True)
                                    break
                        if success:
                            break
                    except Exception as model_err:
                        print(f"⚠️ [Image Agent] Model '{m}' returned: {model_err}", flush=True)
                        continue
            except Exception as genai_err:
                print(f"⚠️ [Image Agent] Google GenAI setup notice: {genai_err}", flush=True)

            if not success or not os.path.exists(dest_path) or os.path.getsize(dest_path) < 1000:
                print("🎨 [Image Agent] Utilizing robust high-resolution visual engine fallback...", flush=True)
                final_prompt = task.prompt
                if pil_source:
                    try:
                        from google import genai
                        client = genai.Client(api_key=config.api_key)
                        v_resp = client.models.generate_content(
                            model="gemini-flash-latest",
                            contents=[pil_source, f"Describe this image and incorporate this instruction: '{task.prompt}'. Output a single photorealistic generation prompt describing the modified scene."]
                        )
                        if v_resp.text:
                            final_prompt = v_resp.text.strip().replace("\n", " ")
                    except Exception:
                        pass

                import urllib.request, urllib.parse, ssl
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

                enc_p = urllib.parse.quote(final_prompt)
                url = f"https://image.pollinations.ai/prompt/{enc_p}?width={width}&height={height}&nologo=true"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
                with urllib.request.urlopen(req, timeout=35, context=ctx) as resp:
                    raw_bytes = resp.read()
                    if len(raw_bytes) > 1000:
                        with open(dest_path, "wb") as f:
                            f.write(raw_bytes)
                        success = True

            if not os.path.exists(dest_path) or os.path.getsize(dest_path) < 1000:
                raise RuntimeError("Failed to generate and save image file to Desktop.")

            try:
                subprocess.Popen(["open", dest_path])
            except Exception:
                pass

            task.status = "completed"
            task.finished_at = time.time()
            task.result_message = f"Image saved to Desktop: {dest_path}"

            _update_hud_completed("Image ready on Desktop! 🎨", dest_filename, auto_hide_seconds=5.0)
            self._play_chime()

        except Exception as e:
            print(f"❌ [Image Agent Error]: {e}", flush=True)
            task.status = "failed"
            task.finished_at = time.time()
            task.error = str(e)
            _update_hud_completed("Image task failed ⚠️", str(e)[:22], auto_hide_seconds=5.0)

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
