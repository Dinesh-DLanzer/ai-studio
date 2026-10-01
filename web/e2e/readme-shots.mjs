// Takes the screenshots used in README.md (docs/img/*.png) from the CURRENT interface.
// Runs against a throwaway test-mode workspace with made-up demo projects (no provider, no key, $0, nothing of yours is touched).
// Usage: node web/e2e/readme-shots.mjs [outDir]      (needs: web built, .venv, ffmpeg)
import { chromium } from "playwright";
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../..");
const out = resolve(process.argv[2] || join(repo, "docs/img")); mkdirSync(out, { recursive: true });
const home = mkdtempSync(join(tmpdir(), "aistudio-shots-")); const work = mkdtempSync(join(tmpdir(), "aistudio-shots-media-"));
const port = 8826, token = "shotstoken", base = `http://127.0.0.1:${port}`; const H = { "x-aistudio-token": token, "content-type": "application/json" };
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1", AISTUDIO_NO_KEYRING: "1" } });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const api = async (m, u, b, h = H) => { const r = await fetch(base + u, { method: m, headers: h, body: b === undefined ? undefined : JSON.stringify(b) }); const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(`${m} ${u}: ${r.status} ${JSON.stringify(j)}`); return j; };
const ff = (...a) => execFileSync("ffmpeg", ["-y", "-loglevel", "error", ...a]);
const grad = (file, c0, c1, w = 540, h = 960) => ff("-f", "lavfi", "-i", `gradients=s=${w}x${h}:c0=${c0}:c1=${c1}:x0=0:y0=0:x1=${w}:y1=${h}:d=1`, "-frames:v", "1", file);
const clip = (file, secs, c0, c1) => ff("-f", "lavfi", "-i", `gradients=s=540x960:c0=${c0}:c1=${c1}:speed=0.04:d=${secs}:r=24`, "-f", "lavfi", "-i", "sine=frequency=330:duration=" + secs, "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-b:v", "250k", "-c:a", "libopus", "-shortest", file);
const job = async (id) => { for (;;) { await sleep(400); const j = await api("GET", `/api/jobs/${id}`); if (j.status !== "running") return j; } };
const generate = async (name, kind, target) => { const p = await api("POST", `/api/projects/${name}/proposals`, { kind, target }); await api("POST", `/api/projects/${name}/proposals/${p.id}/approve`, { code: p.code }); const { job: id } = await api("POST", `/api/projects/${name}/proposals/${p.id}/execute`, {}); return job(id); };
const upload = async (name, rel, file) => { const r = await fetch(`${base}/api/projects/${name}/upload?rel=${rel}`, { method: "POST", headers: { "x-aistudio-token": token }, body: readFileSync(file) }); if (!r.ok) throw new Error("upload " + rel); };
const interview = async (name, answers, logo) => {
  await api("POST", `/api/projects/${name}/chat`, { text: "hello" });
  for (const a of answers) await api("POST", `/api/projects/${name}/chat`, { text: a });
  await api("POST", `/api/projects/${name}/chat`, logo ? { text: "Yes, please use my brand colours.", attachments: ["logo"] } : { text: "skip" });
};

let browser;
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  grad(join(work, "logo.png"), "0x0a5a64", "0xf08c14", 240, 240);

  // 1. chai-corner: a project built through the chat, part-way through production (logo attached, budget approved, first character made)
  await api("POST", "/api/projects", { name: "chai-corner", test_pipeline: true });
  await upload("chai-corner", "stills/logo.png", join(work, "logo.png"));
  await api("POST", "/api/projects/chai-corner/stills/import", { items: [{ file: "logo.png", id: "logo", kind: "other" }] });
  await interview("chai-corner", ["Chai Corner, a street tea stall", "Get more walk-ins", "Meena pours tea. Customers smile. She waves goodbye.", "12", "English", "Meena, 40s, cotton saree, warm smile", "A small street tea stall in the morning", "50"], true);
  await api("POST", "/api/projects/chai-corner/estimate", { failure: 0.2 }); await api("POST", "/api/projects/chai-corner/budget/approve");
  await generate("chai-corner", "image", "meena");

  // 2. tea-corner: a finished set of assets and approved clips with an edit (text, music) ready in Review & Export
  await api("POST", "/api/projects", { name: "tea-corner", test_pipeline: true });
  await interview("tea-corner", ["Tea Corner, a morning tea stall", "Sell more morning chai", "A tea seller opens his stall at sunrise. Regulars gather. He hands over the first cup.", "12", "English", "Ravi, 50s, white shirt, kind eyes", "A small roadside tea stall at sunrise", "50"]);
  const pdir = join(home, "projects", "tea-corner"); mkdirSync(join(pdir, "stills"), { recursive: true }); mkdirSync(join(pdir, "clips"), { recursive: true }); mkdirSync(join(pdir, "audio"), { recursive: true });
  const colors = [["0xf5b041", "0xc0392b"], ["0x1f618d", "0x76d7c4"], ["0x6c3483", "0xf1948a"], ["0x196f3d", "0xf9e79f"], ["0x2e4053", "0xf5cba7"]];
  const assets = (await api("GET", "/api/projects/tea-corner")).images.images.filter((i) => i.kind !== "other");
  assets.forEach((a, i) => grad(join(pdir, a.out), colors[i % 5][0], colors[i % 5][1]));
  const shots = (await api("GET", "/api/projects/tea-corner")).shots;
  shots.shots.forEach((s, i) => { clip(join(pdir, "clips", `${s.id}_final_a1.mp4`), 4, colors[(i + 2) % 5][0], colors[(i + 2) % 5][1]); s.final_ok = true; s.final_clip = `clips/${s.id}_final_a1.mp4`; });
  await api("PUT", "/api/projects/tea-corner/shots", shots);
  await api("POST", "/api/projects/tea-corner/estimate", { failure: 0.2 }); await api("POST", "/api/projects/tea-corner/budget/approve");
  ff("-f", "lavfi", "-i", "sine=frequency=262:duration=12", join(pdir, "audio", "morning-music.wav"));
  const e = await api("GET", "/api/projects/tea-corner/edit");
  const ed = e.edit; ed.tracks.video.forEach((v, i) => { if (i > 0) v.transition = { type: "crossfade", dur: 0.6 }; });
  ed.tracks.text = [{ id: "t1", text: "Fresh chai,\nevery morning", start: 0.8, end: 5, x: 0.5, y: 0.66, font: "Poppins", weight: 700, size: 64, color: "#ffffff", bg: "#a855f7", align: "center", bold: true, italic: false, underline: false, caps: false, opacity: 1, shadow: { on: false, color: "#000000", blur: 20 } }];
  ed.tracks.audio = [{ id: "a1", src: "audio/morning-music.wav", name: "Morning music", start: 0, in: 0, out: 11, volume: 0.5, fadeIn: 1, fadeOut: 1.5 }];
  await api("PUT", "/api/projects/tea-corner/edit", ed);
  await api("POST", "/api/projects/tea-corner/favorite", { on: true });

  // 3. two more cards, and one archived project, for the Projects page
  await api("POST", "/api/projects", { name: "festival-greeting", test_pipeline: true });
  await api("POST", "/api/projects", { name: "old-experiment", test_pipeline: true });
  await api("DELETE", "/api/projects/old-experiment", { confirm: "old-experiment" });
  // an agent (API key) proposes something: it waits for a human decision on the Overview page
  const key = (await api("POST", "/api/keys", { name: "claude-code" })).key;
  await api("POST", "/api/projects/chai-corner/proposals", { kind: "image", target: "main_place" }, { authorization: `Bearer ${key}`, "content-type": "application/json" });

  browser = await chromium.launch(); const ctx = await browser.newContext({ viewport: { width: 1360, height: 860 } }); const page = await ctx.newPage();
  const shot = async (name) => { await sleep(900); await page.screenshot({ path: join(out, name) }); console.log("saved", name); };
  await page.goto(`${base}/?token=${token}#/`);
  await page.getByRole("button", { name: "Actions for tea-corner" }).waitFor(); await page.waitForFunction(() => document.querySelectorAll("img").length >= 1); await shot("projects.png");

  await page.goto(`${base}/#/p/chai-corner/chat`); await page.getByTestId("checklist").waitFor();
  await page.evaluate(() => { const l = document.querySelector("[role=log]"); if (l) l.scrollTop = l.scrollHeight; window.scrollTo(0, 0); }); await sleep(600);
  await page.getByTestId("checklist").scrollIntoViewIfNeeded(); await shot("chat.png");

  await page.goto(`${base}/#/p/tea-corner/assets`); await page.getByText("Characters").first().waitFor(); await sleep(600); await shot("assets.png");
  await page.goto(`${base}/#/p/tea-corner/shots`); await page.getByRole("button", { name: /Open shot s01/ }).waitFor(); await sleep(800); await shot("shots.png");

  await page.setViewportSize({ width: 1360, height: 1040 });                         // the editor needs the height to show its timeline
  await page.goto(`${base}/#/p/tea-corner/review`); await page.locator("[data-testid=vbar-s01]").waitFor();
  await page.waitForFunction(() => document.querySelectorAll(".re-film img").length >= 3, null, { timeout: 20000 }).catch(() => {});
  await page.getByRole("slider", { name: "Seek" }).evaluate((el) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, "1.6"); el.dispatchEvent(new Event("input", { bubbles: true })); });
  await page.locator("[data-testid=tbar-t1]").click({ position: { x: 20, y: 10 } }).catch(() => {}); await sleep(900); await shot("editor.png");

  await page.setViewportSize({ width: 1360, height: 860 });
  await page.goto(`${base}/#/p/chai-corner`); await page.getByText("Waiting for your decision").waitFor(); await shot("waiting-for-decision.png");
  await page.goto(`${base}/#/p/chai-corner/assets`); await page.getByText("Characters").first().waitFor();
  await page.getByText("not made yet").first().click(); await sleep(500);                  // the first asset that is not made yet (the background)
  if (!(await page.getByRole("button", { name: "Generate with AI", exact: true }).count())) { await page.screenshot({ path: "/tmp/dbg-assets.png" }); console.log("BUTTONS", JSON.stringify(await page.getByRole("button").allInnerTexts())); }
  await page.getByRole("button", { name: "Generate with AI", exact: true }).first().click(); await page.getByText("Approve this paid action?").waitFor(); await shot("approve-dialog.png");
  await page.keyboard.press("Escape");

  await page.goto(`${base}/#/help`); await page.getByText("What AI Studio does for you").waitFor(); await shot("help.png");
  await page.goto(`${base}/#/settings`); await page.getByRole("heading", { name: "Connect an AI agent (MCP)" }).waitFor();
  await page.getByRole("heading", { name: "Connect an AI agent (MCP)" }).scrollIntoViewIfNeeded(); await page.evaluate(() => window.scrollBy(0, -90)); await shot("settings-integrations.png");
} catch (err) { console.error("FAILED: " + (err.stack || err)); process.exitCode = 1; }
finally { if (browser) await browser.close(); srv.kill(); }
