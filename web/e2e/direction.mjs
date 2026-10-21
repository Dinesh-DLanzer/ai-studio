// Direction e2e (test mode, $0, nothing is approved): Native / Via prompt chips from the model profile, hidden controls with a hint, saved direction, proposal price breakdown.
import { chromium } from "playwright";
import { go } from "./nav.mjs";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-direction-"));
const port = 8822, token = "dirtoken", base = `http://127.0.0.1:${port}`;
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" } });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const hdr = { "x-aistudio-token": token, "content-type": "application/json" };
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch(); const page = await browser.newPage({ viewport: { width: 1400, height: 1100 } });
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}/?token=${token}`);
  await page.getByPlaceholder(/project-name/).fill("dirdemo"); await page.getByRole("button", { name: "Create" }).click();
  await page.getByRole("log", { name: "Conversation" }).waitFor();
  const put = await fetch(`${base}/api/projects/dirdemo/docs/Story.md`, { method: "PUT", headers: hdr, body: JSON.stringify({ text: readFileSync(join(here, "story.md"), "utf-8") }) });
  ok(put.ok, "story saved through the API");
  ok((await fetch(`${base}/api/projects/dirdemo/story/convert`, { method: "POST", headers: hdr })).ok, "story converted to shots");

  await page.reload(); await go(page, "Shots");
  const dir = page.getByTestId("direction"); await dir.waitFor({ timeout: 8000 }).catch(async () => { console.log((await page.locator("main").innerText()).slice(0, 800)); throw new Error("no direction section"); });
  await page.getByTestId("cap-chips").waitFor(); ok(true, "the model's capability chips are shown");
  ok(/No end frame/.test(await page.getByTestId("cap-chips").innerText()), "the test model shows 'No end frame'");
  ok(await page.getByTestId("endframe-hidden").isVisible(), "the end-frame picker is hidden with a hint when the model cannot use it");
  ok((await page.getByLabel("End frame image").count()) === 0 && (await page.getByTestId("keyframes-hidden").count()) === 1, "end frame and keyframe controls are not offered");

  await page.getByLabel("Camera preset").selectOption({ label: "Slow push-in" });
  ok((await page.getByLabel("Camera movement").inputValue()) === "dolly-in", "choosing a preset fills the movement");
  ok((await dir.getByTestId("chip-prompt").count()) >= 1 && (await dir.getByTestId("chip-native").count()) === 0, "every control is Via prompt on a prompt-only model");
  await page.getByLabel("Framing").selectOption("close-up");
  await page.getByLabel("Lens in millimetres").fill("35");
  await page.getByLabel("Lighting").fill("golden hour");
  await page.getByRole("button", { name: "Save", exact: true }).last().click();
  await page.getByText("Shots saved.").waitFor();
  const shots = await (await fetch(`${base}/api/projects/dirdemo`, { headers: hdr })).json();
  const d = shots.shots.shots[0].direction;
  ok(d && d.movement === "dolly-in" && d.framing === "close-up" && d.lens_mm === 35 && d.lighting === "golden hour", "the direction is saved in shots.json");

  // the model's profile decides what is offered: grant native dolly-in, an end frame and one keyframe (a user override, the backend validates it)
  const bad = await fetch(`${base}/api/capabilities/fake/fake/video`, { method: "PUT", headers: hdr, body: JSON.stringify({ tasks: ["nonsense"] }) });
  ok(bad.status === 400, "the backend refuses an invalid capability override");
  const good = await fetch(`${base}/api/capabilities/fake/fake/video`, { method: "PUT", headers: hdr, body: JSON.stringify({ camera: { mode: "native", native: ["dolly_in"], param: "camera" }, frames: { start: true, end: true, keyframes: 1 } }) });
  ok(good.ok, "a capability override is saved");
  await page.reload(); await go(page, "Shots"); await page.getByTestId("direction").waitFor();
  await page.getByTestId("chip-native").first().waitFor(); ok(true, "dolly-in now shows the Native chip");
  ok((await page.getByLabel("End frame image").count()) === 1, "the end-frame picker appears when the model supports it");
  await page.getByRole("button", { name: "Add keyframe" }).click(); ok((await page.getByLabel("Keyframe 1 image").count()) === 1, "a keyframe row can be added");
  const none = await fetch(`${base}/api/capabilities/fake/fake/video`, { method: "PUT", headers: hdr, body: JSON.stringify({ camera: { mode: "none", native: [], param: null } }) });
  ok(none.ok, "camera control can be turned off by override");
  await page.reload(); await go(page, "Shots"); await page.getByTestId("camera-hidden").waitFor();
  ok((await page.getByLabel("Camera movement").count()) === 0, "camera controls are hidden when the model has none");

  // the proposal dialog shows the price breakdown; nothing is approved here
  const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
  await fetch(`${base}/api/projects/dirdemo/upload?rel=stills/s01.png`, { method: "POST", headers: { "x-aistudio-token": token }, body: png });
  await page.reload(); await go(page, "Shots"); await page.getByTestId("camera-hidden").waitFor();
  // (test project, $0) budget estimated and approved through the human API so a clip can be proposed
  await fetch(`${base}/api/projects/dirdemo/estimate`, { method: "POST", headers: hdr, body: "{}" });
  await fetch(`${base}/api/projects/dirdemo/budget/approve`, { method: "POST", headers: hdr });
  await page.getByRole("button", { name: "Generate New Version" }).click();
  await page.getByText("Approve this paid action?").waitFor();
  await page.getByTestId("price-breakdown").waitFor(); ok(/Total/.test(await page.getByTestId("price-breakdown").innerText()), "the approve dialog lists the price breakdown");
  ok(await page.getByTestId("profile-chips").isVisible(), "the approve dialog shows the model capabilities");
  await page.getByRole("button", { name: "Cancel" }).click();
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join("; ") : ""));
  await browser.close();
} finally { srv.kill(); }
process.exit(failed ? 1 : 0);
