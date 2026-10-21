// Cast UI smoke check in test mode ($0): consent form, identity sheet and version controls.
import { chromium } from "playwright";
import { go } from "./nav.mjs";
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const here = dirname(fileURLToPath(import.meta.url)), repo = resolve(here, "../.."), home = mkdtempSync(join(tmpdir(), "aistudio-cast-"));
const port = 8831, token = "casttoken", base = `http://127.0.0.1:${port}`;
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" } });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; }; const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
try {
  for (let i=0;i<40;i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch(), page = await browser.newPage();
  await page.goto(`${base}/?token=${token}`); await page.getByPlaceholder(/project-name/).fill("castdemo"); await page.getByRole("button", {name:"Create"}).click(); await go(page,"Assets");
  await page.getByText(/No characters yet/).waitFor();
  await page.getByRole("button", {name:/Add Character/}).first().click(); await page.getByLabel("Asset id").fill("maya"); await page.getByLabel("Asset description").fill("Test character"); await page.getByRole("button", {name:"Add", exact:true}).click();
  await page.locator('[data-asset="maya"]').click();
  await page.getByRole("region", {name:"Consent"}).waitFor().catch(() => {});
  ok(await page.getByRole("button", {name:/Build identity sheet/}).isVisible(), "identity sheet control is shown");
  ok(await page.getByLabel("Consent statement").isVisible(), "consent form asks for a written statement");
  ok(await page.getByLabel("Number of candidates").isVisible(), "variant count picker is labelled");
  await browser.close();
} catch (e) { console.error(e); failed = true; } finally { srv.kill("SIGTERM"); }
if (failed) process.exitCode = 1;
