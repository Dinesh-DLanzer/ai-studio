// Clip-tools UI smoke check in test mode ($0): local and proposal-only controls on Shots and editor timeline.
import { chromium } from "playwright";
import { go } from "./nav.mjs";
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), repo = resolve(here, "../.."), home = mkdtempSync(join(tmpdir(), "aistudio-cliptools-"));
const port = 8832, token = "cliptooltoken", base = `http://127.0.0.1:${port}`, hdr = { "x-aistudio-token": token, "content-type": "application/json" };
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" } });
  srv.stderr?.on("data", (d) => console.log("SERVER STDERR:", d.toString()));
  srv.stdout?.on("data", (d) => console.log("SERVER STDOUT:", d.toString()));
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; }; const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch(), page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));

  await page.goto(`${base}/?token=${token}`);
  await page.getByPlaceholder(/project-name/).fill("tooldemo");
  await page.getByRole("button", { name: "Create" }).click();
  // Wait for project to fully load (conversation log appears)
  await page.getByRole("log", { name: "Conversation" }).waitFor({ timeout: 15000 });

  const story = `# Story\n\n## Shot 01 — 0:00–0:04\n### Purpose: HOOK\n\n**Visual**\nTest scene.\n\n**Camera**\nStatic.\n\n**Action**\nNone.\n\n**AI Video Prompt**\n> SUBJECT: test.\n\n---`;
  await fetch(`${base}/api/projects/tooldemo/docs/Story.md`, { method: "PUT", headers: hdr, body: JSON.stringify({ text: story }) });
  await fetch(`${base}/api/projects/tooldemo/story/convert`, { method: "POST", headers: hdr });

  // Create a real 4s clip file for the first shot (s01) so ffprobe can read its length
  const clips = join(home, "projects", "tooldemo", "clips");
  mkdirSync(clips, { recursive: true });
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=4:r=10", "-pix_fmt", "yuv420p", join(clips, "s01_final_a1.mp4")]);

  await page.reload();
  await go(page, "Shots");

  // Select the first shot (s01) - click on the shot in the list (div with role=button)
  await page.getByRole("button", { name: "Open shot s01" }).first().click();

  // Wait for the clip tools panel to appear
  await page.getByTestId("clip-tools").waitFor({ timeout: 15000 });
  ok(true, "a clip tools panel is available for a shot with a clip");

  // Check local tool section
  ok(await page.getByLabel("Local clip tool").isVisible(), "local tool choices are labelled");
  ok(await page.getByRole("button", { name: "Run free tool" }).isVisible(), "run free tool button exists");

  // Check AI tool section - use exact match for the select
  ok(await page.locator('select[aria-label="AI clip tool"]').first().isVisible(), "AI tool choices are labelled");
  ok(await page.getByLabel("AI clip tool prompt").isVisible(), "AI tool prompt input exists");
  ok(await page.getByRole("button", { name: "Propose AI tool" }).isVisible(), "AI tool action is proposal-only");

  // Test local tool: run "speed" tool (free, creates new version)
  await page.getByLabel("Local clip tool").selectOption("speed");
  // Listen for the API response
  const responsePromise = page.waitForResponse(response => response.url().includes('/local-tool') && response.request().method() === 'POST');
  await page.getByRole("button", { name: "Run free tool" }).click();
  const response = await responsePromise;
  const respText = await response.text().catch(() => "");
  console.log("LOCAL TOOL RESPONSE:", response.status(), respText);
  if (response.status() !== 200) {
    console.log("SERVER ERROR - check server logs");
  }
  await page.getByText(/Free local version saved:/).waitFor({ timeout: 10000 });
  ok(true, "local tool runs free and creates a new version");

  // Reload to reset the clip to original
  await page.reload();
  await go(page, "Shots");
  await page.getByRole("button", { name: "Open shot s01" }).first().click();
  await page.getByTestId("clip-tools").waitFor({ timeout: 10000 });

  // Test AI tool: propose "upscale_ai" on the original clip (creates proposal with price)
  await page.locator('select[aria-label="AI clip tool"]').first().selectOption("upscale_ai");
  // Listen for the API response
  const aiResponsePromise = page.waitForResponse(response => response.url().includes('/clips/') && response.url().includes('/tool') && response.request().method() === 'POST');
  await page.getByRole("button", { name: "Propose AI tool" }).click();
  const aiResponse = await aiResponsePromise;
  const aiRespText = await aiResponse.text().catch(() => "");
  console.log("AI TOOL RESPONSE:", aiResponse.status(), aiRespText);
  // The AI tool should create a proposal - the modal dialog opens
  await page.getByRole("heading", { name: "Approve this paid action?" }).waitFor({ timeout: 10000 });
  ok(true, "AI tool creates a proposal with a price");
  await page.getByRole("button", { name: "Cancel" }).click();

  // Test consent-gated tool: character_swap (requires consent for subject)
  // Without consent, it should show a refusal/error
  await page.locator('select[aria-label="AI clip tool"]').first().selectOption("character_swap");
  await page.getByLabel("AI clip tool prompt").fill("swap character");
  await page.getByRole("button", { name: "Propose AI tool" }).click();
  // Should show an error about missing consent
  await page.getByText(/needs the person's name as 'subject'.*consent is required|consent/).waitFor({ timeout: 10000 });
  ok(true, "consent-gated tool shows a refusal reason");

  await browser.close();
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  console.log("FAIL exception: " + e.message.split("\n").slice(0, 3).join(" | "));
  failed = true;
} finally {
  srv.kill("SIGTERM");
}
if (failed) process.exitCode = 1;