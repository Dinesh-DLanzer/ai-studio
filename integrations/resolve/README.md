# AI Studio for DaVinci Resolve

This script opens a small Resolve window, connects to AI Studio with a server URL and API token, lists projects, and imports the selected project's timeline. Save `AI Studio.py` in the Resolve Scripts `Utility` folder, then launch it from **Workspace > Scripts > Utility > AI Studio**.

## Install locations

- macOS: `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility`
- Windows: `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility`
- Linux: `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility`

Restart Resolve after installing the script if it does not appear in the Scripts menu. Use an AI Studio API token with project read access. The script uses HTTP requests with an eight-second timeout and does not invoke a shell.

## Export and fallback routes

The current server has no OTIO export route or approved-media listing route. The script expects these routes:

- `GET /api/projects/{name}/export/otioz` (or `/otio`) to return an OTIO timeline export.
- `GET /api/projects/{name}/media?approved=1` to return an ordered JSON list under `media`; each entry needs a local `path`/`src` or a downloadable `url`.

Once the timeline export route exists, the script downloads `.otioz` first and `.otio` second, then passes the file to Resolve's `MediaPool.ImportTimelineFromFile`. If that call fails or the route is unavailable, it calls `MediaPool.ImportMedia` and then `MediaPool.AppendToTimeline` using the media endpoint's order. Those fallback clips are appended in order, but their edit in/out points are not represented by the media-list contract above.

## Verification limits

This package was syntax-checked and its imports were checked to use only Python's standard library. It was not run inside DaVinci Resolve or against a live AI Studio server. The following Resolve scripting API calls could not be verified in a running host: `bmd.scriptapp("Resolve")`, `bmd.scriptapp("Fusion")`, `fusion.UIManager`, `bmd.UIDispatcher`, the UIManager window/event methods, `GetProjectManager().GetCurrentProject().GetMediaPool()`, `MediaPool.ImportTimelineFromFile`, `MediaPool.ImportMedia`, and `MediaPool.AppendToTimeline`. Resolve API behavior may vary by installed version and edition.
