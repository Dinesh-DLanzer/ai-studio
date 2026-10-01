// Screenshots of every screen of a RUNNING AI Studio (read-only: it only opens pages and switches tabs; it never creates, saves, generates or approves anything).
// Usage: node web/e2e/screenshots-all.mjs "<the link with ?token=...>" [outDir]      (default outDir: ./screenshots)
// The images can show your real projects, so the screenshots folder is git-ignored.
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { join, resolve } from "node:path";

const link = process.argv[2];
if (!link) { console.error('Usage: node web/e2e/screenshots-all.mjs "http://127.0.0.1:8765/?token=..." [outDir]'); process.exit(2); }
const u = new URL(link); const base = u.origin; const token = u.searchParams.get("token") || "";
const out = resolve(process.argv[3] || "screenshots"); mkdirSync(out, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const get = async (p) => (await fetch(base + p, { headers: { "x-aistudio-token": token } })).json();
let n = 0; const saved = [];

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const page = await ctx.newPage(); const errors = []; page.on("pageerror", (e) => errors.push(e.message));
const shot = async (name, opts = {}) => {
  await sleep(opts.wait ?? 1200);
  const file = `${String(++n).padStart(2, "0")}-${name}.png`;
  await page.screenshot({ path: join(out, file), fullPage: opts.full !== false }); saved.push(file); console.log("saved", file);
};
const go = async (hash, waitFor) => { await page.goto(`${base}/#${hash}`); if (waitFor) await waitFor().catch(() => {}); };

try {
  await page.goto(`${base}/?token=${token}`);
  const projects = (await get("/api/projects")).projects.map((p) => p.name);
  const setup = await get("/api/setup");
  console.log("projects:", projects.join(", "), "| setup needed:", setup.needed);

  // ---- Projects page and its tabs
  await go("/", () => page.getByText("Your", { exact: false }).first().waitFor());
  await page.getByRole("tab", { name: /All Projects/ }).waitFor().catch(() => {});
  await shot("projects-all");
  for (const t of ["Recent", "Favorites", "Archived"]) { const tab = page.getByRole("tab", { name: new RegExp(t) }); if (await tab.count()) { await tab.click(); await shot(`projects-${t.toLowerCase()}`, { wait: 700 }); } }
  await page.getByRole("tab", { name: /All Projects/ }).click().catch(() => {});

  // ---- dialogs that open without changing anything
  await page.getByRole("button", { name: /Generate New Video/ }).first().click(); await page.getByRole("dialog").waitFor().catch(() => {}); await shot("dialog-generate-new-video", { full: false, wait: 600 });
  await page.keyboard.press("Escape"); await sleep(300);
  await page.keyboard.press("Control+k"); await page.getByRole("dialog").waitFor().catch(() => {}); await shot("command-box", { full: false, wait: 600 });
  await page.keyboard.press("Escape"); await sleep(300);

  // ---- each project, every page
  const PAGES = [["", "overview"], ["/chat", "chat"], ["/storyboard", "storyboard"], ["/assets", "assets"], ["/shots", "shots"], ["/review", "review-export"], ["/costs", "costs"], ["/discarded", "discarded"]];
  for (const name of projects) {
    const tag = name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
    for (const [path, label] of PAGES) {
      await go(`/p/${name}${path}`, () => page.locator("nav[aria-label=Project]").waitFor({ timeout: 15000 }));
      await shot(`${tag}-${label}`, { wait: label === "review-export" ? 3500 : label === "shots" ? 2500 : 1500 });
    }
  }

  // ---- Settings (whole page; keys are masked by the app)
  await go("/settings", () => page.getByRole("heading", { name: "Settings", exact: true }).waitFor()); await shot("settings", { wait: 2000 });

  // ---- Help: every tab
  await go("/help", () => page.getByRole("tab", { name: "Getting Started" }).waitFor());
  for (const t of ["Getting Started", "Guides", "Features", "API & Integrations", "Troubleshooting", "FAQ"]) {
    await page.getByRole("tab", { name: t }).click(); await shot(`help-${t.toLowerCase().replace(/[^a-z]+/g, "-").replace(/-$/, "")}`, { wait: t.startsWith("API") ? 1800 : 600 });
  }

  // ---- the 404 page
  await go("/p/this-project-does-not-exist", () => page.getByTestId("not-found").waitFor()); await shot("page-not-found");
  console.log(`done: ${saved.length} screenshots in ${out}` + (errors.length ? `; page errors: ${errors.join(" | ")}` : "; no page errors"));
} catch (e) { console.error("FAILED: " + (e.stack || e)); process.exitCode = 1; }
finally { await browser.close(); }
