// First-run e2e: an empty workspace (no projects, no provider) must force provider + model setup, then open an empty projects page.
// The server is started WITHOUT AISTUDIO_ALL_TEST (that variable switches the gate off for tests/CI), so this is the real first-run path.
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { spawn } from "node:child_process";
import { mkdtempSync, existsSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-setup-")); const secrets = mkdtempSync(join(tmpdir(), "aistudio-setup-secrets-"));
const shots = process.env.SHOTS_DIR || join(tmpdir(), "aistudio-shots"); mkdirSync(shots, { recursive: true });
const port = 8823, token = "setuptoken", base = `http://127.0.0.1:${port}`, KEY = "AIza-setup-test-key-9876";
const env = { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_NO_NETWORK: "1", AISTUDIO_NO_KEYRING: "1", AISTUDIO_SECRETS_DIR: secrets };
delete env.AISTUDIO_ALL_TEST;
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const call = (m, p, b) => fetch(base + p, { method: m, headers: { "x-aistudio-token": token, "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined }).then((r) => r.json());
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  ok((await call("GET", "/api/projects")).projects.length === 0, "the workspace starts with no projects and no provider");
  const browser = await chromium.launch(); const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}/?token=${token}`);
  await page.getByTestId("welcome").waitFor();
  ok(await page.getByRole("heading", { name: /Welcome to AI Studio/ }).isVisible() && await page.getByTestId("choose-setup").isVisible() && await page.getByTestId("choose-trial").isVisible(), "with no provider and no projects the app first asks: set up a provider, or try a test project");
  ok(await page.locator("aside.sidebar, header.topbar").count() === 0, "no app navigation is shown while the choice is open");
  await page.screenshot({ path: join(shots, "welcome.png"), fullPage: true });
  const axw = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  ok(axw.violations.length === 0, "no accessibility violations on the welcome choice" + (axw.violations.length ? ": " + axw.violations.map((v) => `${v.id}(${v.nodes.length})`).join("; ") : ""));

  // path B: try a test project (no provider, no key)
  await page.getByTestId("choose-trial").click();
  await page.getByTestId("trial-banner").waitFor(); await page.getByText("No projects yet").waitFor();
  ok((await page.getByTestId("trial-banner").innerText()).includes("No provider connected"), "the test path opens the app with a banner that says new projects are simulated and free");
  ok(await page.getByLabel("Test project").isDisabled() && await page.getByLabel("Test project").isChecked(), "the Test project switch is on and locked while no provider is connected");
  await page.getByLabel("New project name").fill("trial"); await page.getByRole("button", { name: "Create" }).click();
  await page.waitForFunction(() => location.hash === "#/p/trial/chat"); ok(true, "a project can be created without any provider (it becomes a test project)");
  await page.reload(); await page.getByTestId("trial-banner").waitFor(); ok(true, "the choice is remembered after a reload");
  await page.goto(`${base}/#/`); await page.getByRole("button", { name: /Actions for trial/ }).waitFor(); ok((await call("GET", "/api/projects")).projects.length === 1, "the test-mode project exists");
  // from the banner back to setup, then back to the choice
  await page.getByTestId("trial-banner").getByRole("button", { name: "Set up a provider" }).click();
  await page.getByTestId("setup").waitFor(); ok(true, "the banner leads to the setup screen");
  await page.getByTestId("setup-back").click(); await page.getByTestId("welcome").waitFor(); ok(true, "Back returns to the choice");

  // path A: set up a provider (forced: it cannot be skipped from here)
  await page.getByTestId("choose-setup").click();
  await page.getByTestId("setup").waitFor();
  ok(await page.getByRole("heading", { name: /Set up AI Studio/ }).isVisible(), "choosing Set up a provider shows the setup screen");
  ok(await page.locator("aside.sidebar, header.topbar").count() === 0, "no app navigation is shown while setup is open");
  ok(await page.getByTestId("setup-continue").isDisabled(), "Continue is disabled until a provider and a chat model exist");
  ok(await page.getByText("Model Configuration unlocks after you connect a provider").isVisible(), "model choice unlocks after a provider is connected");
  await page.goto(`${base}/#/p/anything/shots`); await page.getByTestId("setup").waitFor(); ok(true, "typing another address still shows setup (it cannot be skipped)");
  const ax = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  ok(ax.violations.length === 0, "no accessibility violations on the setup screen" + (ax.violations.length ? ": " + ax.violations.map((v) => `${v.id}(${v.nodes.length}) ${v.nodes[0].target}`).join("; ") : ""));
  await page.screenshot({ path: join(shots, "setup-empty.png"), fullPage: true });

  // step 1: provider through the dialog
  await page.getByRole("button", { name: /Add Provider/ }).first().click();
  await page.getByRole("button", { name: /Google Gemini/ }).click();
  await page.getByPlaceholder(/Enter your api key/i).fill(KEY);
  await page.getByRole("button", { name: /Save & test/ }).click();
  await page.getByRole("button", { name: /Replace key/ }).waitFor(); ok(true, "step 1: the provider and its key are saved");
  ok(await page.getByTestId("setup-continue").isDisabled(), "a key alone is not enough: Continue stays disabled");
  // step 2: a chat model
  await call("POST", "/api/providers/google-gemini/models", { id: "gem-chat", capability: "chat" });
  await page.reload(); await page.getByTestId("setup").waitFor();
  const chat = page.getByText("Text generation, planning, ideas").locator("xpath=ancestor::*[contains(@class,'panel')][1]");
  await chat.getByRole("button", { name: /Add model/ }).click();
  await page.getByRole("button", { name: "Add gem-chat" }).click();
  await page.waitForFunction(() => !document.querySelector('[data-testid="setup-continue"]')?.disabled);
  ok(true, "step 2: choosing a chat model enables Continue");
  ok(await page.getByText("You are ready").isVisible(), "the screen says the user is ready");
  await page.screenshot({ path: join(shots, "setup-ready.png"), fullPage: true });
  await page.getByTestId("setup-continue").click();

  // the app opens on an empty projects page
  await page.goto(`${base}/#/`); await page.getByRole("button", { name: /Actions for trial/ }).waitFor();
  ok(await page.getByTestId("trial-banner").count() === 0, "once a provider and chat model exist the trial banner is gone");
  ok(await page.getByLabel("Test project").isEnabled(), "and the Test project switch works again");
  await page.reload(); await page.getByRole("button", { name: /Actions for trial/ }).waitFor(); ok(true, "after a reload the app opens straight away because setup is complete");
  await page.getByLabel("New project name").first().fill("first"); await page.getByRole("button", { name: "Create" }).first().click();
  await page.waitForFunction(() => location.hash === "#/p/first/chat"); ok(true, "the first project can be created");
  await page.goto(`${base}/#/p/first`); await page.getByText("Overview").first().waitFor(); ok(true, "an empty project opens");
  for (const r of ["storyboard", "assets", "shots", "review", "costs", "discarded"]) {
    await page.goto(`${base}/#/p/first/${r}`); await page.waitForTimeout(500);
    ok(await page.locator("body").innerText().then((t) => !/something went wrong|undefined|NaN/i.test(t)), `an empty project's ${r} page renders without errors`);
  }
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  await browser.close();
} catch (e) { console.log("FAIL exception: " + (e.stack || e)); failed = true; }
finally { srv.kill(); }
process.exit(failed ? 1 : 0);
