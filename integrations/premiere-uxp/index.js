/**
 * AI Studio UXP Panel for Adobe Premiere Pro
 *
 * Provides connection to local AI Studio server, project/media browsing,
 * and direct import/sequence generation inside Premiere Pro.
 */

// UXP and Host modules (resolved at runtime inside Adobe UXP environment)
let uxp = null;
let uxpStorage = null;
let premiereApp = null;

try {
  if (typeof require === "function") {
    uxp = require("uxp");
    uxpStorage = uxp ? uxp.storage : null;
    premiereApp = require("premierepro");
  }
} catch (e) {
  console.log("UXP or Premiere modules not found in current environment:", e.message);
}

// Register UXP panel entrypoint if available
try {
  if (uxp && uxp.entrypoints) {
    uxp.entrypoints.setup({
      panels: {
        aiStudioPanel: {
          show() {
            console.log("AI Studio UXP Panel mounted");
          },
          hide() {
            console.log("AI Studio UXP Panel hidden");
          }
        }
      }
    });
  }
} catch (e) {
  console.log("UXP entrypoints setup skipped:", e.message);
}

// State
const state = {
  serverUrl: "http://127.0.0.1:8765",
  token: "",
  projects: [],
  selectedProject: "",
  mediaItems: [],
  selectedMediaIds: new Set(),
  storageType: "unknown" // "secure" | "localStorage" | "none"
};

// DOM Elements
const elements = {
  serverUrl: document.getElementById("server-url"),
  token: document.getElementById("token"),
  btnConnect: document.getElementById("btn-connect"),
  btnRefresh: document.getElementById("btn-refresh"),
  btnSelectAll: document.getElementById("btn-select-all"),
  projectSelect: document.getElementById("project-select"),
  mediaList: document.getElementById("media-list"),
  btnImportBin: document.getElementById("btn-import-bin"),
  btnCreateSequence: document.getElementById("btn-create-sequence"),
  statusDot: document.getElementById("status-dot"),
  statusText: document.getElementById("status-text"),
  storageWarning: document.getElementById("storage-warning"),
  statusLog: document.getElementById("status-log")
};

// Security: Validate only local loopback URLs
function validateLocalUrl(urlString) {
  try {
    const parsed = new URL(urlString);
    const host = parsed.hostname;
    if (host !== "127.0.0.1" && host !== "localhost") {
      return false;
    }
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return false;
    }
    return true;
  } catch (err) {
    return false;
  }
}

// Logger helper
function logStatus(message, type = "info") {
  if (!elements.statusLog) return;
  elements.statusLog.textContent = message;
  elements.statusLog.className = `status-log ${type}`;
  console.log(`[AI Studio] ${message}`);
}

// Storage helpers: Token in UXP secureStorage with localStorage fallback
async function loadStoredToken() {
  if (uxpStorage && uxpStorage.secureStorage) {
    try {
      const buffer = await uxpStorage.secureStorage.getItem("aistudio_token");
      if (buffer) {
        state.storageType = "secure";
        setWarningVisible(false);
        return new TextDecoder().decode(buffer);
      }
    } catch (e) {
      console.warn("Failed to read from secureStorage:", e);
    }
  }

  // Fallback to window.localStorage
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      const localToken = window.localStorage.getItem("aistudio_token");
      if (localToken) {
        state.storageType = "localStorage";
        setWarningVisible(true);
        return localToken;
      }
    }
  } catch (e) {
    console.warn("localStorage read failed:", e);
  }

  state.storageType = "none";
  setWarningVisible(false);
  return "";
}

async function persistToken(token) {
  state.token = token;
  if (!token) return;

  if (uxpStorage && uxpStorage.secureStorage) {
    try {
      await uxpStorage.secureStorage.setItem("aistudio_token", token);
      state.storageType = "secure";
      setWarningVisible(false);
      return;
    } catch (e) {
      console.warn("secureStorage write failed, falling back to localStorage:", e);
    }
  }

  // Fallback to localStorage
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      window.localStorage.setItem("aistudio_token", token);
      state.storageType = "localStorage";
      setWarningVisible(true);
    }
  } catch (e) {
    console.warn("localStorage write failed:", e);
  }
}

function setWarningVisible(visible) {
  if (elements.storageWarning) {
    if (visible) {
      elements.storageWarning.classList.add("visible");
    } else {
      elements.storageWarning.classList.remove("visible");
    }
  }
}

function setConnectionState(connected, message) {
  if (elements.statusDot) {
    elements.statusDot.className = `status-dot ${connected ? "connected" : "error"}`;
  }
  if (elements.statusText) {
    elements.statusText.textContent = message;
  }
  elements.projectSelect.disabled = !connected;
  elements.btnRefresh.disabled = !connected;
}

// UXP Cache Folder access
async function getCacheFolder() {
  if (uxpStorage && uxpStorage.localFileSystem) {
    try {
      if (typeof uxpStorage.localFileSystem.getTemporaryFolder === "function") {
        return await uxpStorage.localFileSystem.getTemporaryFolder();
      }
      if (typeof uxpStorage.localFileSystem.getDataFolder === "function") {
        return await uxpStorage.localFileSystem.getDataFolder();
      }
    } catch (e) {
      console.error("Error accessing UXP cache folder:", e);
    }
  }
  return null;
}

// API: Connect & Fetch Projects
async function connectServer() {
  const url = elements.serverUrl.value.trim().replace(/\/+$/, "");
  const token = elements.token.value.trim();

  if (!validateLocalUrl(url)) {
    logStatus("Security error: Server URL must point to localhost (127.0.0.1 or localhost).", "error");
    setConnectionState(false, "Invalid URL");
    return;
  }

  state.serverUrl = url;
  state.token = token;
  await persistToken(token);

  logStatus("Connecting to AI Studio server...", "info");

  try {
    const headers = {
      "Accept": "application/json"
    };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
      headers["X-aistudio-token"] = token;
    }

    const response = await fetch(`${state.serverUrl}/api/projects`, {
      method: "GET",
      headers
    });

    if (!response.ok) {
      throw new Error(`Server returned HTTP ${response.status} (${response.statusText})`);
    }

    const data = await response.json();
    const projectsList = Array.isArray(data) ? data : (data.projects || []);

    state.projects = projectsList;
    setConnectionState(true, "Connected");
    logStatus(`Connected. Found ${projectsList.length} projects.`, "info");

    renderProjectOptions();
  } catch (err) {
    setConnectionState(false, "Failed");
    logStatus(`Connection failed: ${err.message}`, "error");
  }
}

function renderProjectOptions() {
  elements.projectSelect.innerHTML = '<option value="">Select a project...</option>';
  state.projects.forEach((proj) => {
    const name = typeof proj === "string" ? proj : proj.name;
    if (name) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      elements.projectSelect.appendChild(opt);
    }
  });

  if (state.projects.length > 0) {
    elements.projectSelect.selectedIndex = 1;
    onProjectChanged();
  }
}

// API: Fetch Approved Media for Selected Project
async function loadProjectMedia(projectName) {
  if (!projectName) {
    state.mediaItems = [];
    state.selectedMediaIds.clear();
    renderMediaList();
    return;
  }

  logStatus(`Loading media for project "${projectName}"...`, "info");

  const headers = {
    "Accept": "application/json"
  };
  if (state.token) {
    headers["Authorization"] = `Bearer ${state.token}`;
    headers["X-aistudio-token"] = state.token;
  }

  let items = [];

  // Try dedicated endpoint: GET /api/projects/{name}/media?approved=1
  try {
    const res = await fetch(`${state.serverUrl}/api/projects/${encodeURIComponent(projectName)}/media?approved=1`, {
      method: "GET",
      headers
    });

    if (res.ok) {
      const data = await res.json();
      items = Array.isArray(data) ? data : (data.media || []);
    } else if (res.status === 404) {
      // Fallback: fetch project overview
      items = await loadMediaFromOverview(projectName, headers);
    } else {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }
  } catch (err) {
    console.warn("Primary media endpoint failed, attempting overview fallback:", err.message);
    try {
      items = await loadMediaFromOverview(projectName, headers);
    } catch (fallbackErr) {
      logStatus(`Failed to load media: ${fallbackErr.message}`, "error");
      return;
    }
  }

  state.mediaItems = items;
  state.selectedMediaIds.clear();
  // Default to selecting all approved items
  items.forEach((item) => state.selectedMediaIds.add(item.id));

  renderMediaList();
  logStatus(`Loaded ${items.length} approved media item(s).`, "info");
}

// Fallback media extraction from overview
async function loadMediaFromOverview(projectName, headers) {
  const res = await fetch(`${state.serverUrl}/api/projects/${encodeURIComponent(projectName)}`, {
    method: "GET",
    headers
  });

  if (!res.ok) {
    throw new Error(`Overview returned HTTP ${res.status}`);
  }

  const overview = await res.json();
  const items = [];
  let shotIndex = 1;

  // Process shots
  const shotList = overview.shots?.shots || [];
  shotList.forEach((shot) => {
    const sid = shot.id || `shot_${shotIndex}`;
    const shotNum = shot.shot || shotIndex;

    // Check for approved clip
    if (shot.clip) {
      const clipFile = typeof shot.clip === "string" ? shot.clip : shot.clip.filename || `${sid}.mp4`;
      items.push({
        id: `clip_${sid}`,
        name: `Shot ${shotNum} - Clip (${clipFile})`,
        type: "clip",
        approved: true,
        shotOrder: shotNum,
        relPath: `clips/${clipFile}`,
        filename: clipFile
      });
    }

    // Check for approved still
    if (shot.still || shot.approved_still) {
      const stillFile = typeof shot.still === "string" ? shot.still : (shot.approved_still || `${sid}.png`);
      items.push({
        id: `still_${sid}`,
        name: `Shot ${shotNum} - Still (${stillFile})`,
        type: "still",
        approved: true,
        shotOrder: shotNum,
        relPath: `stills/${stillFile}`,
        filename: stillFile
      });
    }

    shotIndex++;
  });

  // Process files listing if shots were empty
  if (items.length === 0 && overview.files) {
    const clips = overview.files.clips || [];
    clips.forEach((clip, idx) => {
      items.push({
        id: `clip_file_${idx}`,
        name: clip,
        type: "clip",
        approved: true,
        shotOrder: idx + 1,
        relPath: `clips/${clip}`,
        filename: clip
      });
    });

    const stills = overview.files.stills || [];
    stills.forEach((still, idx) => {
      items.push({
        id: `still_file_${idx}`,
        name: still,
        type: "still",
        approved: true,
        shotOrder: idx + 1,
        relPath: `stills/${still}`,
        filename: still
      });
    });
  }

  return items;
}

function renderMediaList() {
  const container = elements.mediaList;
  container.innerHTML = "";

  if (state.mediaItems.length === 0) {
    container.innerHTML = '<li class="empty-state">No approved media found in this project.</li>';
    elements.btnImportBin.disabled = true;
    elements.btnCreateSequence.disabled = true;
    elements.btnSelectAll.disabled = true;
    return;
  }

  elements.btnImportBin.disabled = false;
  elements.btnCreateSequence.disabled = false;
  elements.btnSelectAll.disabled = false;

  state.mediaItems.forEach((item) => {
    const li = document.createElement("li");
    li.className = "media-item";

    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.className = "media-checkbox";
    chk.checked = state.selectedMediaIds.has(item.id);
    chk.dataset.id = item.id;
    chk.addEventListener("change", (e) => {
      if (e.target.checked) {
        state.selectedMediaIds.add(item.id);
      } else {
        state.selectedMediaIds.delete(item.id);
      }
      elements.btnImportBin.disabled = state.selectedMediaIds.size === 0;
      elements.btnCreateSequence.disabled = state.selectedMediaIds.size === 0;
    });

    const thumb = document.createElement("div");
    thumb.className = "media-thumb";
    thumb.textContent = item.type.toUpperCase();

    const details = document.createElement("div");
    details.className = "media-details";

    const nameDiv = document.createElement("div");
    nameDiv.className = "media-name";
    nameDiv.textContent = item.name;

    const metaDiv = document.createElement("div");
    metaDiv.className = "media-meta";

    const typeBadge = document.createElement("span");
    typeBadge.className = `badge badge-${item.type}`;
    typeBadge.textContent = item.type;

    const appBadge = document.createElement("span");
    appBadge.className = "badge badge-approved";
    appBadge.textContent = "approved";

    metaDiv.appendChild(typeBadge);
    metaDiv.appendChild(appBadge);
    details.appendChild(nameDiv);
    details.appendChild(metaDiv);

    li.appendChild(chk);
    li.appendChild(thumb);
    li.appendChild(details);

    container.appendChild(li);
  });
}

// Download file into UXP local file system cache
async function downloadFileToCache(relPath, filename) {
  const cacheFolder = await getCacheFolder();
  if (!cacheFolder) {
    throw new Error("UXP localFileSystem is unavailable. Cannot create cached media file.");
  }

  const downloadUrl = `${state.serverUrl}/files/${encodeURIComponent(state.selectedProject)}/${relPath}`;
  const headers = {};
  if (state.token) {
    headers["Authorization"] = `Bearer ${state.token}`;
    headers["X-aistudio-token"] = state.token;
  }

  const res = await fetch(downloadUrl, { method: "GET", headers });
  if (!res.ok) {
    throw new Error(`Failed to download ${relPath}: HTTP ${res.status}`);
  }

  const buffer = await res.arrayBuffer();
  const file = await cacheFolder.createFile(filename, { overwrite: true });

  const writeOptions = (uxpStorage && uxpStorage.formats && uxpStorage.formats.binary)
    ? { format: uxpStorage.formats.binary }
    : {};

  await file.write(buffer, writeOptions);
  return file;
}

// Action: Import to Bin
async function importToBin() {
  const selectedItems = state.mediaItems.filter((i) => state.selectedMediaIds.has(i.id));
  if (selectedItems.length === 0) {
    logStatus("No media items selected to import.", "info");
    return;
  }

  // Feature detection: Premiere Pro module
  if (!premiereApp) {
    logStatus("Feature unavailable: Premiere Pro API (require('premierepro')) is not available.", "error");
    return;
  }

  const getProj = premiereApp.Project?.getActiveProject || premiereApp.project?.getActiveProject;
  if (typeof getProj !== "function") {
    logStatus("Feature unavailable: getActiveProject() is not supported in this host version.", "error");
    return;
  }

  let activeProject = null;
  try {
    activeProject = await getProj();
  } catch (err) {
    logStatus(`Could not get active Premiere project: ${err.message}`, "error");
    return;
  }

  if (!activeProject) {
    logStatus("No active Premiere Pro project is open. Please open a project first.", "error");
    return;
  }

  if (typeof activeProject.importFiles !== "function") {
    logStatus("Feature unavailable: activeProject.importFiles() is not supported.", "error");
    return;
  }

  logStatus(`Downloading ${selectedItems.length} file(s) to cache folder...`, "info");

  const downloadedFiles = [];
  for (const item of selectedItems) {
    try {
      const file = await downloadFileToCache(item.relPath, item.filename);
      downloadedFiles.push(file);
      logStatus(`Downloaded: ${item.filename}`, "info");
    } catch (err) {
      logStatus(`Download error for ${item.filename}: ${err.message}`, "error");
    }
  }

  if (downloadedFiles.length === 0) {
    logStatus("Import aborted: no files were successfully downloaded.", "error");
    return;
  }

  // Get target bin
  let targetBin = null;
  try {
    if (typeof activeProject.getRootItem === "function") {
      targetBin = await activeProject.getRootItem();
    } else if (activeProject.rootItem) {
      targetBin = activeProject.rootItem;
    }
  } catch (e) {
    console.warn("Could not retrieve target bin:", e);
  }

  const filePaths = downloadedFiles.map((f) => f.nativePath || f.path || String(f));
  logStatus(`Importing ${filePaths.length} file(s) into Premiere Pro project...`, "info");

  try {
    // importFiles(filePaths, suppressUI, targetBin, asNumberedStills)
    const result = await activeProject.importFiles(filePaths, true, targetBin, false);
    if (result || result === undefined) {
      logStatus(`Successfully imported ${filePaths.length} media item(s) to project bin!`, "info");
    } else {
      logStatus("Import completed with warnings.", "info");
    }
  } catch (err) {
    logStatus(`Premiere importFiles error: ${err.message}`, "error");
  }
}

// Action: Create Sequence
async function createSequence() {
  const selectedItems = state.mediaItems.filter((i) => state.selectedMediaIds.has(i.id));
  if (selectedItems.length === 0) {
    logStatus("No media items selected to build sequence.", "info");
    return;
  }

  if (!premiereApp) {
    logStatus("Feature unavailable: Premiere Pro API (require('premierepro')) is not available.", "error");
    return;
  }

  const getProj = premiereApp.Project?.getActiveProject || premiereApp.project?.getActiveProject;
  if (typeof getProj !== "function") {
    logStatus("Feature unavailable: getActiveProject() is not supported in this host version.", "error");
    return;
  }

  let activeProject = null;
  try {
    activeProject = await getProj();
  } catch (err) {
    logStatus(`Could not get active Premiere project: ${err.message}`, "error");
    return;
  }

  if (!activeProject) {
    logStatus("No active Premiere Pro project is open. Please open a project first.", "error");
    return;
  }

  // Sort selected items in shot order
  selectedItems.sort((a, b) => (a.shotOrder || 0) - (b.shotOrder || 0));

  // Feature detection: createSequenceFromMedia
  const hasCreateSequence = typeof activeProject.createSequenceFromMedia === "function";

  if (hasCreateSequence) {
    logStatus("Attempting sequence creation via createSequenceFromMedia...", "info");
    try {
      // First ensure media files are downloaded and imported
      const downloadedFiles = [];
      for (const item of selectedItems) {
        const file = await downloadFileToCache(item.relPath, item.filename);
        downloadedFiles.push(file);
      }

      let rootBin = null;
      if (typeof activeProject.getRootItem === "function") {
        rootBin = await activeProject.getRootItem();
      } else if (activeProject.rootItem) {
        rootBin = activeProject.rootItem;
      }

      const paths = downloadedFiles.map((f) => f.nativePath || f.path || String(f));
      if (typeof activeProject.importFiles === "function") {
        await activeProject.importFiles(paths, true, rootBin, false);
      }

      // Collect project items matching the media files
      let clipItems = [];
      if (typeof activeProject.findItemsMatchingMediaPath === "function") {
        for (const p of paths) {
          const matched = await activeProject.findItemsMatchingMediaPath(p);
          if (matched && matched.length > 0) {
            clipItems.push(matched[0]);
          }
        }
      }

      const seqName = `${state.selectedProject} - AI Studio Cut`;
      if (clipItems.length > 0) {
        const seq = await activeProject.createSequenceFromMedia(seqName, clipItems, rootBin);
        const name = seq ? (seq.name || seqName) : seqName;
        logStatus(`Sequence "${name}" created successfully from ${clipItems.length} clip(s)!`, "info");
        return;
      } else {
        logStatus("Could not map items to ClipProjectItem instances; proceeding to fallback...", "info");
      }
    } catch (createErr) {
      console.warn("createSequenceFromMedia encountered an error, trying fallback:", createErr);
      logStatus(`createSequenceFromMedia warning (${createErr.message}). Switching to interchange fallback...`, "info");
    }
  } else {
    logStatus("createSequenceFromMedia unavailable in this Premiere Pro version. Using interchange fallback...", "info");
  }

  // Fallback: Download .otio or .xml interchange and import into project
  await importInterchangeFallback(activeProject);
}

// Fallback sequence creation via OTIO / FCPXML export
async function importInterchangeFallback(activeProject) {
  logStatus("Requesting sequence interchange export (.xml / .otio)...", "info");

  const headers = {};
  if (state.token) {
    headers["Authorization"] = `Bearer ${state.token}`;
    headers["X-aistudio-token"] = state.token;
  }

  // Attempt interchange routes: /api/projects/{name}/export/otio or /api/projects/{name}/edit/export-fcpxml
  const candidateUrls = [
    `${state.serverUrl}/api/projects/${encodeURIComponent(state.selectedProject)}/export/otio`,
    `${state.serverUrl}/api/projects/${encodeURIComponent(state.selectedProject)}/export/xml`,
    `${state.serverUrl}/api/projects/${encodeURIComponent(state.selectedProject)}/edit/export-fcpxml`
  ];

  let interchangeBlob = null;
  let filename = `${state.selectedProject}_sequence.xml`;

  for (const url of candidateUrls) {
    try {
      const res = await fetch(url, { method: "GET", headers });
      if (res.ok) {
        interchangeBlob = await res.arrayBuffer();
        if (url.endsWith("otio")) {
          filename = `${state.selectedProject}_sequence.otio`;
        }
        break;
      }
    } catch (e) {
      console.warn(`Interchange candidate ${url} failed:`, e);
    }
  }

  if (!interchangeBlob) {
    logStatus("Interchange fallback failed: could not retrieve .otio or .xml sequence export from server.", "error");
    return;
  }

  try {
    const cacheFolder = await getCacheFolder();
    if (!cacheFolder) {
      throw new Error("UXP cache folder unavailable.");
    }

    const exportFile = await cacheFolder.createFile(filename, { overwrite: true });
    const writeOptions = (uxpStorage && uxpStorage.formats && uxpStorage.formats.binary)
      ? { format: uxpStorage.formats.binary }
      : {};
    await exportFile.write(interchangeBlob, writeOptions);

    let rootBin = null;
    if (typeof activeProject.getRootItem === "function") {
      rootBin = await activeProject.getRootItem();
    } else if (activeProject.rootItem) {
      rootBin = activeProject.rootItem;
    }

    const exportPath = exportFile.nativePath || exportFile.path || String(exportFile);
    if (typeof activeProject.importFiles === "function") {
      await activeProject.importFiles([exportPath], true, rootBin, false);
      logStatus(`Sequence successfully created via interchange import (${filename})!`, "info");
    } else {
      logStatus(`Export saved to ${exportPath}, but activeProject.importFiles is unavailable.`, "error");
    }
  } catch (err) {
    logStatus(`Interchange import failed: ${err.message}`, "error");
  }
}

// Event Handlers
function onProjectChanged() {
  state.selectedProject = elements.projectSelect.value;
  if (state.selectedProject) {
    loadProjectMedia(state.selectedProject);
  } else {
    state.mediaItems = [];
    state.selectedMediaIds.clear();
    renderMediaList();
  }
}

function onSelectAllToggle() {
  const allSelected = state.selectedMediaIds.size === state.mediaItems.length;
  if (allSelected) {
    state.selectedMediaIds.clear();
  } else {
    state.mediaItems.forEach((item) => state.selectedMediaIds.add(item.id));
  }
  renderMediaList();
}

// Initialization
async function init() {
  elements.btnConnect.addEventListener("click", connectServer);
  elements.btnRefresh.addEventListener("click", () => {
    if (state.selectedProject) {
      loadProjectMedia(state.selectedProject);
    } else {
      connectServer();
    }
  });
  elements.projectSelect.addEventListener("change", onProjectChanged);
  elements.btnSelectAll.addEventListener("click", onSelectAllToggle);
  elements.btnImportBin.addEventListener("click", importToBin);
  elements.btnCreateSequence.addEventListener("click", createSequence);

  // Restore stored token if available
  const savedToken = await loadStoredToken();
  if (savedToken) {
    elements.token.value = savedToken;
    state.token = savedToken;
  }

  // Feature detection report in status log
  const uxpStatus = uxp ? "UXP active" : "Standalone";
  const pproStatus = premiereApp ? "Premiere DOM available" : "Premiere DOM detached";
  logStatus(`Initialized (${uxpStatus}, ${pproStatus}).`, "info");
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
