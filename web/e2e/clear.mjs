// Consent clearance e2e (test mode, $0): a human explicitly clears an uploaded test image by its exact SHA.
import { chromium } from "playwright";
import { go } from "./nav.mjs";
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-clear-"));
const port = 8831, token = "cleartoken", base = `http://127.0.0.1:${port}`;
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1", AISTUDIO_NO_KEYRING: "1" } });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
let browser, page;
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  browser = await chromium.launch(); page = await browser.newPage();
  await page.goto(`${base}/?token=${token}`);
  await page.getByPlaceholder(/project-name/).fill("cleardemo"); await page.getByRole("button", { name: "Create" }).click();
  await go(page, "Assets");
  await page.getByRole("button", { name: "Add Character" }).first().click();
  await page.getByLabel("Asset id").fill("test_face"); await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByLabel("Upload image for test_face").first().setInputFiles({ name: "test.png", mimeType: "image/png", buffer: PNG });
  await page.locator('[data-asset="test_face"] img').waitFor(); await page.locator('[data-asset="test_face"]').getByRole("button", { name: /Open test_face in the preview/ }).click();
  const clear = page.getByRole("button", { name: "Clear for use" }).first(); await clear.waitFor();
  ok(await page.getByText("Unverified", { exact: true }).count() > 0, "unverified media is labeled in the consent panel");
  await clear.click(); await page.getByText(/I confirm this file does not show a real person/).waitFor();
  await page.getByRole("button", { name: "I confirm" }).click();
  await page.getByText(/is cleared for use/).waitFor(); ok(true, "human clearance records exact-byte confirmation");
  await browser.close();
} catch (e) { console.log("FAIL exception: " + (e.stack || e)); try { console.log("BODY: " + (await page.locator("body").innerText()).replace(/\s+/g, " ").split("Cast:").slice(1).join("Cast:").slice(0, 1800) || "NO CAST PANEL"); } catch {} failed = true; }
finally { srv.kill(); }
process.exit(failed ? 1 : 0);
