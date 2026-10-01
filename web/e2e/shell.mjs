// Shell e2e (test mode, $0): routing, responsive layouts (desktop/tablet/phone), drawer, command box, brand, dark-only, accessibility.
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-shell-"));
const shots = process.env.SHOTS_DIR || join(tmpdir(), "aistudio-shots"); mkdirSync(shots, { recursive: true });
const port = 8818, token = "shelltoken", base = `http://127.0.0.1:${port}`;
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" } });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const hscroll = (page) => page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}/?token=${token}`);
  await page.getByPlaceholder(/project-name/).fill("shell"); await page.getByRole("button", { name: "Create" }).click();
  await page.waitForFunction(() => location.hash === "#/p/shell/chat"); ok(true, "creating a project opens its Chat route (#/p/shell/chat)");

  // brand + dark only
  ok((await page.title()) === "AI Studio", "the page title is AI Studio");
  ok(await page.getByText("AI Studio").first().isVisible(), "the brand reads AI Studio");
  ok(!/\bad[- ]?studio\b/i.test(await page.locator("body").innerText()) && !(await page.locator("body").innerText()).includes("Ai Studio"), "the app only ever says 'AI Studio' (no old spelling is visible)");
  ok(await page.evaluate(() => document.documentElement.classList.contains("dark")), "the UI is dark only (html.dark)");
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  ok(/rgb\((\d+), (\d+), (\d+)\)/.test(bg) && Math.max(...bg.match(/\d+/g).slice(0, 3).map(Number)) < 40, "the background is near-black");

  // sidebar routes + counts
  for (const [link, hash] of [["Storyboard", "/storyboard"], ["Assets", "/assets"], ["Shots", "/shots"], ["Costs", "/costs"], ["Discarded", "/discarded"], ["Overview", ""]]) {
    await page.locator("nav[aria-label=Project]").getByRole("link", { name: new RegExp(`^${link}`) }).click();
    await page.waitForFunction((h) => location.hash === `#/p/shell${h}`, hash);
  }
  ok(true, "every sidebar link changes the route");
  await page.goBack(); await page.waitForFunction(() => location.hash === "#/p/shell/discarded"); ok(true, "the browser back button works");
  await page.goto(`${base}/#/p/shell/nonsense`); await page.getByTestId("not-found").waitFor(); ok(await page.getByRole("heading", { name: "Page not found" }).isVisible() && await page.locator("nav[aria-label=Project]").isVisible(), "an unknown page inside a project shows a 404 with the project sidebar kept");
  await page.goto(`${base}/#/nonsense`); await page.getByTestId("not-found").waitFor(); await page.getByRole("link", { name: /All projects/ }).first().click(); await page.waitForFunction(() => location.hash === "#/"); ok(true, "an unknown address shows a 404 page with a way back to all projects");

  // top bar: GitHub star link, settings via the sidebar
  await page.goto(`${base}/#/p/shell`);
  const gh = page.getByRole("link", { name: "Star AI Studio on GitHub" }); ok((await gh.getAttribute("href")).startsWith("https://github.com/") && (await gh.getAttribute("target")) === "_blank", "the top bar GitHub icon opens the repository in a new tab");
  await page.getByRole("link", { name: "Settings" }).first().click(); await page.waitForFunction(() => location.hash === "#/settings"); ok(true, "Settings opens from the sidebar");
  await page.getByRole("heading", { name: "Settings", exact: true }).waitFor();
  await page.keyboard.press("Control+k"); await page.getByRole("dialog").getByLabel("Command or idea").waitFor(); ok(true, "Ctrl/Cmd+K opens the command box");
  await page.keyboard.press("Escape"); await page.getByRole("dialog").waitFor({ state: "hidden" });
  await page.goto(`${base}/#/p/shell`); await page.getByRole("button", { name: "Open command palette" }).click();
  await page.getByLabel("Command or idea").fill("Create a 45s ad for my tea shop");
  await page.getByRole("option", { name: /Start a new project/ }).waitFor(); ok(true, "typing an idea offers to start a new project");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => /^#\/p\/create-a-45s-ad\/chat/.test(location.hash), null, { timeout: 15000 }); ok(true, "the idea creates a project and opens its chat");
  await page.getByText("Create a 45s ad for my tea shop", { exact: true }).first().waitFor({ timeout: 15000 }); ok(true, "the idea is sent to the producer as the first message");
  await page.getByText(/What is the brand|brand or business/i).first().waitFor({ timeout: 15000 }); ok(true, "the producer replies with its first question");
  await page.getByRole("button", { name: /^Notifications/ }).click(); await page.getByText("Tara is replying").first().waitFor(); ok(true, "the bell lists the chat process"); await page.keyboard.press("Escape");

  // the top-bar button opens the new-project popup
  await page.goto(`${base}/#/`); await page.getByRole("button", { name: /Generate New Video/ }).click();
  await page.getByRole("dialog").getByLabel("New project name").fill("popupvideo"); await page.getByRole("dialog").getByRole("button", { name: "Create" }).click();
  await page.waitForFunction(() => location.hash === "#/p/popupvideo/chat", null, { timeout: 15000 }); ok(true, "Generate New Video opens a popup that creates a project and opens its chat");

  // kit + help pages
  await page.goto(`${base}/#/kit`); await page.getByText("Design kit").waitFor(); ok(true, "the design kit page renders");
  await page.goto(`${base}/#/help`); await page.getByText("Safety rules").waitFor(); ok(true, "the Help page renders");

  // responsive
  await page.goto(`${base}/#/p/shell`); await page.getByText("TODO", { exact: true }).waitFor();
  for (const [label, w, h] of [["desktop", 1536, 900], ["laptop", 1280, 800], ["tablet", 820, 1100], ["phone", 390, 844], ["small phone", 320, 640]]) {
    await page.setViewportSize({ width: w, height: h }); await sleep(250);
    const sidebarVisible = await page.locator("aside[aria-label=Sidebar]").isVisible();
    const menuVisible = await page.getByRole("button", { name: "Open menu" }).isVisible();
    ok(w >= 1024 ? sidebarVisible && !menuVisible : !sidebarVisible && menuVisible, `${label} (${w}px): ${w >= 1024 ? "sidebar shown" : "sidebar hidden, menu button shown"}`);
    ok(!(await hscroll(page)), `${label} (${w}px): no horizontal scrolling`);
    if (label === "phone") await page.screenshot({ path: join(shots, "20-phone.png") });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open menu" }).click();
  await page.getByRole("dialog").getByRole("link", { name: /^Assets/ }).click();
  await page.waitForFunction(() => location.hash === "#/p/shell/assets"); ok(true, "the phone drawer navigates, and closes");
  await page.getByRole("button", { name: "Close menu" }).waitFor({ state: "hidden" });
  for (const [route, label, marker] of [["#/p/shell/assets", "Assets", /Characters/], ["#/p/shell/shots", "Shots", /All Shots/], ["#/p/shell/chat", "Chat", /Chat with/], ["#/settings", "Settings", /Model Configuration/], ["#/p/shell/costs", "Costs", /Spend: used vs discarded/]]) {
    await page.goto(`${base}/${route}`); await page.getByText(marker).first().waitFor(); await sleep(300);
    ok(!(await hscroll(page)), `phone: ${label} page has no horizontal scrolling`);
  }

  // accessibility (serious and critical only)
  await page.setViewportSize({ width: 1440, height: 900 });
  for (const [route, label] of [["#/", "projects"], ["#/p/shell", "overview"], ["#/p/shell/assets", "assets"], ["#/settings", "settings"], ["#/kit", "kit"]]) {
    await page.goto(`${base}/${route}`); await sleep(900);
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    const bad = r.violations.filter((v) => ["serious", "critical"].includes(v.impact));
    ok(bad.length === 0, `accessibility (${label}): no serious or critical violations` + (bad.length ? ": " + bad.map((v) => `${v.id}(${v.nodes.length})`).join(", ") : ""));
  }
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  await browser.close();
} catch (e) { console.log("FAIL exception: " + e.message.split("\n").slice(0, 3).join(" | ")); failed = true; }
finally { srv.kill(); }
process.exit(failed ? 1 : 0);
