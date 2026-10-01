// Manage e2e (test mode, $0): verification findings, languages, renames, AI model settings.
import { chromium } from "playwright";
import { go } from "./nav.mjs";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-manage-"));
const shots = process.env.SHOTS_DIR || join(tmpdir(), "aistudio-shots"); mkdirSync(shots, { recursive: true });
const port = 8816, token = "managetoken";
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" } });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`http://127.0.0.1:${port}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch(); const page = await browser.newPage({ viewport: { width: 1300, height: 1000 } });
  page.on("dialog", (d) => d.accept());
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`http://127.0.0.1:${port}/?token=${token}`);
  await page.getByPlaceholder(/project-name/).fill("mgr"); await page.getByRole("button", { name: "Create" }).click();
  await go(page, "Story");
  await page.waitForFunction(() => document.querySelector("textarea")?.value.includes("STORYBOARD"));
  await page.locator("textarea").first().fill(readFileSync(join(here, "story.md"), "utf-8"));
  await page.getByRole("button", { name: "Save", exact: true }).first().click(); await page.getByText("Saved").first().waitFor();
  await page.getByRole("dialog").getByText("Set the budget").first().waitFor(); await page.getByRole("button", { name: "Decide later" }).click();

  // ---- languages (the voice language is chosen in the brief form on the Storyboard page, then saved)
  const brief = async () => (await (await fetch(`http://127.0.0.1:${port}/api/projects/mgr/brief`, { headers: { "x-aistudio-token": token } })).json());
  const lang = async () => (await brief()).fields.find((f) => f.key === "language")?.value;
  await go(page, "Story"); await page.getByRole("tab", { name: /brief\.md/ }).click();
  const sel = page.getByLabel("Brief voice language", { exact: true });
  const saveBrief = async () => { const put = page.waitForResponse((r) => r.url().includes("/brief") && r.request().method() === "PUT"); await page.getByRole("button", { name: "Save", exact: true }).first().click(); await put; };
  await sel.selectOption("Tamil"); await saveBrief();
  await page.waitForFunction(async ([p, t]) => { const r = await (await fetch(`http://127.0.0.1:${p}/api/projects/mgr/brief`, { headers: { "x-aistudio-token": t } })).json(); return r.fields.find((f) => f.key === "language")?.value === "Tamil"; }, [port, token]);
  ok((await lang()) === "Tamil", "the voice language can be chosen from a list");
  await page.getByText(/Tested with the video model/).waitFor(); ok(true, "a tested language shows its guidance");
  await sel.selectOption("Hindi");
  await page.getByText(/Not tested yet with the video model/).waitFor(); ok(true, "an untested language shows a warning");
  await sel.selectOption("Tamil"); await saveBrief();
  await page.getByText(/Tested with the video model/).waitFor(); ok((await lang()) === "Tamil", "the language is switched back to Tamil");

  // saving Story.md rebuilds the shots (there is no separate Convert button), now with the chosen language
  await go(page, "Story"); await page.getByRole("tab", { name: /Story\.md/ }).click();
  await page.waitForFunction(() => document.querySelector("textarea")?.value.includes("STORYBOARD"));
  await page.getByRole("button", { name: "Save", exact: true }).first().click();
  await page.getByRole("dialog").getByText("Set the budget").first().waitFor(); await page.getByRole("button", { name: "Decide later" }).click();
  await page.getByText(/Updated: 3 shots/).waitFor();
  const shotsDoc = await (await fetch(`http://127.0.0.1:${port}/api/projects/mgr`, { headers: { "x-aistudio-token": token } })).json();
  ok(/says this line in Tamil/.test(shotsDoc.shots.shots[0].prompt), "the converted shots name the language in the spoken line");

  // ---- verification
  await go(page, "Shots");
  await page.locator('[data-verify="shots"]').waitFor(); ok(true, "the Shots tab has a verification bar");
  await page.getByRole("button", { name: "Open shot s02" }).click();   // second shot prompt: make it Tanglish and add a colour code
  const ta = page.getByLabel("Prompt for shot s02");
  await ta.fill('SUBJECT: phone (#07363c). AUDIO: An off-camera narrator says this line in Tamil, clearly: "kadai irukku instagram irukku" (I have a shop).');
  await page.getByRole("region", { name: "Shot s02" }).getByRole("button", { name: "Save", exact: true }).click(); await page.getByText("Shots saved.").waitFor();
  await page.locator('[data-verify="shots"][data-status="fail"]').waitFor({ timeout: 15000 }); ok(true, "a Tanglish voice line makes the shots verification FAIL");
  await page.locator('[data-verify="shots"]').getByRole("button", { name: /findings?/ }).click();
  await page.getByText(/not written in Tamil script/).waitFor(); ok(true, "the finding explains the problem");
  await page.getByText(/colour code/).first().waitFor(); ok(true, "a colour code in the prompt is flagged");
  await page.getByText(/Fix: Write the line in Tamil script/).waitFor(); ok(true, "each finding says how to fix it");
  await page.locator('[data-verify="shots"]').getByText(/AI reviewed|AI review/).first().waitFor({ timeout: 15000 }); ok(true, "the AI review state is shown");
  await page.screenshot({ path: join(shots, "16-verify.png"), fullPage: true });

  // ---- renames
  await go(page, "Assets");
  await page.getByRole("button", { name: "Rename asset s01" }).click();
  await page.getByLabel("New asset name").fill("hero"); await page.getByRole("button", { name: "Rename", exact: true }).click();
  await page.getByText("Renamed s01 to hero.").waitFor(); ok(true, "an asset can be renamed");
  await go(page, "Shots");
  await page.getByRole("button", { name: "Advanced Settings" }).click();
  await page.getByText("stills/hero.png", { exact: true }).first().waitFor(); ok(true, "the shot's first frame followed the asset rename");
  await page.getByRole("button", { name: "Open shot s02" }).click();
  await page.getByRole("button", { name: "Rename shot s02" }).click();
  await page.getByLabel("New shot name").fill("pain"); await page.getByRole("button", { name: "Rename", exact: true }).click();
  await page.getByText("Renamed s02 to pain.").waitFor(); ok(true, "a shot can be renamed");
  await page.getByRole("button", { name: "Open shot s01" }).click();
  await page.getByRole("button", { name: "Rename shot s01" }).click();
  await page.getByLabel("New shot name").fill("bad name!"); await page.getByRole("button", { name: "Rename", exact: true }).click();
  await page.getByText(/letters, numbers/).waitFor(); ok(true, "an invalid name is rejected in the dialog"); await page.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("button", { name: "Rename project mgr" }).click();
  await page.getByLabel("New project name").fill("mgr2"); await page.getByRole("button", { name: "Rename", exact: true }).click();
  await page.waitForFunction(() => location.hash === "#/p/mgr2"); await page.getByRole("heading", { name: /mgr2/ }).waitFor(); ok(true, "the project can be renamed and the page follows it");
  await page.reload(); await page.getByRole("heading", { name: /mgr2/ }).waitFor();

  // ---- AI model settings (the detailed Settings tests live in settings.mjs)
  await page.getByRole("link", { name: "Settings" }).first().click();
  await page.getByRole("heading", { name: "Settings", exact: true }).waitFor(); ok(true, "the sidebar Settings link opens the Settings page");
  await page.getByText("Model Configuration").first().waitFor(); ok(true, "the Settings page shows Model Configuration");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  await browser.close();
} catch (e) { console.log("FAIL exception: " + e.message.split("\n").slice(0,4).join(" | ")); failed = true; }
finally { srv.kill(); }
process.exit(failed ? 1 : 0);
