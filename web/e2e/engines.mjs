// Local Engines & Paired Devices e2e (test mode, $0, no paid action):
// ComfyUI workflow listing, add with node mapping dropdowns, validate dry-run, capability profile, delete.
// Paired devices: start pairing, 6-digit code in human session with countdown, explain permissions, device list, revoke.
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-engines-"));
const port = 8830, token = "enginestoken", base = `http://127.0.0.1:${port}`;
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

  // Create project
  await api("POST", "/api/projects", { name: "enginesdemo" });

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1300, height: 950 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto(`${base}/?token=${token}`);
  await page.goto(`${base}/#/settings`);

  // 1. Local Engines: ComfyUI Workflows
  await page.getByTestId("local-engines-section").waitFor({ timeout: 10000 });
  ok(true, "Settings displays the Local Engines section");

  const addBtn = page.getByTestId("add-workflow-btn");
  ok(await addBtn.isVisible(), "Add Workflow button is visible");
  await addBtn.click();

  await page.getByTestId("add-workflow-form").waitFor();
  ok(true, "Clicking Add Workflow opens registration form");

  await page.getByLabel("Workflow ID slug").fill("wan-i2v");

  const sampleWorkflow = {
    "3": { class_type: "KSampler", inputs: { seed: 12345, steps: 20 } },
    "6": { class_type: "CLIPTextEncode", inputs: { text: "Cinematic portrait" } },
    "52": { class_type: "LoadImage", inputs: { image: "start.png" } },
    "50": { class_type: "EmptyLatentImage", inputs: { length: 48 } },
  };

  const jsonArea = page.getByLabel("Paste workflow API JSON content");
  await jsonArea.fill(JSON.stringify(sampleWorkflow, null, 2));

  // Verify node mapping dropdowns
  ok(await page.getByLabel("Prompt node selector").isVisible(), "Node mapping dropdown for prompt is visible");
  ok(await page.getByLabel("Seed node selector").isVisible(), "Node mapping dropdown for seed is visible");

  // Validate dry-run
  const validateBtn = page.getByTestId("validate-dry-run-btn");
  ok(await validateBtn.isEnabled(), "Validate dry-run button is enabled");
  await validateBtn.click();

  await page.getByTestId("validation-success-chip").waitFor({ timeout: 8000 });
  ok(true, "Dry-run validation passes and confirms compatibility");

  // Register workflow
  const registerBtn = page.getByTestId("register-workflow-btn");
  await registerBtn.click();

  await page.getByTestId("workflow-row-wan-i2v").waitFor({ timeout: 8000 });
  ok(true, "ComfyUI workflow registered and visible in list");

  const rowText = await page.getByTestId("workflow-row-wan-i2v").innerText();
  ok(/Durations:/.test(rowText) && /Resolutions:/.test(rowText), "Derived capability profile is displayed on workflow card");

  // Delete workflow
  const deleteBtn = page.getByTestId("delete-workflow-wan-i2v");
  ok(await deleteBtn.isVisible(), "Delete workflow button is present");
  await deleteBtn.click();

  // Confirm dialog
  await page.getByRole("button", { name: "Move to Trash" }).click();
  await page.waitForFunction(() => !document.querySelector("[data-testid=workflow-row-wan-i2v]"), null, { timeout: 6000 });
  ok(true, "Workflow deleted and moved to trash");

  // 2. Paired Devices Section
  await page.getByTestId("paired-devices-section").waitFor({ timeout: 8000 });
  ok(true, "Paired Devices section is visible under Integrations");

  const explanation = await page.getByTestId("paired-devices-section").innerText();
  ok(/Devices cannot approve spending/.test(explanation), "Permission model explains devices cannot approve spending");

  const startPairingBtn = page.getByTestId("start-pairing-btn");
  ok(await startPairingBtn.isVisible(), "Start Pairing button is visible");
  await startPairingBtn.click();

  await page.getByTestId("pairing-active-card").waitFor({ timeout: 8000 });
  ok(true, "Active pairing challenge card appears");

  await page.getByTestId("pairing-code").waitFor({ timeout: 8000 });
  const code = (await page.getByTestId("pairing-code").innerText()).trim();
  ok(/^\d{6}$/.test(code), `6-digit pairing code is shown in human session: ${code}`);

  ok(await page.getByTestId("pairing-countdown").isVisible(), "Expiry countdown timer is displayed");

  // Simulate an NLE panel confirming pairing with this code
  const confirmRes = await fetch(`${base}/api/pair/confirm`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      code,
      host: "premiere",
      device_name: "Edit Bay Mac Studio",
    }),
  });
  const confirmJson = await confirmRes.json();
  ok(confirmRes.ok && confirmJson.device_token, "NLE device successfully confirmed pairing");

  // Refresh and verify device list
  await page.reload();
  await page.getByTestId("paired-device-list").waitFor({ timeout: 8000 });
  ok(await page.getByTestId("paired-device-list").getByText("Edit Bay Mac Studio").isVisible(), "Paired device appears in Connected Devices list");
  ok(await page.getByTestId("paired-device-list").getByText("premiere").isVisible(), "Device host badge is visible");

  // Revoke device
  const revokeBtn = page.locator("[data-testid^=revoke-device-]").first();
  ok(await revokeBtn.isVisible(), "Revoke device button is visible");
  await revokeBtn.click();

  await page.getByRole("button", { name: "Revoke Device" }).click();
  await page.waitForFunction(() => !document.querySelector("[data-testid^=device-row-]"), null, { timeout: 6000 });
  ok(true, "Paired device revoked successfully");

  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join("; ") : ""));
  await browser.close();
} finally {
  srv.kill();
}

process.exit(failed ? 1 : 0);
