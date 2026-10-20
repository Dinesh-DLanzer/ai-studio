"""Bundled Blender Previs Rendering Script.

Executed inside Blender in background mode:
    blender -b project.blend -P blender_previs_script.py -- --out <out_dir> --shot <shot_id> ...

Features:
- Reads --out and --shot arguments from the CLI.
- For each shot ID, locates matching scene, timeline marker, or camera.
- Sets the scene frame and active camera.
- Renders the previs frame to the output path.
- Extracts camera metadata (focal length, sensor size, 4x4 world matrix).
- Emits structured JSON via stdout lines formatted as:
    AISTUDIO_JSON: {"shot": "...", "frame": "...", "camera": {...}}
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import bpy
except ImportError:
    bpy = None  # type: ignore[assignment]


def parse_cli_args() -> argparse.Namespace:
    """Extract and parse arguments passed after the '--' delimiter."""
    argv = sys.argv
    if "--" in argv:
        args_to_parse = argv[argv.index("--") + 1:]
    else:
        args_to_parse = []

    parser = argparse.ArgumentParser(description="AI Studio Blender Previs Renderer")
    parser.add_argument("--out", required=True, help="Destination directory for rendered frames")
    parser.add_argument(
        "--shot",
        action="append",
        dest="shots",
        default=[],
        help="Shot ID to render (can be specified multiple times)",
    )
    return parser.parse_args(args_to_parse)


def get_camera_metadata(camera_obj: Any) -> dict[str, Any]:
    """Extract lens, sensor, and world transform matrix from a Blender camera object."""
    if not camera_obj or not hasattr(camera_obj, "data"):
        return {
            "lens_mm": 50.0,
            "sensor_mm": 36.0,
            "matrix_world": None,
        }

    cam_data = camera_obj.data
    lens_mm = float(getattr(cam_data, "lens", 50.0))
    sensor_mm = float(getattr(cam_data, "sensor_width", 36.0))

    matrix_world = None
    if hasattr(camera_obj, "matrix_world"):
        # Convert Blender 4x4 matrix to standard nested list (row-major)
        matrix_world = [list(row) for row in camera_obj.matrix_world]

    return {
        "lens_mm": lens_mm,
        "sensor_mm": sensor_mm,
        "matrix_world": matrix_world,
    }


def find_target_for_shot(shot_id: str) -> tuple[Any, int, Any]:
    """Locate the scene, frame number, and camera object for a given shot ID.

    Lookup hierarchy:
    1. Scene with name == shot_id.
    2. Timeline marker named shot_id in current scene.
    3. Camera object named shot_id or shot_id + '_cam'.
    4. Fallback to active scene, current frame, and active camera.
    """
    # 1. Match scene by shot name
    target_scene = bpy.data.scenes.get(shot_id)
    if not target_scene:
        target_scene = bpy.context.scene

    target_frame = target_scene.frame_current
    target_cam = target_scene.camera

    # 2. Check for matching timeline marker in the scene
    for marker in target_scene.timeline_markers:
        if marker.name.strip() == shot_id.strip():
            target_frame = marker.frame
            if marker.camera:
                target_cam = marker.camera
            break

    # 3. Check for specific camera object named for this shot
    candidate_cam_names = [shot_id, f"{shot_id}_cam", f"Camera_{shot_id}"]
    for cname in candidate_cam_names:
        cam_obj = bpy.data.objects.get(cname)
        if cam_obj and cam_obj.type == "CAMERA":
            target_cam = cam_obj
            break

    return target_scene, target_frame, target_cam


def render_shot(shot_id: str, out_dir: str) -> dict[str, Any]:
    """Configure render settings and render a still frame for the specified shot."""
    scene, frame, cam = find_target_for_shot(shot_id)

    # Set active camera and frame
    if cam:
        scene.camera = cam
    scene.frame_set(frame)

    # Ensure output format is PNG
    scene.render.image_settings.file_format = "PNG"

    # Set destination file path
    out_filename = f"{shot_id}.png"
    out_filepath = os.path.abspath(os.path.join(out_dir, out_filename))
    scene.render.filepath = out_filepath

    # Render frame to disk
    bpy.ops.render.render(write_still=True, scene=scene.name)

    # Collect metadata
    cam_meta = get_camera_metadata(scene.camera)

    return {
        "shot": shot_id,
        "frame": out_filepath,
        "frame_number": frame,
        "camera": cam_meta,
    }


def main() -> None:
    if bpy is None:
        print(
            "Error: This script must be run inside Blender background mode (-b).",
            file=sys.stderr,
        )
        sys.exit(1)

    args = parse_cli_args()
    os.makedirs(args.out, exist_ok=True)

    if not args.shots:
        print("Warning: No shots specified with --shot", file=sys.stderr)
        return

    for shot_id in args.shots:
        try:
            shot_result = render_shot(shot_id, args.out)
            # Emit structured JSON prefixed with AISTUDIO_JSON: for host capture
            print(f"AISTUDIO_JSON: {json.dumps(shot_result)}", flush=True)
        except Exception as exc:
            err_payload = {
                "shot": shot_id,
                "error": str(exc),
            }
            print(f"AISTUDIO_JSON: {json.dumps(err_payload)}", flush=True)


if __name__ == "__main__":
    main()
