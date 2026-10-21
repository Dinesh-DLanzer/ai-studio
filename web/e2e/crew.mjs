// Crew page e2e (test mode, $0, no paid action): plan dialog, disabled Start with reasons, a free run, Settings > Agents, @agent hint.
import { chromium } from "playwright";
import { go } from "./nav.mjs";
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-crew-"));
const port = 8821, token = "crewtoken", base = `http://127.0.0.1:${port}`;
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" } });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const hdr = { "x-aistudio-token": token, "content-type": "application/json" };
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch(); const page = await browser.newPage({ viewport: { width: 1300, height: 950 } });
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}/?token=${token}`);
  await page.getByPlaceholder(/project-name/).fill("crewdemo"); await page.getByRole("button", { name: "Create" }).click();
  await page.getByRole("log", { name: "Conversation" }).waitFor();

  // chat hint: typing @ offers the agent ids
  await page.getByLabel("Message").fill("@");
  await page.getByTestId("agent-hints").waitFor(); ok((await page.getByTestId("agent-hints").getByRole("button").count()) >= 8, "typing @ in Chat lists the crew agents");
  await page.getByLabel("Message").fill("");

  await go(page, "Crew");
  await page.getByTestId("stage-generate_clips").click();
  await page.getByTestId("run-plan").waitFor(); ok(true, "Generate clips opens the run plan dialog");
  ok(/so far/.test(await page.getByTestId("plan-paid-total").innerText()), "the paid total is labelled 'so far'");
  ok(await page.getByTestId("plan-hash").isVisible(), "the plan hash is shown");
  const opts = await page.getByTestId("autonomy").locator("option").allInnerTexts();
  ok(opts.length === 2 && /Copilot/.test(opts[0]) && /Assist/.test(opts[1]) && !opts.some((o) => /autopilot/i.test(o)), "autonomy offers Copilot (default) and Assist only");
  ok(await page.getByTestId("start-run").isDisabled(), "Start is disabled while prerequisites are missing");
  ok(/storyboard/.test(await page.getByTestId("start-blocked").innerText()), "the reason is shown");
  await page.keyboard.press("Escape");

  // a free run (the test-mode LLM may not produce valid actions: any end state is fine)
  const r = await fetch(`${base}/api/projects/crewdemo/brief`, { method: "PUT", headers: hdr, body: JSON.stringify({ brand: "Chai Corner", goal: "walk-ins" }) });
  ok(r.ok, "brief saved through the API");
  await page.getByTestId("stage-write_storyboard").click();
  await page.getByTestId("run-plan").waitFor();
  await page.waitForFunction(() => { const b = document.querySelector("[data-testid=start-run]"); return b && !b.disabled; }, null, { timeout: 8000 });
  ok(true, "Start is enabled when nothing is missing");
  await page.getByTestId("start-run").click();
  await page.getByTestId("run-view").waitFor({ timeout: 10000 }); ok(true, "starting opens the run view");
  await page.waitForFunction(() => /done|error|stopped|awaiting checkpoint/.test(document.querySelector("[data-testid=run-view]")?.innerText || ""), null, { timeout: 30000 });
  ok(true, "the run reaches an end state");
  ok((await page.getByTestId("batch-card").count()) === 0, "no batch card without proposals");

  // Settings > Agents
  await page.goto(`${base}/#/settings`);
  await page.getByTestId("crew-agent-writer").waitFor(); ok(true, "Settings lists the crew agents");
  await page.getByTestId("crew-agent-writer").locator("summary").click();
  ok(await page.getByText(/Tools can never be changed/).last().isVisible(), "the tools-are-read-only note is shown");
  ok((await page.getByRole("button", { name: /Reset .* to default/ }).count()) >= 1, "reset to default control exists");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join("; ") : ""));
  await browser.close();
} finally { srv.kill(); }
process.exit(failed ? 1 : 0);
