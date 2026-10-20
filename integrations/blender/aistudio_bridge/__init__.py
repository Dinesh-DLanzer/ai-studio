"""AI Studio Bridge - Blender 4.2+ Extension

Connects Blender previs and camera data to AI Studio.
Allows sending viewport/camera stills as first/end frames,
exporting animated camera trajectories, and importing approved video clips into the VSE.
"""

import os
from pathlib import Path
import tempfile
import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel

from .client import AIStudioClient, AIStudioError

# In-memory caches for dynamic EnumProperty items
_projects_cache = [("NONE", "No Projects (Click Pair)", "Connect to server to load projects")]
_shots_cache = [("NONE", "No Shots", "Select a project to load shots")]


def get_client(context):
    """Instantiate the AIStudioClient from scene properties or preferences."""
    scene = context.scene
    url = getattr(scene, "aistudio_server_url", "") or "http://127.0.0.1:8765"
    token = getattr(scene, "aistudio_token", "") or ""

    # Fall back to add-on preferences if scene property token is empty
    if not token and __package__:
        prefs = context.preferences.addons.get(__package__)
        if prefs and getattr(prefs, "preferences", None):
            token = getattr(prefs.preferences, "token", "") or ""

    return AIStudioClient(base_url=url, token=token)


def get_projects_items(self, context):
    """Callback returning cached project items for the dropdown."""
    return _projects_cache


def get_shots_items(self, context):
    """Callback returning cached shot items for the dropdown."""
    return _shots_cache


def on_project_update(self, context):
    """Update shot choices whenever a new project is selected."""
    scene = context.scene
    proj = getattr(scene, "aistudio_project", "")
    if not proj or proj == "NONE":
        return

    client = get_client(context)
    try:
        shots_doc = client.get_shots(proj)
        shots = shots_doc.get("shots", [])
        items = []
        for s in shots:
            sid = s.get("id", "")
            if not sid:
                continue
            secs = s.get("seconds", "?")
            prompt = s.get("prompt", "")
            items.append((sid, f"{sid} ({secs}s)", prompt[:60]))
        if not items:
            items = [("NONE", "No Shots Found", "No shots found in project")]
        global _shots_cache
        _shots_cache = items
    except Exception:
        pass


class AIStudioPreferences(AddonPreferences):
    bl_idname = __package__ or "aistudio_bridge"

    server_url: StringProperty(
        name="Server URL",
        default="http://127.0.0.1:8765",
        description="Local AI Studio server URL",
    )
    token: StringProperty(
        name="Session Token",
        default="",
        subtype='PASSWORD',
        description="AI Studio session token or API key",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "server_url")
        layout.prop(self, "token")


class AISTUDIO_OT_pair(Operator):
    """Pair with the AI Studio server and load project list"""

    bl_idname = "aistudio.pair"
    bl_label = "Pair with AI Studio"
    bl_description = "Connect to AI Studio and refresh project list"

    def execute(self, context):
        client = get_client(context)
        try:
            projects = client.pair()
        except AIStudioError as e:
            self.report({'ERROR'}, f"Failed to connect to AI Studio: {e}")
            return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Unexpected error: {e}")
            return {'CANCELLED'}

        items = []
        for p in projects:
            pname = p.get("name") if isinstance(p, dict) else str(p)
            if pname:
                items.append((pname, pname, f"Project {pname}"))

        global _projects_cache
        if items:
            _projects_cache = items
            # Select first project and load its shots
            context.scene.aistudio_project = items[0][0]
            on_project_update(self, context)
            self.report({'INFO'}, f"Paired with AI Studio! Found {len(items)} project(s).")
        else:
            _projects_cache = [("NONE", "No Projects Found", "No projects found on server")]
            self.report({'INFO'}, "Connected, but no projects found on server.")

        return {'FINISHED'}


class AISTUDIO_OT_refresh_projects(Operator):
    """Refresh list of projects from AI Studio"""

    bl_idname = "aistudio.refresh_projects"
    bl_label = "Refresh Projects"
    bl_description = "Fetch latest project list from AI Studio"

    def execute(self, context):
        client = get_client(context)
        try:
            projects = client.list_projects()
        except AIStudioError as e:
            self.report({'ERROR'}, f"Failed to fetch projects: {e}")
            return {'CANCELLED'}

        items = []
        for p in projects:
            pname = p.get("name") if isinstance(p, dict) else str(p)
            if pname:
                items.append((pname, pname, f"Project {pname}"))

        global _projects_cache
        if items:
            _projects_cache = items
            self.report({'INFO'}, f"Loaded {len(items)} project(s).")
        else:
            _projects_cache = [("NONE", "No Projects Found", "")]
            self.report({'INFO'}, "No projects found.")

        return {'FINISHED'}


class AISTUDIO_OT_refresh_shots(Operator):
    """Refresh shots list for currently selected project"""

    bl_idname = "aistudio.refresh_shots"
    bl_label = "Refresh Shots"
    bl_description = "Fetch latest shots for the selected project"

    def execute(self, context):
        scene = context.scene
        proj = getattr(scene, "aistudio_project", "")
        if not proj or proj == "NONE":
            self.report({'ERROR'}, "Select a project first")
            return {'CANCELLED'}

        client = get_client(context)
        try:
            shots_doc = client.get_shots(proj)
            shots = shots_doc.get("shots", [])
            items = []
            for s in shots:
                sid = s.get("id", "")
                if sid:
                    items.append((sid, f"{sid} ({s.get('seconds', '?')}s)", s.get("prompt", "")[:60]))
            global _shots_cache
            if items:
                _shots_cache = items
                self.report({'INFO'}, f"Loaded {len(items)} shot(s).")
            else:
                _shots_cache = [("NONE", "No Shots Found", "")]
                self.report({'INFO'}, "No shots found in project.")
        except AIStudioError as e:
            self.report({'ERROR'}, f"Failed to fetch shots: {e}")
            return {'CANCELLED'}

        return {'FINISHED'}


class AISTUDIO_OT_send_frame(Operator):
    """Render active camera frame and send to AI Studio"""

    bl_idname = "aistudio.send_frame"
    bl_label = "Send Frame"
    bl_description = "Render active camera and upload to AI Studio shot"

    frame_type: EnumProperty(
        name="Frame Type",
        items=[
            ("first_frame", "First Frame", "Set as shot's first frame"),
            ("end_frame", "End Frame", "Set as shot's end frame"),
        ],
        default="first_frame",
    )

    def execute(self, context):
        scene = context.scene
        project = getattr(scene, "aistudio_project", "")
        shot = getattr(scene, "aistudio_shot", "")

        if not project or project == "NONE":
            self.report({'ERROR'}, "Please select a valid project")
            return {'CANCELLED'}
        if not shot or shot == "NONE":
            self.report({'ERROR'}, "Please select a valid shot")
            return {'CANCELLED'}
        if not scene.camera:
            self.report({'ERROR'}, "Scene has no active camera")
            return {'CANCELLED'}

        client = get_client(context)

        # 1. Fetch project shots document to determine aspect ratio
        try:
            shots_doc = client.get_shots(project)
        except AIStudioError as e:
            self.report({'ERROR'}, f"Failed to get project information: {e}")
            return {'CANCELLED'}

        aspect_ratio = shots_doc.get("aspect_ratio", "9:16")
        target_w, target_h = 1080, 1920
        if ":" in str(aspect_ratio):
            try:
                w_str, h_str = str(aspect_ratio).split(":", 1)
                w_val, h_val = int(w_str), int(h_str)
                if w_val > 0 and h_val > 0:
                    if w_val >= h_val:
                        target_w = 1920
                        target_h = int(round(1920 * h_val / w_val))
                    else:
                        target_h = 1920
                        target_w = int(round(1920 * w_val / h_val))
            except Exception:
                target_w, target_h = 1080, 1920

        # 2. Render active camera to temporary PNG
        frame_num = scene.frame_current
        stem = f"{shot}-blender-{frame_num}"
        rel_path = f"stills/{stem}.png"

        orig_res_x = scene.render.resolution_x
        orig_res_y = scene.render.resolution_y
        orig_path = scene.render.filepath
        orig_format = scene.render.image_settings.file_format

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            scene.render.resolution_x = target_w
            scene.render.resolution_y = target_h
            scene.render.filepath = tmp_path
            scene.render.image_settings.file_format = 'PNG'

            bpy.ops.render.render(write_still=True)

            with open(tmp_path, "rb") as f:
                img_bytes = f.read()
        except Exception as e:
            self.report({'ERROR'}, f"Render failed: {e}")
            return {'CANCELLED'}
        finally:
            scene.render.resolution_x = orig_res_x
            scene.render.resolution_y = orig_res_y
            scene.render.filepath = orig_path
            scene.render.image_settings.file_format = orig_format
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        # 3. POST image bytes to upload endpoint
        try:
            client.upload_frame(project, rel_path, img_bytes, replace=1)
        except AIStudioError as e:
            self.report({'ERROR'}, f"Upload failed: {e}")
            return {'CANCELLED'}

        # 4. Update shot's first_frame or end_frame in shots.json
        shots = shots_doc.get("shots", [])
        shot_obj = next((s for s in shots if s.get("id") == shot), None)
        if shot_obj is not None:
            if self.frame_type == "first_frame":
                shot_obj["first_frame"] = rel_path
            elif self.frame_type == "end_frame":
                shot_obj["end_frame"] = rel_path

            try:
                client.put_shots(project, shots_doc)
            except AIStudioError as e:
                self.report({'WARNING'}, f"Frame uploaded, but updating shots.json failed: {e}")
                return {'FINISHED'}

        self.report({'INFO'}, f"Uploaded {self.frame_type} for {shot}: {rel_path}")
        return {'FINISHED'}


class AISTUDIO_OT_send_camera_move(Operator):
    """Sample camera trajectory and send to AI Studio"""

    bl_idname = "aistudio.send_camera_move"
    bl_label = "Send Camera Move"
    bl_description = "Sample camera world matrix over frame range and send to AI Studio"

    def execute(self, context):
        scene = context.scene
        project = getattr(scene, "aistudio_project", "")
        shot = getattr(scene, "aistudio_shot", "")

        if not project or project == "NONE":
            self.report({'ERROR'}, "Please select a valid project")
            return {'CANCELLED'}
        if not shot or shot == "NONE":
            self.report({'ERROR'}, "Please select a valid shot")
            return {'CANCELLED'}
        if not scene.camera:
            self.report({'ERROR'}, "Scene has no active camera")
            return {'CANCELLED'}

        client = get_client(context)

        fps = scene.render.fps / scene.render.fps_base if scene.render.fps_base else float(scene.render.fps)
        start = scene.frame_start
        end = scene.frame_end
        orig_frame = scene.frame_current

        samples = []
        lens_samples = []

        try:
            for f in range(start, end + 1):
                scene.frame_set(f)
                cam = scene.camera
                cam_data = cam.data
                mat = [[round(cam.matrix_world[row][col], 6) for col in range(4)] for row in range(4)]
                samples.append({"frame": f, "matrix": mat})
                lens_samples.append({
                    "frame": f,
                    "focal_length": round(cam_data.lens, 3),
                    "sensor_width": round(cam_data.sensor_width, 3),
                    "sensor_height": round(cam_data.sensor_height, 3),
                })
        finally:
            scene.frame_set(orig_frame)

        payload = {
            "samples": samples,
            "fps": round(fps, 3),
            "lens_samples": lens_samples,
        }

        try:
            client.send_camera_move(project, shot, payload)
            self.report({'INFO'}, f"Sent camera move for {shot} ({len(samples)} frames)")
        except AIStudioError as e:
            if "HTTP 404" in str(e):
                self.report(
                    {'WARNING'},
                    f"Sent camera move, but server route /camera-move is not yet implemented (see README): {e}",
                )
            else:
                self.report({'ERROR'}, f"Failed to send camera move: {e}")
                return {'CANCELLED'}

        return {'FINISHED'}


class AISTUDIO_OT_import_clips(Operator):
    """Download approved clips and add to Video Sequence Editor"""

    bl_idname = "aistudio.import_clips"
    bl_label = "Import Approved Clips"
    bl_description = "Download approved clips and arrange them sequentially in the VSE"

    def execute(self, context):
        scene = context.scene
        project = getattr(scene, "aistudio_project", "")

        if not project or project == "NONE":
            self.report({'ERROR'}, "Please select a valid project")
            return {'CANCELLED'}

        client = get_client(context)

        try:
            shots_doc = client.get_shots(project)
        except AIStudioError as e:
            self.report({'ERROR'}, f"Failed to get shots for project: {e}")
            return {'CANCELLED'}

        shots = shots_doc.get("shots", [])
        approved_shots = []
        for s in shots:
            is_approved = s.get("final_ok") or s.get("approved")
            clip_rel = s.get("final_clip") or s.get("clip")
            if is_approved or clip_rel:
                rel = clip_rel or f"clips/{s.get('id')}.mp4"
                approved_shots.append((s.get("id", "clip"), rel))

        if not approved_shots:
            self.report({'WARNING'}, "No approved clips found in this project")
            return {'CANCELLED'}

        if not scene.sequence_editor:
            scene.sequence_editor_create()
        seq = scene.sequence_editor

        temp_dir = Path(tempfile.gettempdir()) / "aistudio_clips" / project
        temp_dir.mkdir(parents=True, exist_ok=True)

        current_frame = scene.frame_start
        imported_count = 0

        for sid, rel in approved_shots:
            try:
                clip_bytes = client.download_file(project, rel)
                local_file = temp_dir / Path(rel).name
                local_file.write_bytes(clip_bytes)

                strip = seq.sequences.new_movie(
                    name=sid,
                    filepath=str(local_file),
                    channel=1,
                    frame_start=current_frame,
                )
                current_frame += strip.frame_final_duration
                imported_count += 1
            except Exception as e:
                self.report({'WARNING'}, f"Failed to import {rel}: {e}")

        if imported_count > 0:
            scene.frame_end = max(scene.frame_end, current_frame - 1)
            self.report({'INFO'}, f"Imported {imported_count} approved clip(s) into VSE")
            return {'FINISHED'}

        self.report({'ERROR'}, "Could not download or import any approved clips")
        return {'CANCELLED'}


class AISTUDIO_PT_panel(Panel):
    """N-Panel in 3D Viewport for AI Studio Bridge"""

    bl_label = "AI Studio"
    bl_idname = "VIEW3D_PT_aistudio"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "AI Studio"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Connection box
        box = layout.box()
        box.label(text="Connection", icon='PREFERENCES')
        box.prop(scene, "aistudio_server_url", text="URL")
        box.prop(scene, "aistudio_token", text="Token")
        box.operator("aistudio.pair", text="Pair", icon='LINKED')

        # Project & Shot selection
        box = layout.box()
        box.label(text="Project & Shot", icon='SCENE_DATA')
        row = box.row(align=True)
        row.prop(scene, "aistudio_project", text="Project")
        row.operator("aistudio.refresh_projects", text="", icon='FILE_REFRESH')

        row = box.row(align=True)
        row.prop(scene, "aistudio_shot", text="Shot")
        row.operator("aistudio.refresh_shots", text="", icon='FILE_REFRESH')

        # Previs Actions
        box = layout.box()
        box.label(text="Previs Actions", icon='CAMERA_DATA')

        col = box.column(align=True)
        op_first = col.operator("aistudio.send_frame", text="Send frame as first frame", icon='IMAGE_DATA')
        op_first.frame_type = "first_frame"

        op_end = col.operator("aistudio.send_frame", text="Send frame as end frame", icon='IMAGE_DATA')
        op_end.frame_type = "end_frame"

        box.operator("aistudio.send_camera_move", text="Send camera move", icon='ANIM_DATA')
        box.operator("aistudio.import_clips", text="Import approved clips", icon='SEQUENCE')


classes = (
    AIStudioPreferences,
    AISTUDIO_OT_pair,
    AISTUDIO_OT_refresh_projects,
    AISTUDIO_OT_refresh_shots,
    AISTUDIO_OT_send_frame,
    AISTUDIO_OT_send_camera_move,
    AISTUDIO_OT_import_clips,
    AISTUDIO_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.aistudio_server_url = StringProperty(
        name="Server URL",
        default="http://127.0.0.1:8765",
        description="Local AI Studio server URL",
    )
    bpy.types.Scene.aistudio_token = StringProperty(
        name="Session Token",
        default="",
        subtype='PASSWORD',
        description="Session token or API key for AI Studio",
    )
    bpy.types.Scene.aistudio_project = EnumProperty(
        name="Project",
        items=get_projects_items,
        update=on_project_update,
        description="Active AI Studio project",
    )
    bpy.types.Scene.aistudio_shot = EnumProperty(
        name="Shot",
        items=get_shots_items,
        description="Active shot within selected project",
    )


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.aistudio_server_url
    del bpy.types.Scene.aistudio_token
    del bpy.types.Scene.aistudio_project
    del bpy.types.Scene.aistudio_shot


if __name__ == "__main__":
    register()
