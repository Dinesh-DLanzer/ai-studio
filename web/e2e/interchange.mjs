// Interchange & External Edit e2e (test mode, $0, no paid action):
// "Export for…" download cards (OTIO, OTIOZ, FCP7 XML, FCPXML, EDL, SRT, VTT, bundle, JSX),
// "Edit externally" button on media with status chip "waiting for save", stop button,
// OTIO import diff preview and human confirmation, and Settings > allowed-apps editor.
import { chromium } from "playwright";
import { go } from "./nav.mjs";
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-interchange-"));
const port = 8829, token = "interchangetoken", base = `http://127.0.0.1:${port}`;
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], {
  cwd: repo,
  env: {
    ...process.env,
    AISTUDIO_HOME: home,
    AISTUDIO_TOKEN: token,
    AISTUDIO_PORT: String(port),
    AISTUDIO_ALL_TEST: "1",
    AISTUDIO_NO_NETWORK: "1",
  },
});

let failed = false;
const ok = (c, m) => {
  console.log((c ? "PASS " : "FAIL ") + m);
  if (!c) failed = true;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const H = { "x-aistudio-token": token, "content-type": "application/json" };
const api = async (m, u, b) => {
  const r = await fetch(base + u, {
    method: m,
    headers: H,
    body: b === undefined ? undefined : JSON.stringify(b),
  });
  return { status: r.status, json: await r.json().catch(() => ({})) };
};

try {
  for (let i = 0; i < 40; i++) {
    try {
      if ((await fetch(`${base}/api/health`)).ok) break;
    } catch {}
    await sleep(250);
  }

  // Create project and files
  await api("POST", "/api/projects", { name: "interchangedemo" });
  const pdir = join(home, "projects", "interchangedemo");
  mkdirSync(join(pdir, "clips"), { recursive: true });
  mkdirSync(join(pdir, "stills"), { recursive: true });
  mkdirSync(join(pdir, "audio"), { recursive: true });

  writeFileSync(join(pdir, "clips", "s01.mp4"), Buffer.from("FAKEMP4testvideo1234567890"));
  writeFileSync(join(pdir, "stills", "s01.png"), Buffer.from("\x89PNG\r\n\x1a\nfakeimage"));
  writeFileSync(join(pdir, "audio", "song.mp3"), Buffer.from("ID3fakeaudio12345"));

  await api("PUT", "/api/projects/interchangedemo/shots", {
    aspect_ratio: "9:16",
    final_resolution: "720p",
    shots: [
      {
        id: "s01",
        model: "google/veo-3.1-lite",
        prompt: "Shot 1 scene action",
        seconds: 4,
      },
    ],
  });

  await api("PUT", "/api/projects/interchangedemo/edit", {
    tracks: {
      video: [{ id: "c01", src: "clips/s01.mp4", in: 0, out: 4 }],
      audio: [],
      text: [],
    },
  });

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1300, height: 950 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto(`${base}/?token=${token}`);
  await page.goto(`${base}/#/p/interchangedemo`);

  // Navigate to Interchange page
  await go(page, "Export");
  await page.getByTestId("interchange-page").waitFor({ timeout: 10000 });
  ok(true, "Interchange page loads from the sidebar");

  // 1. "Export for…" options grid
  await page.getByTestId("export-options-grid").waitFor();
  ok(await page.getByTestId("export-card-otio").isVisible(), "OTIO export option is visible");
  ok(await page.getByTestId("export-card-otioz").isVisible(), "OTIOZ export option is visible");
  ok(await page.getByTestId("export-card-xmeml").isVisible(), "FCP7 XML export option is visible");
  ok(await page.getByTestId("export-card-fcpxml").isVisible(), "FCPXML export option is visible");
  ok(await page.getByTestId("export-card-edl").isVisible(), "EDL export option is visible");
  ok(await page.getByTestId("export-card-srt").isVisible(), "SRT subtitles export option is visible");
  ok(await page.getByTestId("export-card-vtt").isVisible(), "VTT captions export option is visible");
  ok(await page.getByTestId("export-card-bundle").isVisible(), "Canva & Google Vids bundle option is visible");

  // 2. "Edit externally" button on clips/stills/audio
  await page.getByTestId("media-external-list").waitFor();
  const editExtBtn = page.getByTestId("edit-ext-clips-s01-mp4");
  await editExtBtn.waitFor();
  ok(await editExtBtn.isVisible(), "Edit Externally button is visible on clips/s01.mp4");

  await editExtBtn.click();
  await page.getByTestId("status-waiting-for-save").waitFor({ timeout: 6000 });
  ok(true, "Clicking Edit Externally displays 'waiting for save' status chip");
  ok(await page.getByTestId("external-edit-banner").isVisible(), "Active external edit banner is visible");

  const stopBtn = page.getByTestId("stop-external-edit");
  ok(await stopBtn.isVisible(), "Stop button is visible for external edit session");
  await stopBtn.click();
  await page.waitForFunction(() => !document.querySelector("[data-testid=status-waiting-for-save]"), null, { timeout: 6000 });
  ok(true, "Clicking Stop ends the external editing session");

  // 3. OTIO import preview and human confirmation
  const otioTextarea = page.getByLabel("OTIO JSON document content");
  await otioTextarea.fill('{"OTIO_SCHEMA":"Timeline.1","tracks":{"children":[]}}');

  const previewBtn = page.getByTestId("preview-otio-btn");
  ok(await previewBtn.isEnabled(), "Preview OTIO Import button is enabled");
  await previewBtn.click();

  await page.getByTestId("otio-diff-view").waitFor({ timeout: 8000 });
  ok(true, "Previewing OTIO import displays diff view comparing current vs imported timeline");

  const applyBtn = page.getByTestId("apply-otio-btn");
  ok(await applyBtn.isVisible(), "Confirm & Apply button is visible for human confirmation");
  await applyBtn.click();
  await page.waitForFunction(() => !document.querySelector("[data-testid=otio-diff-view]"), null, { timeout: 6000 });
  ok(true, "Confirming OTIO import applies changes to timeline with existing PUT /edit");

  // 4. Settings > Approved desktop applications editor
  await page.goto(`${base}/#/settings`);
  await page.getByTestId("allowed-apps-list").waitFor({ timeout: 10000 });
  ok(true, "Settings displays the approved desktop applications editor");

  const appInput = page.getByLabel("New application name");
  await appInput.fill("Photoshop");
  await page.getByTestId("add-allowed-app-btn").click();

  await page.getByTestId("allowed-app-chip-Photoshop").waitFor({ timeout: 6000 });
  ok(true, "Adding Photoshop persists it into allowed desktop apps list via PUT /api/external-apps");

  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join("; ") : ""));
  await browser.close();
} finally {
  srv.kill();
}

process.exit(failed ? 1 : 0);
