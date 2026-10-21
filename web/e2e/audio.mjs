// Audio Suite e2e (test mode, $0, no paid action):
// Voice picker, voiceover plan batch modal, per-shot voice lines, audio proposal forms,
// caption preview, and loudness/ducking export options.
import { chromium } from "playwright";
import { go } from "./nav.mjs";
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-audio-"));
const port = 8828, token = "audiotoken", base = `http://127.0.0.1:${port}`;
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

  // Create project with voiced shots
  await api("POST", "/api/projects", { name: "audiodemo" });
  await api("PUT", "/api/projects/audiodemo/brief", {
    brand: "Chai Corner",
    goal: "Morning walk-ins",
    voice: { voice_id: "alloy" },
  });
  const shotsRes = await api("PUT", "/api/projects/audiodemo/shots", {
    aspect_ratio: "9:16",
    final_resolution: "720p",
    shots: [
      {
        id: "s01",
        model: "google/veo-3.1-lite",
        prompt: "Tea master pouring boiling tea",
        seconds: 4,
        voice_mode: "off-camera",
        voice_line: "Freshly brewed chai every single morning.",
      },
      {
        id: "s02",
        model: "google/veo-3.1-lite",
        prompt: "Customer smiling enjoying a warm cup",
        seconds: 4,
        voice_mode: "on-camera",
        voice_line: "The best chai in town, made with real spices.",
      },
      {
        id: "s03",
        model: "google/veo-3.1-lite",
        prompt: "Exterior banner of Chai Corner stall",
        seconds: 4,
        voice_mode: "silent",
        voice_line: "",
      },
    ],
  });
  ok(shotsRes.status === 200, "shots saved to audiodemo project");

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1300, height: 950 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto(`${base}/?token=${token}`);
  await page.goto(`${base}/#/p/audiodemo`);

  // Navigate to Audio page via sidebar
  await go(page, "Audio");
  await page.getByTestId("audio-page").waitFor({ timeout: 10000 });
  ok(true, "Audio page loads from the sidebar");

  // 1. Voice picker verification
  const voiceSelect = page.getByLabel("Preset Voice selection");
  await voiceSelect.waitFor();
  ok(await voiceSelect.isVisible(), "Voice picker dropdown is displayed");
  const voiceOptions = await voiceSelect.locator("option").allInnerTexts();
  ok(voiceOptions.length >= 4, "Voice picker contains TTS preset voices");

  // 2. Per-shot voice line list with char count & price hints
  await page.getByTestId("shot-voice-list").waitFor();
  ok(await page.getByTestId("shot-voice-row-s01").isVisible(), "Shot s01 voice row is visible");
  ok(await page.getByTestId("shot-voice-row-s02").isVisible(), "Shot s02 voice row is visible");
  ok(await page.getByTestId("shot-voice-row-s03").isVisible(), "Shot s03 silent row is visible");

  const s01Text = await page.getByTestId("shot-voice-row-s01").innerText();
  ok(/Freshly brewed chai/.test(s01Text), "Shot s01 contains spoken voice line");
  ok(/chars/.test(s01Text) && /est\./.test(s01Text), "Shot s01 displays character count and price hint");

  // 3. Plan voiceover batch button opens shared BatchPlanModal
  const planBtn = page.getByTestId("voiceover-plan-btn");
  ok(await planBtn.isEnabled(), "Plan Voiceover Batch button is enabled");
  await planBtn.click();

  await page.getByTestId("plan").waitFor({ timeout: 8000 });
  ok(true, "Planning voiceovers opens the existing shared batch approve dialog");
  ok(await page.getByTestId("plan-total").isVisible(), "Exact batch total price is displayed");
  ok(await page.getByTestId("approve-all").isVisible(), "Approve and run button is present");
  await page.keyboard.press("Escape");

  // 4. Proposal forms for audio tools
  ok(await page.getByTestId("form-music").isVisible(), "Music bed proposal form is visible by default");
  ok(await page.getByTestId("propose-music-btn").isVisible(), "Propose Music button is visible");

  await page.getByRole("tab", { name: /Sound Effects SFX/ }).click();
  await page.getByTestId("form-sfx").waitFor();
  ok(await page.getByTestId("propose-sfx-btn").isVisible(), "SFX proposal form is visible");

  await page.getByRole("tab", { name: /Lip Sync/ }).click();
  await page.getByTestId("form-lipsync").waitFor();
  ok(await page.getByTestId("propose-lipsync-btn").isVisible(), "Lip sync proposal form is visible");

  await page.getByRole("tab", { name: /Transcription/i }).click();
  await page.getByTestId("form-transcribe").waitFor();
  ok(await page.getByTestId("propose-transcribe-btn").isVisible(), "Transcribe proposal form is visible");

  // 5. Caption preview
  await page.getByTestId("caption-preview-box").waitFor();
  ok(await page.getByTestId("caption-preview-box").isVisible(), "Caption preview container is visible");

  // 6. Loudness & Ducking options
  ok(await page.getByLabel("Loudness target standard selection").isVisible(), "Loudness target dropdown is present");
  ok(await page.getByLabel("Duck background music under dialogue").isVisible(), "Music ducking checkbox is present");
  ok(await page.getByRole("button", { name: /Save export mix settings/i }).isVisible(), "Save mix settings button is present");

  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join("; ") : ""));
  await browser.close();
} finally {
  srv.kill();
}

process.exit(failed ? 1 : 0);
