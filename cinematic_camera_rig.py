"""
=============================================================================
Cinematic Camera Choreography & Kinematics Engine for Blender 5.2 / 4.x
Author: Senior Blender Python Camera Choreography Engineer
Compatibility: Blender 4.0 - 5.2+ (Python 3.10 - 3.12)
=============================================================================

Key Architectural Guarantees:
1. 100% Scene Asset Preservation: NEVER deletes, modifies, or unlinks user meshes.
2. Isolated Animation Clearing: Only purges animation data on the camera and rig empties.
3. Singularity / Gimbal Protection: Enforces minimum horizontal offset >= 0.02m
   from the Z-axis pole to prevent TRACK_TO 180-degree yaw snaps.
4. Depth of Field Precision: Full Blender 5.2 exact syntax setup on target empty.
5. Exact Frame Insertion: Standard bpy keyframe_insert on 'location' and 'lens'.
"""

import bpy
import math
import mathutils
from mathutils import Vector
from typing import Optional, Tuple, Dict, Any, List

def get_hero_bounds(scene: bpy.types.Scene, hero_object: Optional[bpy.types.Object] = None) -> Tuple[Vector, float, float]:
    """
    Computes the world-space bounding box center, bounding radius, and height.
    Preserves all scene objects. If hero_object is None, dynamically detects
    the active/selected mesh or the aggregate scene median.
    """
    target_obj = hero_object

    if not target_obj:
        selected_meshes = [o for o in scene.objects if o.type == 'MESH' and o.select_get()]
        if selected_meshes:
            target_obj = selected_meshes[0]
        else:
            mesh_objs = [o for o in scene.objects if o.type == 'MESH']
            if mesh_objs:
                target_obj = mesh_objs[0]

    if target_obj and hasattr(target_obj, 'bound_box') and target_obj.bound_box:
        world_corners = [target_obj.matrix_world @ Vector(corner) for corner in target_obj.bound_box]
        center = sum(world_corners, Vector((0.0, 0.0, 0.0))) / 8.0
        radius = max((c - center).length for c in world_corners)
        min_z = min(c.z for c in world_corners)
        max_z = max(c.z for c in world_corners)
        height = max(max_z - min_z, 0.2)
        return center, max(radius, 0.5), height
    elif target_obj:
        center = target_obj.matrix_world.translation.copy()
        return center, 1.5, 1.5

    return Vector((0.0, 0.0, 1.0)), 1.5, 1.5


def protect_pole_singularity(pos: Vector, target: Vector, min_dist: float = 0.02) -> Vector:
    """
    Singularity Protection:
    Enforces minimum horizontal planar distance >= min_dist (0.02m) from the
    exact vertical Z-axis pole passing through the target. Prevents TRACK_TO
    constraint from hitting gimbal lock and snapping 180 degrees.
    """
    dx = pos.x - target.x
    dy = pos.y - target.y
    planar_dist = math.hypot(dx, dy)

    if planar_dist < min_dist:
        safe_pos = pos.copy()
        if planar_dist > 1e-6:
            ratio = min_dist / planar_dist
            safe_pos.x = target.x + dx * ratio
            safe_pos.y = target.y + dy * ratio
        else:
            safe_pos.x = target.x + min_dist
            safe_pos.y = target.y
        return safe_pos
    return pos.copy()


def set_fcurve_interpolation(obj: bpy.types.Object, interpolation: str = 'BEZIER', handle_type: str = 'AUTO_CLAMPED'):
    """
    Configures F-curve keyframe interpolation and handle types for zero-drift
    stops (AUTO_CLAMPED / VECTOR) or linear robotic arcs.
    """
    if not (obj and obj.animation_data and obj.animation_data.action):
        return

    action = obj.animation_data.action
    fcurves = getattr(action, 'fcurves', None)
    if fcurves is None and hasattr(action, 'layers'):
        try:
            fcurves = []
            for layer in action.layers:
                for strip in layer.strips:
                    if hasattr(strip, 'channelbags') and strip.channelbags:
                        fcurves.extend(strip.channelbags[0].fcurves)
        except Exception:
            fcurves = []

    if fcurves:
        for fc in fcurves:
            for kp in fc.keyframe_points:
                try:
                    kp.interpolation = interpolation
                    if interpolation == 'BEZIER' and handle_type:
                        kp.handle_left_type = handle_type
                        kp.handle_right_type = handle_type
                except Exception:
                    pass


def get_or_create_director_rig(scene: bpy.types.Scene, target_center: Vector) -> Tuple[bpy.types.Object, bpy.types.Object]:
    """
    Retrieves or safely provisions the camera and Camera_LookTarget rig without
    modifying or deleting any existing meshes, materials, or collections.
    """
    look_target = bpy.data.objects.get("Camera_LookTarget")
    if not look_target:
        look_target = bpy.data.objects.new("Camera_LookTarget", None)
        look_target.empty_display_type = 'SPHERE'
        look_target.empty_display_size = 0.25
        scene.collection.objects.link(look_target)
    
    look_target.location = target_center.copy()

    cam = scene.camera
    if not cam or cam.type != 'CAMERA':
        existing_cam = bpy.data.objects.get("CinematicCamera")
        if existing_cam and existing_cam.type == 'CAMERA':
            cam = existing_cam
        else:
            cam_data = bpy.data.cameras.new(name="CinematicCamera")
            cam = bpy.data.objects.new(name="CinematicCamera", object_data=cam_data)
            scene.collection.objects.link(cam)
        scene.camera = cam

    # Clean slate keyframe hygiene: ONLY on camera and target empties
    if cam.animation_data:
        cam.animation_data_clear()
    if cam.data and cam.data.animation_data:
        cam.data.animation_data_clear()
    if look_target.animation_data:
        look_target.animation_data_clear()

    # Rig Constraints: TRACK_TO
    track_constraint = None
    for c in cam.constraints:
        if c.type == 'TRACK_TO':
            track_constraint = c
            break
    if not track_constraint:
        track_constraint = cam.constraints.new(type='TRACK_TO')

    track_constraint.target = look_target
    track_constraint.track_axis = 'TRACK_NEGATIVE_Z'
    track_constraint.up_axis = 'UP_Y'
    track_constraint.influence = 1.0

    # Camera Optics & Depth of Field (Blender 5.2 exact syntax)
    cam.data.clip_start = 0.05
    cam.data.clip_end = 500.0
    cam.data.dof.use_dof = True
    cam.data.dof.focus_object = look_target
    cam.data.dof.aperture_fstop = 2.8

    return cam, look_target


class TrajectoryGenerator:
    @staticmethod
    def generate_orbital(cam: bpy.types.Object,
                         look_target: bpy.types.Object,
                         center: Vector,
                         radius: float,
                         height: float,
                         style: str = 'living_lens',
                         start_f: int = 1,
                         end_f: int = 120,
                         step_frames: int = 4):
        look_target.location = center
        look_target.keyframe_insert(data_path='location', frame=start_f)
        look_target.keyframe_insert(data_path='location', frame=end_f)

        orbit_radius = max(radius * 2.8, 3.0)
        base_z = center.z + max(height * 0.35, 0.4)
        total_frames = end_f - start_f

        frames = list(range(start_f, end_f + 1, step_frames))
        if frames[-1] != end_f:
            frames.append(end_f)

        for f in frames:
            t = (f - start_f) / total_frames

            if style == 'hypermotion':
                s = t + 0.22 * math.sin(2.0 * math.pi * t)
                angle = s * 2.0 * math.pi
                lens = 28.0 - 6.0 * math.sin(math.pi * t)
                z_offset = 0.5 * math.sin(math.pi * t)
            else:
                s = 0.5 * (1.0 - math.cos(math.pi * t))
                angle = s * 2.0 * math.pi
                lens = 48.0 - 20.0 * math.sin(math.pi * t)
                z_offset = 0.35 * math.sin(2.0 * math.pi * t)

            raw_pos = Vector((
                center.x + orbit_radius * math.cos(angle),
                center.y + orbit_radius * math.sin(angle),
                base_z + z_offset
            ))

            safe_pos = protect_pole_singularity(raw_pos, center, min_dist=0.02)
            cam.location = safe_pos
            cam.keyframe_insert(data_path='location', frame=f)

            cam.data.lens = lens
            cam.data.keyframe_insert(data_path='lens', frame=f)

        set_fcurve_interpolation(cam, interpolation='BEZIER', handle_type='AUTO_CLAMPED')
        set_fcurve_interpolation(cam.data, interpolation='BEZIER', handle_type='AUTO_CLAMPED')


    @staticmethod
    def generate_push_in(cam: bpy.types.Object,
                         look_target: bpy.types.Object,
                         center: Vector,
                         radius: float,
                         height: float,
                         style: str = 'living_lens',
                         start_f: int = 1,
                         end_f: int = 120,
                         vertigo_effect: bool = True):
        look_target.location = center
        look_target.keyframe_insert(data_path='location', frame=start_f)
        look_target.keyframe_insert(data_path='location', frame=end_f)

        d_start = max(radius * 4.5, 6.0)
        d_end = max(radius * 1.5, 1.8)
        z_start = center.z + max(height * 1.8, 2.2)
        z_end = center.z + max(height * 0.15, 0.2)
        focal_start = 85.0 if vertigo_effect else 28.0
        total_frames = end_f - start_f

        frames = list(range(start_f, end_f + 1, 4))
        if frames[-1] != end_f:
            frames.append(end_f)

        for f in frames:
            t = (f - start_f) / total_frames
            s = 0.5 * (1.0 - math.cos(math.pi * t))

            curr_dist = d_start + (d_end - d_start) * s
            curr_z = z_start + (z_end - z_start) * s

            raw_pos = Vector((
                center.x + curr_dist * 0.25,
                center.y - curr_dist * 0.968,
                curr_z
            ))

            safe_pos = protect_pole_singularity(raw_pos, center, min_dist=0.02)
            cam.location = safe_pos
            cam.keyframe_insert(data_path='location', frame=f)

            if vertigo_effect:
                current_lens = focal_start * (curr_dist / d_start)
            else:
                current_lens = 24.0 + (65.0 - 24.0) * s

            cam.data.lens = current_lens
            cam.data.keyframe_insert(data_path='lens', frame=f)

        set_fcurve_interpolation(cam, interpolation='BEZIER', handle_type='AUTO_CLAMPED')
        set_fcurve_interpolation(cam.data, interpolation='BEZIER', handle_type='AUTO_CLAMPED')


    @staticmethod
    def generate_robo_arm(cam: bpy.types.Object,
                          look_target: bpy.types.Object,
                          center: Vector,
                          radius: float,
                          height: float,
                          start_f: int = 1,
                          end_f: int = 120):
        r = max(radius * 2.2, 2.5)

        wp1_pos = protect_pole_singularity(Vector((center.x - r * 0.8, center.y - r * 0.8, center.z - 0.2 * height)), center)
        wp1_apex = protect_pole_singularity(Vector((center.x + r * 0.2, center.y - r * 1.2, center.z + height * 2.0)), center)
        wp2_pos = protect_pole_singularity(Vector((center.x + r * 0.6, center.y + r * 0.8, center.z + height * 2.8)), center)
        wp2_apex = protect_pole_singularity(Vector((center.x + r * 1.2, center.y - r * 0.4, center.z + height * 0.9)), center)
        wp3_pos = protect_pole_singularity(Vector((center.x + r * 0.7, center.y - r * 0.9, center.z + height * 0.3)), center)

        # WP1 Hold
        cam.location = wp1_pos
        cam.keyframe_insert(data_path='location', frame=1)
        cam.keyframe_insert(data_path='location', frame=25)
        cam.data.lens = 35.0
        cam.data.keyframe_insert(data_path='lens', frame=1)
        cam.data.keyframe_insert(data_path='lens', frame=25)

        # Arc 1 Apex
        cam.location = wp1_apex
        cam.keyframe_insert(data_path='location', frame=35)
        cam.data.lens = 24.0
        cam.data.keyframe_insert(data_path='lens', frame=35)

        # WP2 Hold
        cam.location = wp2_pos
        cam.keyframe_insert(data_path='location', frame=45)
        cam.keyframe_insert(data_path='location', frame=75)
        cam.data.lens = 50.0
        cam.data.keyframe_insert(data_path='lens', frame=45)
        cam.data.keyframe_insert(data_path='lens', frame=75)

        # Arc 2 Apex
        cam.location = wp2_apex
        cam.keyframe_insert(data_path='location', frame=85)
        cam.data.lens = 28.0
        cam.data.keyframe_insert(data_path='lens', frame=85)

        # WP3 Hold
        cam.location = wp3_pos
        cam.keyframe_insert(data_path='location', frame=95)
        cam.keyframe_insert(data_path='location', frame=120)
        cam.data.lens = 65.0
        cam.data.keyframe_insert(data_path='lens', frame=95)
        cam.data.keyframe_insert(data_path='lens', frame=120)

        # Separate LookTarget with reaction lag
        tgt_chest = center.copy()
        tgt_head = Vector((center.x, center.y, center.z + height * 0.5))

        look_target.location = tgt_chest
        look_target.keyframe_insert(data_path='location', frame=1)
        look_target.keyframe_insert(data_path='location', frame=30)

        look_target.location = tgt_head
        look_target.keyframe_insert(data_path='location', frame=50)
        look_target.keyframe_insert(data_path='location', frame=80)

        look_target.location = tgt_chest
        look_target.keyframe_insert(data_path='location', frame=100)
        look_target.keyframe_insert(data_path='location', frame=120)

        set_fcurve_interpolation(cam, interpolation='BEZIER', handle_type='AUTO_CLAMPED')
        set_fcurve_interpolation(cam.data, interpolation='BEZIER', handle_type='AUTO_CLAMPED')
        set_fcurve_interpolation(look_target, interpolation='BEZIER', handle_type='AUTO_CLAMPED')


    @staticmethod
    def generate_surface_dive(cam: bpy.types.Object,
                              look_target: bpy.types.Object,
                              center: Vector,
                              radius: float,
                              height: float,
                              start_f: int = 1,
                              end_f: int = 120):
        look_target.location = center.copy()
        look_target.keyframe_insert(data_path='location', frame=start_f)
        look_target.keyframe_insert(data_path='location', frame=end_f)

        horizontal_offset_y = -max(radius * 2.5, 2.5)
        cam_x = center.x
        cam_y = center.y + horizontal_offset_y

        total_frames = end_f - start_f
        z_floor_entry = center.z - max(height * 3.5, 4.5)
        z_mid_inspect = center.z + max(height * 0.1, 0.15)
        z_roof_exit = center.z + max(height * 3.5, 4.5)

        frames = list(range(start_f, end_f + 1, 4))
        if frames[-1] != end_f:
            frames.append(end_f)

        for f in frames:
            t = (f - start_f) / total_frames
            if t < 0.35:
                sub_t = t / 0.35
                s = 0.5 * (1.0 - math.cos(math.pi * sub_t))
                curr_z = z_floor_entry + (z_mid_inspect - 0.4 - z_floor_entry) * s
            elif t <= 0.70:
                sub_t = (t - 0.35) / 0.35
                curr_z = (z_mid_inspect - 0.4) + 0.8 * sub_t
            else:
                sub_t = (t - 0.70) / 0.30
                s = 0.5 * (1.0 - math.cos(math.pi * sub_t))
                curr_z = (z_mid_inspect + 0.4) + (z_roof_exit - (z_mid_inspect + 0.4)) * s

            raw_pos = Vector((cam_x, cam_y, curr_z))
            safe_pos = protect_pole_singularity(raw_pos, center, min_dist=0.02)

            cam.location = safe_pos
            cam.keyframe_insert(data_path='location', frame=f)

        cam.data.lens = 32.0
        cam.data.keyframe_insert(data_path='lens', frame=start_f)
        cam.data.keyframe_insert(data_path='lens', frame=end_f)

        set_fcurve_interpolation(cam, interpolation='BEZIER', handle_type='AUTO_CLAMPED')


    @staticmethod
    def generate_dialogue_ots(cam: bpy.types.Object,
                              look_target: bpy.types.Object,
                              center: Vector,
                              radius: float,
                              height: float,
                              start_f: int = 1,
                              end_f: int = 120):
        spread = max(radius * 1.2, 1.2)
        char_a_loc = Vector((center.x - spread, center.y, center.z + height * 0.4))
        char_b_loc = Vector((center.x + spread, center.y, center.z + height * 0.4))

        ots_depth = -max(radius * 1.8, 2.0)
        shoulder_z = center.z + height * 0.5

        pos_ots_a = protect_pole_singularity(Vector((char_a_loc.x - 0.4, center.y + ots_depth, shoulder_z)), char_b_loc)
        pos_mid_rail = protect_pole_singularity(Vector((center.x, center.y + ots_depth * 1.2, shoulder_z - 0.1)), center)
        pos_ots_b = protect_pole_singularity(Vector((char_b_loc.x + 0.4, center.y + ots_depth, shoulder_z)), char_a_loc)

        cam.location = pos_ots_a
        cam.keyframe_insert(data_path='location', frame=1)
        cam.keyframe_insert(data_path='location', frame=45)

        cam.location = pos_mid_rail
        cam.keyframe_insert(data_path='location', frame=65)

        cam.location = pos_ots_b
        cam.keyframe_insert(data_path='location', frame=85)
        cam.keyframe_insert(data_path='location', frame=120)

        look_target.location = char_b_loc
        look_target.keyframe_insert(data_path='location', frame=1)
        look_target.keyframe_insert(data_path='location', frame=50)

        look_target.location = char_a_loc
        look_target.keyframe_insert(data_path='location', frame=75)
        look_target.keyframe_insert(data_path='location', frame=120)

        cam.data.lens = 58.0
        cam.data.keyframe_insert(data_path='lens', frame=1)
        cam.data.keyframe_insert(data_path='lens', frame=120)

        set_fcurve_interpolation(cam, interpolation='BEZIER', handle_type='AUTO_CLAMPED')
        set_fcurve_interpolation(look_target, interpolation='BEZIER', handle_type='AUTO_CLAMPED')


def setup_cinematic_director_rig(scene: Optional[bpy.types.Scene] = None,
                                 hero_object: Optional[bpy.types.Object] = None,
                                 style: str = 'living_lens',
                                 trajectory: str = 'orbital',
                                 **kwargs) -> Dict[str, Any]:
    if scene is None:
        scene = bpy.context.scene

    start_frame = kwargs.get('start_frame', 1)
    end_frame = kwargs.get('end_frame', 120)
    scene.frame_start = start_frame
    scene.frame_end = end_frame
    scene.render.fps = 24
    scene.frame_set(start_frame)

    center, radius, height = get_hero_bounds(scene, hero_object)
    cam, look_target = get_or_create_director_rig(scene, center)

    traj_key = trajectory.lower()
    if traj_key == 'orbital':
        step = kwargs.get('step_frames', 4)
        TrajectoryGenerator.generate_orbital(cam, look_target, center, radius, height,
                                            style=style, start_f=start_frame, end_f=end_frame,
                                            step_frames=step)
    elif traj_key == 'push_in':
        vertigo = kwargs.get('vertigo_effect', True)
        TrajectoryGenerator.generate_push_in(cam, look_target, center, radius, height,
                                             style=style, start_f=start_frame, end_f=end_frame,
                                             vertigo_effect=vertigo)
    elif traj_key == 'robo_arm':
        TrajectoryGenerator.generate_robo_arm(cam, look_target, center, radius, height,
                                              start_f=start_frame, end_f=end_frame)
    elif traj_key == 'surface_dive':
        TrajectoryGenerator.generate_surface_dive(cam, look_target, center, radius, height,
                                                  start_f=start_frame, end_f=end_frame)
    elif traj_key == 'dialogue_ots':
        TrajectoryGenerator.generate_dialogue_ots(cam, look_target, center, radius, height,
                                                  start_f=start_frame, end_f=end_frame)
    else:
        TrajectoryGenerator.generate_orbital(cam, look_target, center, radius, height,
                                            style=style, start_f=start_frame, end_f=end_frame)

    scene.frame_set(start_frame)

    for wm in bpy.data.window_managers:
        for win in wm.windows:
            for area in win.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

    return {
        "status": "success",
        "style": style,
        "trajectory": traj_key,
        "camera": cam.name,
        "look_target": look_target.name,
        "hero_center": [round(v, 3) for v in center],
        "bounding_radius": round(radius, 3),
        "frame_range": [start_frame, end_frame]
    }

if __name__ == '__main__':
    res = setup_cinematic_director_rig(
        scene=bpy.context.scene,
        style='living_lens',
        trajectory='orbital'
    )
    print(f"[Cinematic Director Rig] Success: {res}")
