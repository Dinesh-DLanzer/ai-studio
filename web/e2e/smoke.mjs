// End-to-end smoke test in a real headless browser against a test-mode server (costs $0).
// Usage: node e2e/smoke.mjs   (needs: web built, .venv with fastapi, playwright chromium)
import { chromium } from "playwright";
import { go } from "./nav.mjs";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-e2e-"));
const shots = process.env.SHOTS_DIR || join(tmpdir(), "aistudio-shots");
mkdirSync(shots, { recursive: true });
const port = 8811, token = "e2etoken";
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" } });
let failed = false, pageRef = null;
const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`http://127.0.0.1:${port}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } }); pageRef = page;
  page.on("dialog", (d) => d.accept("test reason"));
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`http://127.0.0.1:${port}/?token=${token}`);
  await page.getByText("No projects yet").waitFor();
  ok(true, "projects page renders with the token");
  await page.screenshot({ path: join(shots, "1-projects.png") });

  await page.getByPlaceholder(/project-name/).fill("demo"); await page.getByRole("button", { name: "Create" }).click();
  await page.getByRole("log", { name: "Conversation" }).waitFor(); ok(true, "project created and opened");

  await go(page, "Story");
  const story = readFileSync(join(here, "story.md"), "utf-8");
  await page.waitForFunction(() => document.querySelector("textarea")?.value.includes("STORYBOARD"));
  await page.locator("textarea").first().fill(story);
  await page.getByRole("button", { name: "Save", exact: true }).first().click();
  await page.getByText("Saved").first().waitFor();
  // saving Story.md now rebuilds the shots and images by itself (there is no separate Convert button any more)
  await page.getByText(/Updated: 3 shots, 1 images/).waitFor(); ok(true, "story converted to 3 shots and 1 image");
  await page.getByRole("dialog").getByText("Set the budget").first().waitFor(); ok(true, "budget popup opened automatically after the story was converted");
  await page.getByRole("dialog").getByText(/estimated total/).waitFor();
  await page.screenshot({ path: join(shots, "2b-budget.png") });
  await page.getByRole("dialog").getByRole("button", { name: /Approve budget/ }).click(); await page.getByText(/Budget approved/).first().waitFor(); ok(true, "budget approved from the popup");
  await go(page, "Costs"); await page.getByText("approved", { exact: true }).first().waitFor(); ok(true, "Costs tab shows the approved budget");
  await page.screenshot({ path: join(shots, "3-costs.png") });

  await go(page, "Assets");
  await page.getByRole("button", { name: "Generate with AI", exact: true }).first().click();
  await page.getByText("Approve this paid action?").waitFor();
  ok(await page.getByText("TEST PROJECT: no real money").first().isVisible(), "proposal dialog shows price and TEST PROJECT");
  await new Promise((r) => setTimeout(r, 900)); await page.screenshot({ path: join(shots, "4-proposal.png") });
  await page.getByRole("button", { name: /Approve and run/ }).click();
  await page.getByText("Approve this paid action?").waitFor({ state: "hidden" }); ok(true, "popup closes as soon as the action is approved");
  await page.getByText(/image s01: Done/).waitFor({ timeout: 15000 }); ok(true, "a toast reports the finished image");
  await page.locator('img[alt="s01 preview"]').waitFor(); ok(true, "image generated (test mode) and shown in the preview");
  await page.screenshot({ path: join(shots, "5-assets.png") });

  await go(page, "Shots");
  await page.getByRole("button", { name: "Generate clip", exact: true }).first().click();
  await page.getByRole("button", { name: /Approve and run/ }).click();
  await page.getByText(/clip s01: Done/).waitFor({ timeout: 15000 });
  await page.locator('video[src*="s01_final_a1.mp4"]').waitFor({ state: "attached" }); ok(true, "clip generated (test mode)");
  await page.getByRole("region", { name: "Shot s01" }).getByRole("button", { name: "Re-check" }).click();
  await page.getByRole("button", { name: /Approve and run/ }).click();
  await page.getByText(/vision: pass/).first().waitFor({ timeout: 15000 }); ok(true, "vision review shown as a badge");
  await page.getByRole("button", { name: "Approve this clip" }).click();
  await page.getByText("approved", { exact: true }).first().waitFor(); ok(true, "shot approved");
  await page.screenshot({ path: join(shots, "6-shots.png"), fullPage: true });

  await page.getByRole("button", { name: "Discard", exact: true }).first().click();
  await page.getByRole("dialog").getByRole("textbox").fill("test reason"); await page.getByRole("dialog").getByRole("button", { name: "Discard", exact: true }).click();
  await go(page, "Discarded");
  await page.getByText("s01_final_a1.mp4").first().waitFor(); ok(true, "discard moves the clip to the Discarded tab");
  await page.screenshot({ path: join(shots, "7-discarded.png") });
  await page.getByRole("button", { name: "Restore" }).first().click();
  await go(page, "Overview");
  await page.getByText("TODO", { exact: true }).waitFor(); ok(true, "restore works and overview renders with the TODO list");
  await page.screenshot({ path: join(shots, "8-overview.png") });
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  await browser.close();
} catch (e) { console.log("FAIL exception: " + e.message.split("\n")[0]); failed = true; if (pageRef) { await pageRef.screenshot({ path: join(shots, "FAIL.png") }).catch(() => {}); console.log("PAGE TEXT: " + (await pageRef.locator("body").innerText().catch(() => "")).slice(0, 600).replace(/\n+/g, " | ")); } }
finally { srv.kill(); }
process.exit(failed ? 1 : 0);
