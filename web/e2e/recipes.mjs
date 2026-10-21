// Recipes page smoke flow in isolated test mode. Planning never approves or runs a batch.
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../.."); const home = mkdtempSync(join(tmpdir(), "aistudio-recipes-"));
const port = 8822, token = "recipestoken", base = `http://127.0.0.1:${port}`; const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" } });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms)); let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
try { for (let i = 0; i < 40; i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch(); const page = await browser.newPage(); const errors = []; page.on("pageerror", (e) => errors.push(e.message)); await page.goto(`${base}/?token=${token}`);
  await page.getByPlaceholder(/project-name/).fill("recipedemo"); await page.getByRole("button", { name: "Create" }).click(); await page.getByRole("log", { name: "Conversation" }).waitFor();
  await page.goto(`${base}/#/p/recipedemo/recipes`); await page.getByRole("heading", { name: /Recipe Library/ }).waitFor();
  const recipes = await fetch(`${base}/api/recipes?project=recipedemo`, { headers: { "x-aistudio-token": token } }).then((r) => r.json()); ok(Array.isArray(recipes.recipes), "recipe cards load from the recipe API");
  ok(await page.getByText(/person must review and approve/i).isVisible(), "page explains human approval is required"); ok(errors.length === 0, "no browser errors"); await browser.close();
} finally { srv.kill(); } process.exit(failed ? 1 : 0);
