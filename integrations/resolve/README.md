# AI Studio for DaVinci Resolve

This script opens a small Resolve window, connects to AI Studio with a server URL and API token, lists projects, and imports the selected project's timeline. Save `AI Studio.py` in the Resolve Scripts `Utility` folder, then launch it from **Workspace > Scripts > Utility > AI Studio**.

## Install locations

- macOS: `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility`
- Windows: `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility`
- Linux: `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility`

Restart Resolve after installing the script if it does not appear in the Scripts menu. Use an AI Studio API token with project read access. The script uses HTTP requests with an eight-second timeout and does not invoke a shell.

## Export and fallback routes

The server provides both timeline exports and the approved media listing:

- `GET /api/projects/{name}/export/otioz` (or `/otio`): Implemented in `server/app.py`. Returns OpenTimelineIO timeline exports.
- `GET /api/projects/{name}/media?approved=1`: Implemented in `server/app.py`. Returns an ordered JSON list under `media`; each entry includes `name`, `kind`, `size`, `sha`, `path`, `src`, and `download_path`/`url`.

When importing, the script downloads `.otioz` first and `.otio` second, then passes the file to Resolve's `MediaPool.ImportTimelineFromFile`. If that call fails or the route is unavailable, it calls `MediaPool.ImportMedia` and then `MediaPool.AppendToTimeline` using the media endpoint's order. Device pairing tokens (`aisd_...`) via `POST /api/pair/confirm` are supported for authentication.

## Verification limits

This package was syntax-checked and its imports were checked to use only Python's standard library. It was not run inside DaVinci Resolve or against a live AI Studio server. The following Resolve scripting API calls could not be verified in a running host: `bmd.scriptapp("Resolve")`, `bmd.scriptapp("Fusion")`, `fusion.UIManager`, `bmd.UIDispatcher`, the UIManager window/event methods, `GetProjectManager().GetCurrentProject().GetMediaPool()`, `MediaPool.ImportTimelineFromFile`, `MediaPool.ImportMedia`, and `MediaPool.AppendToTimeline`. Resolve API behavior may vary by installed version and edition.
