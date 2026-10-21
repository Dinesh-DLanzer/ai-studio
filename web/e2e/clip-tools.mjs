// Clip-tools UI smoke check in test mode ($0): local and proposal-only controls on Shots and editor timeline.
import { chromium } from "playwright";
import { go } from "./nav.mjs";
import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const here = dirname(fileURLToPath(import.meta.url)), repo = resolve(here, "../.."), home = mkdtempSync(join(tmpdir(), "aistudio-cliptools-"));
const port = 8832, token = "cliptooltoken", base = `http://127.0.0.1:${port}`, hdr = { "x-aistudio-token": token, "content-type": "application/json" };
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" } });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; }; const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
try {
  for (let i=0;i<40;i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch(), page = await browser.newPage();
  await page.goto(`${base}/?token=${token}`); await page.getByPlaceholder(/project-name/).fill("tool demo"); await page.getByRole("button", {name:"Create"}).click();
  const story = "# Story\n\n## Scene 1\nA small test scene.\n";
  await fetch(`${base}/api/projects/tool-demo/docs/Story.md`, { method:"PUT", headers:hdr, body:JSON.stringify({text:story}) });
  await fetch(`${base}/api/projects/tool-demo/story/convert`, { method:"POST", headers:hdr });
  const clips = join(home, "projects", "tool-demo", "clips"); mkdirSync(clips, {recursive:true}); writeFileSync(join(clips,"s01_final_a1.mp4"),"fake clip");
  await page.reload(); await go(page,"Shots");
  ok(await page.getByTestId("clip-tools").isVisible(), "a clip tools panel is available for a shot with a clip");
  ok(await page.getByLabel("Local clip tool").isVisible(), "local tool choices are labelled");
  ok(await page.getByRole("button", {name:"Propose AI tool"}).isVisible(), "AI tool action is proposal-only");
  await browser.close();
} catch (e) { console.error(e); failed = true; } finally { srv.kill("SIGTERM"); }
if (failed) process.exitCode = 1;
