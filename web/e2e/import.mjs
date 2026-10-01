// Import e2e (test mode, $0): images that exist in stills/ but not in the asset list are found, categorised and imported.
import { chromium } from "playwright";
import { go } from "./nav.mjs";
import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-import-"));
const shots = process.env.SHOTS_DIR || join(tmpdir(), "aistudio-shots"); mkdirSync(shots, { recursive: true });
const port = 8817, token = "importtoken";
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" } });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`http://127.0.0.1:${port}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch(); const page = await browser.newPage({ viewport: { width: 1300, height: 1000 } });
  page.on("dialog", (d) => d.accept());
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`http://127.0.0.1:${port}/?token=${token}`);
  await page.getByPlaceholder(/project-name/).fill("impdemo"); await page.getByRole("button", { name: "Create" }).click();
  await page.getByRole("navigation", { name: "Project" }).waitFor();
  const stills = join(home, "projects", "impdemo", "stills");
  for (const n of ["Ramesh Shop With Crowed.png", "Ramesh.png", "s01.png", "my logo.png"]) writeFileSync(join(stills, n), PNG);
  writeFileSync(join(stills, "notes.txt"), "not an image");
  await go(page, "Assets");
  await page.getByText(/Found 4 images in this project's stills folder/).waitFor({ timeout: 10000 }); ok(true, "images present in stills/ but not in the asset list are found (4 images, the text file is ignored)");
  await page.screenshot({ path: join(shots, "18-import.png"), fullPage: true });
  ok((await page.getByLabel("Asset id for Ramesh Shop With Crowed.png").inputValue()) === "ramesh_shop_with_crowed", "a name with spaces gets a clean suggested id");
  ok((await page.getByLabel("Category for Ramesh Shop With Crowed.png").inputValue()) === "background", "a shop image is suggested as a background");
  ok((await page.getByLabel("Category for my logo.png").inputValue()) === "other", "a logo is suggested as 'other'");
  ok((await page.getByLabel("Category for s01.png").inputValue()) === "frame", "sNN.png is suggested as a scene frame");
  ok((await page.getByLabel("Category for Ramesh.png").inputValue()) === "character", "a person's name is suggested as a character");

  // an invalid id is refused and nothing is moved
  await page.getByLabel("Asset id for Ramesh.png").fill("bad id!");
  await page.getByRole("button", { name: /Add 4 to the list/ }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Add", exact: true }).click();
  await page.getByText(/invalid asset id/).waitFor(); ok(true, "an invalid id is refused with a message");
  ok(readdirSync(stills).includes("Ramesh.png"), "nothing was renamed after the refused attempt");
  await page.getByLabel("Asset id for Ramesh.png").fill("ramesh");

  // change a category, deselect one, import
  await page.getByLabel("Category for s01.png").selectOption("character");
  await page.getByLabel("Add my logo.png").uncheck();
  await page.getByRole("button", { name: /Add 3 to the list/ }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Add", exact: true }).click();
  await page.getByText("Added 3 image(s) to the asset list.").waitFor(); ok(true, "the selected images were added");
  await page.locator('[data-asset="ramesh_shop_with_crowed"]').waitFor(); await page.locator('[data-asset="ramesh"]').waitFor();
  ok((await page.locator('[data-asset="ramesh_shop_with_crowed"] img, [data-asset="ramesh"] img, [data-asset="s01"] img').count()) >= 3, "the imported assets show their images as ready");
  const names = readdirSync(stills);
  ok(names.includes("ramesh_shop_with_crowed.png") && names.includes("ramesh.png") && !names.includes("Ramesh Shop With Crowed.png") && names.includes("my logo.png"), "files were renamed to their ids; the unselected file was left alone");
  await page.getByText(/Found 1 image in this project's stills folder/).waitFor(); ok(true, "the remaining unregistered image is still offered");
  await page.screenshot({ path: join(shots, "19-imported.png"), fullPage: true });
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  await browser.close();
} catch (e) { console.log("FAIL exception: " + e.message.split("\n")[0]); failed = true; }
finally { srv.kill(); }
process.exit(failed ? 1 : 0);
