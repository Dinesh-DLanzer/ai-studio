// Formats and brand kits e2e (test mode, $0): create a kit from a logo in Settings, edit it, start a project from a format + kit, delete the kit to the trash.
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { deflateSync, crc32 } from "node:zlib";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-kits-"));
const port = 8823, token = "kittoken", base = `http://127.0.0.1:${port}`;
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" } });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// a 40x40 two-colour PNG (orange and navy), built here so the palette extraction has colours to find
const chunk = (t, d) => { const b = Buffer.concat([Buffer.from(t), d]); const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const c = Buffer.alloc(4); c.writeUInt32BE(crc32(b)); return Buffer.concat([l, b, c]); };
const raw = Buffer.concat(Array.from({ length: 40 }, (_, y) => Buffer.concat([Buffer.from([0]), ...Array.from({ length: 40 }, (_, x) => Buffer.from(x < 20 ? [249, 115, 22] : [15, 23, 42]))])));
const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(40, 0); ihdr.writeUInt32BE(40, 4); ihdr[8] = 8; ihdr[9] = 2;
const PNG = Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", deflateSync(raw)), chunk("IEND", Buffer.alloc(0))]);
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch(); const page = await browser.newPage({ viewport: { width: 1300, height: 1000 } });
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}/?token=${token}`); await page.goto(`${base}/#/settings`);
  await page.getByLabel("New brand kit name").fill("Acme");
  await page.getByLabel("Brand kit logo").setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: PNG });
  await page.getByRole("button", { name: "Create kit" }).click();
  const kit = page.getByTestId("kit-acme"); await kit.waitFor(); ok(true, "a brand kit is created from a logo upload");
  ok((await kit.getByLabel("Acme palette", { exact: true }).locator("span").count()) >= 1, "the palette came from the logo");
  await kit.locator("summary").click();
  await kit.getByLabel("Style words").fill("clean, bright"); await kit.getByLabel("End card text").fill("acme.com");
  await kit.getByLabel("Acme Heading font").selectOption("Anton");
  await kit.getByRole("button", { name: "Save kit" }).click(); await page.getByText(/Acme saved/).waitFor();
  const saved = await (await fetch(`${base}/api/brand-kits/acme`, { headers: { "x-aistudio-token": token } })).json();
  ok(saved.style_words === "clean, bright" && saved.end_card.text === "acme.com" && saved.fonts.heading === "Anton", "edits are saved");
  await kit.getByLabel("Acme palette colours").fill("nope"); await kit.getByRole("button", { name: "Save kit" }).click();
  ok(await page.getByText(/Palette colours look like/).isVisible(), "a bad palette is explained");

  // New Project: format grid + brand kit
  await page.goto(`${base}/`);
  await page.getByRole("button", { name: /Generate New Video/ }).first().click();
  const grid = page.getByTestId("format-grid"); await grid.waitFor();
  await page.getByTestId("format-instagram-reel").waitFor(); ok((await grid.getByRole("radio").count()) >= 11, "the format grid lists Blank and the formats");
  ok((await page.getByTestId("format-blank").getAttribute("aria-checked")) === "true", "Blank is the default");
  await page.getByTestId("format-instagram-reel").click();
  await page.getByRole("dialog").getByLabel("Brand kit").selectOption("acme");
  const dlg = page.getByRole("dialog"); await dlg.getByLabel("New project name").fill("reel1"); await dlg.getByRole("button", { name: "Create" }).click();
  await page.getByRole("log", { name: "Conversation" }).waitFor();
  const proj = join(home, "projects", "reel1");
  ok(existsSync(join(proj, "brand", "kit.json")), "the kit is copied into the project");
  ok(/Shot 05/.test(readFileSync(join(proj, "Story.md"), "utf-8")) && JSON.parse(readFileSync(join(proj, "shots.json"), "utf-8")).format === "instagram-reel", "the format seeds the story skeleton and shots.json");

  await page.goto(`${base}/#/settings`);
  await page.getByTestId("kit-acme").locator("summary").click();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete Acme" }).click();
  await page.getByRole("button", { name: "Move to trash" }).click();
  await page.getByText(/No brand kits yet/).waitFor(); ok(existsSync(join(home, "brand_kits", "_trash")), "deleting moves the kit to the trash");
  ok(existsSync(join(proj, "brand", "kit.json")), "the project keeps its own copy");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join("; ") : ""));
  await browser.close();
} finally { srv.kill(); }
process.exit(failed ? 1 : 0);
