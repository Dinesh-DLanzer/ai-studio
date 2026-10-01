// Help & Documentation + Integrations e2e (test mode, $0): the Help tabs hold real content, the API tab is read live from the server, and API keys
// can be made, used (with agent limits) and revoked from Settings > Integrations.
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-help-"));
const port = 8824, token = "helptoken", base = `http://127.0.0.1:${port}`;
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1", AISTUDIO_NO_KEYRING: "1" } });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const call = (m, p, key) => fetch(base + p, { method: m, headers: { authorization: `Bearer ${key}` } }).then((r) => r.status);
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch(); const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ["clipboard-read", "clipboard-write"] })).newPage();
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}/?token=${token}#/help`);
  await page.getByRole("heading", { name: /Help/ }).first().waitFor();
  const tabs = (await page.getByRole("tab").allInnerTexts()).map((s) => s.trim());
  ok(tabs.join("|") === "Getting Started|Guides|Features|API & Integrations|Troubleshooting|FAQ", "the six Help tabs are there");

  // Getting Started: benefits, setup, flow, test vs real
  await page.getByText("What AI Studio does for you").waitFor();
  ok((await page.getByText("Install the three things it needs").count()) === 1 && (await page.locator("ol >> text=Brief").count()) >= 1, "Getting Started has the setup steps and the idea-to-MP4 flow");
  ok(await page.getByRole("columnheader", { name: "Test project" }).isVisible() && await page.getByRole("columnheader", { name: "Real project" }).isVisible(), "it compares test and real projects");
  const body = await page.locator("body").innerText();
  ok(!/cancel my plan|Contact Support|Watch Intro Video|Release Notes|Feature Tour/i.test(body), "none of the old filler text is left (plans, support contact, intro video)");
  ok(!/fake/i.test(body), "no 'fake' wording in the Help page");
  await sleep(800);                                          // let the page finish its fade-in so colours are final
  let ax = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze(); ok(ax.violations.length === 0, "Getting Started: no accessibility violations" + (ax.violations.length ? ": " + ax.violations.map((v) => v.id).join() : ""));

  // the right-hand column stays in view while the page scrolls
  const railTop = async () => (await page.getByLabel("Details").boundingBox()).y;
  await page.evaluate(() => window.scrollTo(0, 700)); await sleep(300);
  const t1 = await railTop(); await page.evaluate(() => window.scrollTo(0, 1400)); await sleep(300); const t2 = await railTop();
  ok(t1 > 60 && t1 < 140 && Math.abs(t1 - t2) < 4, `the right-hand column is sticky (stays at ${Math.round(t1)}px while scrolling)`);
  await page.evaluate(() => window.scrollTo(0, 0));

  // Guides
  await page.getByRole("tab", { name: "Guides" }).click();
  ok(await page.getByTestId("guides").locator("details").count() === 7 && await page.getByTestId("guides").locator("details[open]").count() === 1, "Guides has 7 guides, the first one open");
  await page.getByText("Write or edit Story.md").click(); ok(await page.getByText("## Shared style", { exact: false }).first().isVisible(), "the Story.md guide shows the exact format");
  ax = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze(); ok(ax.violations.length === 0, "Guides: no accessibility violations" + (ax.violations.length ? ": " + ax.violations.map((v) => v.id).join() : ""));

  // Features, Troubleshooting, FAQ
  await page.getByRole("tab", { name: "Features" }).click(); await page.getByText("Model chains with fallback").waitFor(); ok(true, "Features lists the capabilities");
  await page.getByRole("tab", { name: "Troubleshooting" }).click(); ok(await page.getByTestId("trouble").locator("details").count() >= 10, "Troubleshooting has at least 10 problems with fixes");
  await page.getByTestId("trouble").getByText(/ffmpeg is not installed/).click(); ok(await page.getByText(/brew install ffmpeg/).first().isVisible(), "a problem opens to show its fix");
  await page.getByRole("tab", { name: "FAQ" }).click(); ok(await page.getByTestId("faq").locator("details").count() >= 10, "FAQ has real questions");

  // API tab: live reference
  await page.getByRole("tab", { name: "API & Integrations" }).click();
  await page.getByTestId("endpoint-list").locator("li").first().waitFor();
  const n = await page.getByTestId("endpoint-list").locator("li").count();
  ok(n >= 70, `the endpoint reference lists every route, read from the server (${n})`);
  ok(await page.getByTestId("endpoint-list").getByText("key ok").first().isVisible() && await page.getByTestId("endpoint-list").getByText("page only").first().isVisible(), "each route says whether an API key may call it");
  await page.getByLabel("Filter endpoints").fill("proposals"); const f = await page.getByTestId("endpoint-list").locator("li").count(); ok(f > 0 && f < n, "the filter narrows the list (" + f + ")");
  await page.getByLabel("Filter endpoints").fill("");
  const txt = await page.locator("main").innerText();
  ok(/-m aistudio\.mcp_server/.test(txt) && /mcpServers/.test(txt) && /opencode\.ai\/config\.json/.test(txt) && /claude mcp add ai-studio/.test(txt), "MCP setup for Claude Code, OpenCode and other clients is filled in for this install");
  await page.getByRole("button", { name: "Copy Claude Code command" }).click(); await sleep(300);
  ok((await page.evaluate(() => navigator.clipboard.readText())).startsWith("claude mcp add ai-studio"), "the Copy button puts the command on the clipboard");
  ax = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze(); ok(ax.violations.length === 0, "API tab: no accessibility violations" + (ax.violations.length ? ": " + ax.violations.map((v) => `${v.id}(${v.nodes.length}) ${v.nodes[0].target}`).join("; ") : ""));
  await page.goto(`${base}/#/help?tab=api`); await page.getByRole("tab", { name: "API & Integrations", selected: true }).waitFor(); ok(true, "a link can open the API tab directly (#/help?tab=api)");

  // Settings > Integrations: make, use and revoke a key
  await page.goto(`${base}/#/settings`); await page.getByRole("heading", { name: "Connect an AI agent (MCP)" }).waitFor();
  ok(await page.getByRole("tab", { name: "OpenCode" }).isVisible(), "Settings has an Integrations section with MCP setup");
  await page.getByRole("button", { name: /The \d+ tools|Show the \d+ tools/ }).click(); ok(await page.getByTestId("mcp-tools").getByText("propose", { exact: true }).isVisible() && await page.getByTestId("mcp-tools").getByText("approve_budget").count() === 0, "the tool list shows propose and no approval tool");
  await page.getByTestId("new-key").click(); await page.getByLabel("API key name").fill("e2e script"); await page.getByRole("button", { name: "Create key" }).last().click();
  await page.getByTestId("new-key-result").waitFor();
  const key = await page.getByTestId("new-key-result").locator("code").innerText(); ok(/^aisk_/.test(key), "a new key is shown once");
  await page.getByRole("button", { name: "I saved it" }).click();
  const listed = await page.getByTestId("key-list").innerText(); ok(listed.includes("e2e script") && !listed.includes(key), "the list shows the key's name and first characters, never the key");
  ok((await call("GET", "/api/projects", key)) === 200 && (await call("GET", "/api/keys", key)) === 403 && (await call("POST", "/api/projects/x/budget/approve", key)) === 403, "the key works for reading but is refused for approvals and key management");
  await page.getByRole("button", { name: "Revoke e2e script" }).click(); await page.getByRole("dialog").getByRole("button", { name: "Revoke" }).click();
  await page.waitForFunction(() => !document.querySelector("[data-testid=key-list]"));
  ok((await call("GET", "/api/projects", key)) === 401, "revoking a key stops it at once");
  ax = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze(); ok(ax.violations.length === 0, "Settings with Integrations: no accessibility violations" + (ax.violations.length ? ": " + ax.violations.map((v) => `${v.id}(${v.nodes.length}) ${v.nodes[0].target}`).join("; ") : ""));
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  await browser.close();
} catch (e) { console.log("FAIL exception: " + (e.stack || e)); failed = true; }
finally { srv.kill(); }
process.exit(failed ? 1 : 0);
