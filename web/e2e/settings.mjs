// Settings e2e (test mode, $0, no network): connect providers, secrets stay secret, chains + fallback order, prices, limits, accessibility.
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-settings-"));
const port = 8828, token = "settok", base = `http://127.0.0.1:${port}`; const KEY = "AIzaE2ESECRETKEYVALUE1234567";
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1", AISTUDIO_NO_KEYRING: "1", AISTUDIO_SECRETS_DIR: join(home, "sec") } });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const call = (m, p, b) => fetch(base + p, { method: m, headers: { "x-aistudio-token": token, "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined }).then((r) => r.json());
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch(); const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}/?token=${token}#/settings`);
  await page.getByRole("heading", { name: "Settings", exact: true }).waitFor();
  await page.getByText("Connect your first provider").first().waitFor();
  ok(await page.getByText("Connect your first provider").first().isVisible() && (await page.getByText("Built-in test").count()) === 0, "a fresh workspace shows no providers (the built-in fake one is hidden)");

  // add a provider through the dialog
  await page.getByRole("button", { name: /Add Provider/ }).first().click();
  await page.getByRole("button", { name: /Google Gemini/ }).click();
  await page.getByPlaceholder(/Enter your api key/i).fill(KEY);
  await page.getByRole("button", { name: /Save & test/ }).click();
  await page.getByText("Google Gemini").first().waitFor();
  await page.getByRole("button", { name: /Replace key/ }).waitFor(); ok(true, "the provider was added and its key is saved");
  ok(!(await page.content()).includes(KEY), "the saved key is never shown in the page");
  ok(await page.evaluate(() => (document.body.innerText + [...document.querySelectorAll("input")].map((i) => i.value).join(" ")).includes("4567")), "only the last 4 characters of the key are shown");
  ok(!JSON.stringify(await call("GET", "/api/providers")).includes(KEY), "the API never returns the key");

  // add a model by typing its id: it must land in the chain, not just in a list
  const chatCard = page.getByText("Text generation, planning, ideas").locator("xpath=ancestor::*[contains(@class,'panel')][1]");
  await chatCard.getByRole("button", { name: /Add model/ }).click();
  await page.getByRole("button", { name: /Model not listed/ }).click();
  await page.getByPlaceholder(/vendor\/model-name/).fill("typed-chat-model"); await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByRole("list", { name: /chat model chain/ }).getByText("typed-chat-model").waitFor({ timeout: 8000 });
  ok((await call("GET", "/api/roles")).roles.chat.chain.some((c) => c.model === "typed-chat-model"), "a model typed by id is added to the chain and saved");
  await chatCard.getByRole("button", { name: /Add fallback/ }).click(); await page.getByRole("button", { name: /Model not listed/ }).click();
  await page.getByPlaceholder(/vendor\/model-name/).fill("typed-chat-model"); await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByText(/already in the chain/).first().waitFor(); ok(true, "typing an id that is already in the chain says so");
  await page.keyboard.press("Escape");

  // models and prices (no network: add the model by id), then a fallback chain
  await call("POST", "/api/providers/google-gemini/models", { id: "veo-a", capability: "video" });
  await call("POST", "/api/providers/google-gemini/models", { id: "veo-b", capability: "video" });
  await call("PUT", "/api/prices/google-gemini/veo-b", { kind: "video", per_second: { "720p": 0.2 } });
  await page.reload();
  const videoCard = page.getByText("Text to video, image to video").locator("xpath=ancestor::*[contains(@class,'panel')][1]");
  await videoCard.getByRole("button", { name: /Add model/ }).click();
  await page.getByRole("button", { name: "Add veo-a" }).click();
  await page.getByRole("list", { name: /video model chain/ }).getByText("veo-a").waitFor(); ok(true, "a model is added to the video chain");
  await page.getByRole("button", { name: "Set price for veo-a" }).click();
  await page.getByLabel("Dollars per second (720p)").fill("0.03");
  await page.getByRole("button", { name: /^Save/ }).click();
  await page.getByText("$0.03/s").waitFor(); ok(true, "setting a price shows it on the chain row");
  await videoCard.getByRole("button", { name: /Add fallback/ }).click();
  await page.getByRole("button", { name: "Add veo-b" }).click();
  await page.getByText("Costs more").waitFor(); ok(true, "a more expensive fallback is flagged as needing a new approval");
  await page.getByRole("button", { name: "Move veo-b up" }).click();
  await page.waitForFunction(() => document.querySelector('[aria-label$="video model chain, in order of use"] li')?.textContent.includes("veo-b"));
  ok((await call("GET", "/api/roles")).roles.video.chain[0].model === "veo-b", "reordering the chain is saved (veo-b is now primary)");
  await page.getByRole("button", { name: "Remove veo-a from video chain" }).click();
  for (let i = 0; i < 40 && (await call("GET", "/api/roles")).roles.video.chain.length !== 1; i++) await sleep(150);
  ok((await call("GET", "/api/roles")).roles.video.chain.length === 1, "removing a model is saved");

  // limits
  await page.getByLabel("AI spending cap").fill("2.5"); await page.getByLabel("AI spending cap").blur();
  await page.getByText("Saved.").first().waitFor();
  ok((await call("GET", "/api/roles")).ai_cap_usd === 2.5, "the spending cap is saved");
  await page.getByLabel("Allow paid models").click(); await page.getByRole("button", { name: "Allow", exact: true }).click();
  await page.waitForFunction(async () => (await (await fetch("/api/roles", { headers: { "x-aistudio-token": "settok" } })).json()).allow_paid === true);
  ok(true, "allowing paid text models asks for confirmation, then saves");

  // delete refused while used
  const del = await fetch(`${base}/api/providers/google-gemini`, { method: "DELETE", headers: { "x-aistudio-token": token } });
  ok(del.status === 400, "a provider that is in use cannot be removed without force");

  const axe = await new AxeBuilder({ page }).analyze();
  const bad = axe.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
  ok(bad.length === 0, "no serious accessibility violations on Settings" + (bad.length ? ": " + bad.map((v) => v.id + "(" + v.nodes.length + ")").join(", ") : ""));
  await page.setViewportSize({ width: 390, height: 800 }); await page.waitForTimeout(300);
  ok(!(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)), "Settings has no horizontal scroll on a phone");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  await browser.close();
} catch (e) { console.log("FAIL exception: " + e.message.split("\n")[0]); failed = true; }
finally { srv.kill(); }
process.exit(failed ? 1 : 0);
