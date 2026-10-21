# AI Studio Premiere Pro UXP Panel

A native Adobe Premiere Pro panel built on the Unified Extensible Platform (UXP Manifest v5) enabling video editors to browse AI Studio projects, inspect approved media (clips, stills, voiceovers), download assets into local cache storage, import them directly into the active project bin, and assemble rough cut sequences on the timeline.

---

## 1. Installation

### Option A: Development / Sideload via UXP Developer Tool (UDT)

1. **Install Adobe UXP Developer Tool:** Download and install the UXP Developer Tool (UDT) from the Adobe Creative Cloud desktop app.
2. **Launch UDT:** Open the UXP Developer Tool on your workstation.
3. **Add Plugin:**
   - Click **Add Plugin** in the top-right corner.
   - Navigate to this repository and select `integrations/premiere-uxp/manifest.json`.
4. **Select Host Application:**
   - Under the plugin entry, ensure the host application is set to **Adobe Premiere Pro** (v25.2.0 or newer).
5. **Load Panel:**
   - Launch Adobe Premiere Pro.
   - In UDT, click the **•••** menu next to the "AI Studio" entry and click **Load** (or **Debug** to open Chrome DevTools for the panel).
6. **Open Panel in Premiere Pro:**
   - In Premiere Pro, choose **Window > Extensions > AI Studio** or **Window > Panels > AI Studio**.

### Option B: Production Package as `.ccx`

1. **Package using UXP Developer Tool:**
   - In UDT, select the "AI Studio" plugin.
   - Click **Package...**
   - Choose a target destination (e.g. `dist/aistudio-premiere-1.0.0.ccx`).
   - UDT signs and bundles the manifest, HTML, JavaScript, CSS, and icons into a `.ccx` archive.
2. **Double-Click Install:**
   - Double-click the resulting `.ccx` file.
   - Creative Cloud Desktop will prompt to install the plugin for Premiere Pro.
   - Restart Premiere Pro, then open the panel from **Window > Extensions > AI Studio**.

---

## 2. Minimum Premiere Version

| Host / Feature | Minimum Version | Verification Status | Notes |
| :--- | :--- | :--- | :--- |
| **UXP Manifest v5** | `24.0+` (Premiere Pro 2024) | **Verified** in UXP schema docs | Standard manifest v5 schema support. |
| **UXP DOM (`require("premierepro")`)** | `25.2.0+` (Premiere Pro 2025) | **Verified** in Adobe UXP release notes | DOM API migration from ExtendScript to async JavaScript. |
| **File Import (`activeProject.importFiles`)** | `25.2.0+` | **Verified** in Adobe UXP API references | Asynchronous `Promise<boolean>` import. |
| **Sequence Creation (`createSequenceFromMedia`)** | `25.6.0+` | **Verified** in Adobe UXP 25.6 specs | Automated sequence construction from media items. |
| **Overall Recommended Host** | **Premiere Pro 25.6.0+** | **Partially Verified** | `minVersion` is set to `25.2.0` in `manifest.json` with runtime feature detection and fallback to interchange export (`.otio`/`.xml`). |

---

## 3. Security Notes

* **Strict Local Loopback Network Boundary:**
  - Network access in `manifest.json` is explicitly constrained under `requiredPermissions.network.domains` to:
    - `http://127.0.0.1:8765`
    - `http://localhost:8765`
  - No remote external domains, wildcard domains, or `"all"` permissions are granted.
  - The client runtime code strictly validates input URLs via `validateLocalUrl()` before issuing `fetch()` requests, preventing Server-Side Request Forgery (SSRF) or accidental credential leakage.
* **Token Storage:**
  - The session token is saved in UXP's encrypted `secureStorage` (`require("uxp").storage.secureStorage`) when available on disk.
  - If running in an environment where `secureStorage` is missing, the panel falls back to `localStorage` and displays a visible security warning banner to notify the user.
* **No Dynamic Execution:**
  - The panel contains no `eval()`, no `new Function()`, no string code execution in timers, and no dynamic remote `<script>` injection. All HTML, script, and style resources are strictly loaded from local disk packages.

---

## 4. Needed Server Routes

The panel communicates with the local AI Studio FastAPI server (`server/app.py`). The required server routes for NLE panel integration are implemented as follows:

1. **`GET /api/projects/{name}/media?approved=1`**
   - **Status:** **Implemented** in `server/app.py`.
   - **Access:** Human session or paired device token.
   - **Purpose:** Returns a curated, structured list of all approved media assets (clips, stills, audio) with shot IDs, sequence ordering, file sizes, SHA-256 hashes, and download paths.

2. **`GET /api/projects/{name}/export/{fmt}`**
   - **Status:** **Implemented** in `server/app.py`.
   - **Access:** Human session or paired device token.
   - **Purpose:** Delivers timeline interchange files (`.otio`, `.otioz`, `.xmeml`, `.fcpxml`, `.edl`, `.srt`, `.vtt`, `.bundle`, and `aftereffects.jsx`) for sequence creation and fallbacks.

3. **`POST /api/pair/start` & `POST /api/pair/confirm`**
   - **Status:** **Implemented** in `server/app.py`.
   - **Purpose:** Initiates 6-digit device pairing code generation (shown in notifications/stderr, never in API responses) and exchanges it for a scoped 30-day device token (`aisd_...`).
   - **Scope:** Device tokens are allowed on bridge read routes and proposal creation (`POST clips/{id}/tool`, `POST proposals`). For security, approvals must be completed by a human in the AI Studio web interface.

4. **`GET /api/jobs`**
   - **Status:** **Implemented** in `server/app.py`.
   - **Purpose:** Lists active background rendering and export jobs for the Jobs tab.

---

## 5. UNVERIFIED APIs

Because Adobe Premiere Pro cannot be executed within a headless CLI/CI environment, the following Premiere Pro UXP API behaviors are based on Adobe Developer Documentation and community specs, but remain **unverified in a live Premiere runtime**:

1. **`activeProject.createSequenceFromMedia(name, clipItems, targetBin)`**
   - *Status:* **UNVERIFIED in live execution.**
   - *Details:* Introduced in Premiere Pro 25.6. Exact return type (`Sequence` object vs boolean), behavior when mixing video clips and image stills in `clipItems`, and requirement for bin hierarchy require validation on physical Premiere Pro 25.6+ installs. Wrapped in runtime feature detection with automatic fallback to interchange import.
2. **`ClipProjectItem` resolution after `activeProject.importFiles`**
   - *Status:* **UNVERIFIED in live execution.**
   - *Details:* The official specification indicates `importFiles` returns a `Promise<boolean>`. Locating newly imported items via `findItemsMatchingMediaPath()` or iterating `rootItem.children` can vary between Premiere minor releases.
3. **Interchange File Ingestion via `importFiles`**
   - *Status:* **UNVERIFIED in live execution.**
   - *Details:* While importing Final Cut Pro XML (`.xml`) via `importFiles` historically creates a new sequence bin in Premiere ExtendScript, the exact behavior of OpenTimelineIO (`.otio`) direct import via UXP `importFiles` requires testing against Premiere Pro 25.x release builds.
4. **UXP `secureStorage` availability across OS variants**
   - *Status:* **UNVERIFIED in live execution.**
   - *Details:* `secureStorage` is documented in UXP 7.0+, but host compatibility on Windows vs macOS for Premiere Pro specifically needs verification. The panel safely feature-detects it and falls back to `localStorage` with a warning.
