# AI Studio Bridge for Blender

A Blender 4.2+ extension that connects Blender 3D previs, camera staging, and animatics with AI Studio.

---

## 1. Overview

AI Studio Bridge allows artists, directors, and layout artists to:
- **Block shots in 3D:** Set up framing, cameras, mannequins, and timing directly inside Blender.
- **Send stills:** Render the active camera at the project's exact aspect ratio and upload directly as a shot's **first frame** or **end frame**.
- **Send camera moves:** Export sampled camera world matrices and lens parameters for server-side classification (dolly, truck, orbit, pan, tilt, zoom) into structured direction.
- **Import approved clips:** Download final approved video clips from AI Studio directly into Blender's Video Sequence Editor (VSE) in shot order.

---

## 2. Installation

### Extension Packaging (Blender 4.2 LTS+)

1. Create a zip archive containing the extension directory:
   ```bash
   cd integrations/blender
   zip -r aistudio_bridge.zip aistudio_bridge/
   ```

2. Inside Blender 4.2+:
   - Open **Edit** > **Preferences** > **Add-ons** (or **Get Extensions**).
   - In the top-right corner dropdown menu (arrow next to Repositories), choose **Install from Disk...**.
   - Select `aistudio_bridge.zip` (or the `aistudio_bridge` directory directly).
   - Enable **AI Studio Bridge**.

---

## 3. Usage

### N-Panel Location
In Blender's **3D Viewport**, press <kbd>N</kbd> to toggle the sidebar, and click on the **AI Studio** tab.

### Pairing
1. **Server URL:** Defaults to `http://127.0.0.1:8765`.
2. **Token:** Enter your AI Studio session token, API key, or paired device token (`x-aistudio-token`, `Authorization: Bearer <token>`). Paired device tokens can be generated via `POST /api/pair/confirm` with `host: "blender"`.
3. Click **Pair**. The extension connects to the server and populates the **Project** and **Shot** dropdowns.

### Workflow
1. **Select Project and Shot:** Choose your active project and shot from the dropdowns. Use the refresh icons if changes were made on the web interface.
2. **Send Frame as First Frame / End Frame:**
   - Frame your shot with the active camera (`Ctrl + Numpad 0`).
   - Click **Send frame as first frame** or **Send frame as end frame**.
   - The extension queries the project aspect ratio (e.g. `9:16`, `16:9`), renders the active camera still to a temporary PNG via `bpy.ops.render.render(write_still=True)`, uploads it to `POST /api/projects/{name}/upload?rel=stills/<shot>-blender-<n>.png&replace=1`, and links it in the project's `shots.json` via `PUT /api/projects/{name}/shots`.
3. **Send Camera Move:**
   - Keyframe or animate camera motion over the scene frame range (`frame_start` to `frame_end`).
   - Click **Send camera move**.
   - The extension samples `matrix_world`, focal length, and sensor dimensions frame-by-frame and POSTs the sample data to `/api/projects/{name}/shots/{shot}/camera-move`.
   - The server classifies the move and answers with the proposed `direction`. **Nothing is saved yet**: a human applies it
     with `POST /api/projects/{name}/shots/{shot}/direction` (or in the web UI), so a mis-read move never changes a shot.
4. **Import Approved Clips:**
   - Click **Import approved clips**.
   - The extension downloads all completed and approved video clips (`clips/<shot>_final_*.mp4`) and arranges them consecutively on Channel 1 of the Blender Video Sequence Editor (VSE).

---

## 4. Security Notes

- **Localhost Loopback:** Designed strictly for communication with local AI Studio server instances (`http://127.0.0.1:8765`).
- **Token Protection:** The authentication token is stored in password-masked properties (`subtype='PASSWORD'`) and sent via HTTP headers (`x-aistudio-token`, `Authorization: Bearer`). It is never stored in public scene assets or logs.
- **Declared Extension Permissions:** Declared in `blender_manifest.toml`:
  - `network`: `"talk to the local AI Studio server"`
  - `files`: `"save rendered frames temporarily"`
- **Safe Execution:** No shell commands or subshells (`shell=True`, `os.system`) are used. All network operations use Python's standard `urllib` library with strict timeouts and error handling.

---

## 5. Needed Server Routes

The following endpoints support blender integration:

1. **`GET /api/projects/{name}/media?approved=1`**
   - **Status:** **Implemented** in `server/app.py`.
   - **Purpose:** Delivers approved clips, stills, and audio assets with resolved download paths.

2. **`POST /api/pair/confirm` & Device Tokens**
   - **Status:** **Implemented** in `server/app.py`.
   - **Purpose:** Supports `host: "blender"` for issuing 30-day paired device tokens.

3. **`POST /api/projects/{name}/shots/{shot}/camera-move`**
   - **Status:** **Implemented** in `server/app.py` (a human session **or a paired device token**; an API key is refused).
   - **Payload format:**
     ```json
     {
       "samples": [
         {
           "frame": 1,
           "matrix": [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
         }
       ],
       "fps": 24.0,
       "lens_samples": [
         {
           "frame": 1,
           "focal_length": 50.0,
           "sensor_width": 36.0,
           "sensor_height": 24.0
         }
       ],
       "target": [0.0, 0.0, 0.0]
     }
     ```
     `samples` may also be a plain list of 4x4 matrices, and `lens_samples` a plain list of focal lengths in mm.
     `target` (the point the camera orbits) is optional.
   - **Limits:** at most 2000 samples, every number must be finite (NaN and infinity are refused), `fps` must be between 0 and 1000.
   - **Server behavior:** the samples go to `storyboard/camera_classify.py`, which classifies the motion (e.g. dolly-in, orbit, pan, tilt, zoom).
   - **Answer:** `{"shot": "s01", "classification": {"movement", "speed", "confidence", "evidence"}, "direction": {...}, "saved": false}`.
     The classification and the proposed `direction` are **only a proposal**: nothing is written to the project.

4. **`POST /api/projects/{name}/shots/{shot}/direction`**
   - **Status:** **Implemented** in `server/app.py` (**human session only**: a device token may look, not write).
   - **Payload format:** `{"direction": {"movement": "dolly-in", "speed": "normal"}, "replace": false}`.
     The direction may also be sent as the body itself (`{"movement": "dolly-in"}`).
   - **Server behavior:** validates the direction against the direction schema (movement, framing, angle, lens_mm, ...),
     merges it into the shot's direction (or replaces it with `"replace": true`) and saves it through the validated
     shots path, so the previous version stays in the document history. Unknown keys are kept.
   - **Answer:** `{"shot": "s01", "direction": {...}}`.

5. **`POST /api/projects/{name}/previs/render`**
   - **Status:** **Implemented** in `server/app.py` (**human session only**).
   - **Payload format:** `{"blend": "scenes/main.blend", "shots": ["s01", "s02"]}`.
     The `.blend` file must be a path **inside the project** (no absolute paths, no `..`).
   - **Server behavior:** runs headless Blender as a free local ledger job (`kind: "previs"`, no provider, no cost) and
     writes the frames into the project's `previs/` folder.
   - **Answer:** `{"job": "<id>"}`; poll `GET /api/jobs/{id}`.

6. **`GET /api/projects/{name}/previs`**
   - **Status:** **Implemented** in `server/app.py` (**human session only**).
   - **Purpose:** lists the frames in `previs/` (`file`, `shot`, `bytes`, `registered`).
     The frames are **not** registered as stills: a human still uploads them through the normal upload path.

7. **`GET /api/projects/{name}/shots`**
   - **Status:** Recommended convenience route. Currently shots can be retrieved via `GET /api/projects/{name}` overview.

---

## 6. What is Untested

- **Headless test constraints:** Unit tests in `tests/test_blender_addon_package.py` execute in pure Python without requiring Blender or the `bpy` C-extension library.
- **Live Blender Runtime:** Execution inside a live Blender GUI session (such as OpenGL/Eevee rendering and VSE timeline manipulation) requires a Blender installation and was not run in CI/headless unit tests.
- **Previs rendering:** the server route is covered by `tests/test_blender_routes.py` with a mocked engine, so the real
  `blender -b file.blend -P ...` round trip was not run here. Set the Blender path in `settings/blender.json`
  (`{"binary": "/Applications/Blender.app/Contents/MacOS/Blender"}`) if it is not on the PATH.

