// Projects page e2e (test mode, $0): cover images ignore hidden files, Test badge, Test label under Discarded, zip import (good, duplicate name, bad zip).
import { chromium } from "playwright";
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../..");
const shotsDir = process.env.SHOTS_DIR || tmpdir();
const home = mkdtempSync(join(tmpdir(), "aistudio-projects-")); const work = mkdtempSync(join(tmpdir(), "aistudio-zips-"));
const port = 8822, token = "prjtoken", base = `http://127.0.0.1:${port}`; const H = { "x-aistudio-token": token, "content-type": "application/json" };
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_NO_NETWORK: "1" } });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const api = async (m, u, b) => { const r = await fetch(base + u, { method: m, headers: H, body: b === undefined ? undefined : JSON.stringify(b) }); return { status: r.status, json: await r.json().catch(() => ({})), r }; };
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  // a connected provider with a chat model (so the first-run screen is out of the way) and NO forced test mode: projects are test or real by their files
  await api("POST", "/api/providers", { type: "openrouter", secret: { api_key: "sk-or-test-1234567890abcd" } });
  await api("PUT", "/api/roles/chat", { chain: [{ provider: "openrouter", model: "openrouter/free" }] });
  await api("POST", "/api/projects", { name: "alpha" }); await api("POST", "/api/projects", { name: "tp", test_pipeline: true });
  const stills = join(home, "projects", "alpha", "stills");
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=orange:s=320x200", "-frames:v", "1", join(stills, "hero.png")]);
  writeFileSync(join(stills, ".DS_Store"), "junk");          // sorts before hero.png: used to become the cover and break the image

  const browser = await chromium.launch(); const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true })).newPage();
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}/?token=${token}`);
  await page.getByRole("button", { name: "Actions for alpha" }).waitFor();
  await page.waitForFunction(() => [...document.querySelectorAll("img")].some((i) => i.complete && i.naturalWidth > 0), null, { timeout: 8000 });
  const alphaCard = page.locator("div.relative", { has: page.getByRole("button", { name: "Actions for alpha" }) });
  ok(await alphaCard.locator("img").evaluate((i) => i.complete && i.naturalWidth > 0), "a project with a hidden .DS_Store in stills/ still shows its real cover image");
  const ov = (await api("GET", "/api/projects/alpha")).json; ok(ov.files.stills.join() === "hero.png", "hidden files are not listed as assets");
  ok(await alphaCard.getByTestId("test-badge").count() === 0, "a normal project has no Test badge");
  const tpCard = page.locator("div.relative", { has: page.getByRole("button", { name: "Actions for tp" }) });
  ok(await tpCard.getByTestId("test-badge").isVisible() && (await tpCard.getByTestId("test-badge").innerText()).toLowerCase() === "test", "a test-pipeline project shows a Test badge on its card");

  // card: asset and shot counts are visible; Add to favorites lives in the 3-dots menu
  ok(/\d+ assets/.test(await alphaCard.getByTestId("card-counts").innerText()) && /\d+ shots/.test(await alphaCard.getByTestId("card-counts").innerText()), "each card shows its asset count and shot count");
  ok(await alphaCard.getByText("★", { exact: true }).count() === 0, "the star badge is gone from the card image");
  await page.getByRole("button", { name: "Actions for alpha" }).click(); await page.getByRole("menuitem", { name: "Add to favorites" }).click();
  await page.getByRole("tab", { name: /Favorites/ }).waitFor(); await page.waitForFunction(() => [...document.querySelectorAll("[role=tab]")].some((t) => /Favorites/.test(t.textContent) && /1/.test(t.textContent)));
  ok(await alphaCard.getByLabel("Favorite").isVisible(), "a favorite shows a small star next to its name");
  await page.getByRole("tab", { name: /Favorites/ }).click(); ok(await page.getByRole("button", { name: "Actions for tp" }).count() === 0 && await page.getByRole("button", { name: "Actions for alpha" }).isVisible(), "the Favorites tab lists only favorites");
  await page.getByRole("button", { name: "Actions for alpha" }).click(); ok(await page.getByRole("menuitem", { name: "Remove from favorites" }).isVisible(), "the menu offers Remove from favorites");
  await page.getByRole("menuitem", { name: "Remove from favorites" }).click(); await page.getByRole("tab", { name: /All Projects/ }).click();
  await page.getByRole("button", { name: "Actions for alpha" }).waitFor();

  // label under Discarded
  await page.goto(`${base}/#/p/tp`); await page.getByTestId("mode-label").waitFor();
  const lab = await page.getByTestId("mode-label").boundingBox(); const disc = await page.locator("nav[aria-label=Project]").getByRole("link", { name: /^Discarded/ }).boundingBox();
  ok((await page.getByTestId("mode-label").innerText()).trim().toLowerCase() === "test project" && lab.y > disc.y, "inside a test project the label 'Test Project' sits under Discarded");
  await page.goto(`${base}/#/p/alpha`); await page.locator("nav[aria-label=Project]").waitFor(); await sleep(400);
  ok(await page.getByTestId("mode-label").count() === 0 && !(await page.locator("aside.sidebar").innerText()).toLowerCase().includes("test"), "a normal project never shows a Test label");
  // a real clip (not the test-mode placeholder) makes it an actual project even if it carries the test marker
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1:r=10", join(home, "projects", "tp", "clips", "real.mp4")]);
  await page.goto(`${base}/#/p/tp`); await page.locator("nav[aria-label=Project]").waitFor(); await sleep(400);
  ok(await page.getByTestId("mode-label").count() === 0, "a project with real generated media is shown as an actual project, whatever marker it has");
  await page.goto(`${base}/#/`); await page.getByRole("button", { name: "Actions for tp" }).waitFor();
  ok(await page.getByTestId("test-badge").count() === 0, "and its card has no Test badge")

  // ---- zip import
  const exp = await fetch(`${base}/api/projects/alpha/export-project`, { headers: H }); writeFileSync(join(work, "alpha.zip"), Buffer.from(await exp.arrayBuffer()));
  await page.goto(`${base}/#/`); await page.getByTestId("import-project").first().waitFor();
  await page.getByLabel("Project zip file").first().setInputFiles(join(work, "alpha.zip"));
  ok((await page.getByLabel("Imported project name").inputValue()) === "alpha", "choosing a zip suggests the project name from the file");
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.getByTestId("import-problems").waitFor(); ok((await page.getByTestId("import-problems").innerText()).includes("already exists"), "a name that is taken is refused with a clear message");
  await page.getByLabel("Imported project name").fill("alpha-copy"); await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.waitForFunction(() => location.hash === "#/p/alpha-copy"); ok(true, "a good zip is imported and opens the new project");
  const list = (await api("GET", "/api/projects")).json.projects.map((p) => p.name).sort().join();
  ok(list === "alpha,alpha-copy,tp", "the project list now has the imported project");
  ok((await api("GET", "/api/projects/alpha-copy")).json.files.stills.join() === "hero.png", "the imported project has its files");

  // bad zip: a script, a fake-looking image, broken JSON
  const bad = join(work, "bad"); mkdirSync(join(bad, "evil", "stills"), { recursive: true });
  writeFileSync(join(bad, "evil", "run.sh"), "rm -rf /"); writeFileSync(join(bad, "evil", "stills", "x.png"), "not a png"); writeFileSync(join(bad, "evil", "shots.json"), "{oops");
  execFileSync("zip", ["-qr", join(work, "evil.zip"), "evil"], { cwd: bad });
  await page.goto(`${base}/#/`); await page.getByLabel("Project zip file").first().waitFor({ state: "attached" });
  await page.getByLabel("Project zip file").first().setInputFiles(join(work, "evil.zip"));
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.getByTestId("import-problems").waitFor(); const txt = await page.getByTestId("import-problems").innerText();
  ok(/run\.sh/.test(txt) && /x\.png/.test(txt) && /shots\.json/.test(txt), "a bad zip lists every problem (script, fake image, broken JSON)");
  ok((await api("GET", "/api/projects")).json.projects.length === 3, "the bad zip created nothing");
  // ---- 404 pages
  for (const [hash, what] of [["#/p/ghost", "a missing project"], ["#/p/ghost/assets", "a page of a missing project"]]) {
    await page.goto(`${base}/${hash}`); await page.getByTestId("not-found").waitFor();
    ok(await page.getByRole("heading", { name: "Project not found" }).isVisible() && (await page.getByTestId("not-found").innerText()).includes("ghost") && (await page.title()).startsWith("Page not found"), `${what} shows a proper 404 that names the project`);
  }
  await page.goto(`${base}/#/p/ghost`); await page.getByTestId("not-found").waitFor(); await sleep(600); await page.screenshot({ path: join(work, "404.png") });
  await page.goto(`${base}/#/p/alph`); await page.getByTestId("nf-similar").waitFor(); await page.getByTestId("nf-similar").getByRole("link", { name: "alpha", exact: true }).click();
  await page.waitForFunction(() => location.hash === "#/p/alpha"); ok(true, "the 404 suggests similar project names");
  await api("DELETE", "/api/projects/tp", { confirm: "tp" });
  await page.goto(`${base}/#/p/tp/assets`); await page.getByTestId("nf-trash").waitFor(); ok(true, "a deleted project's 404 says it is in the trash");
  await page.getByRole("button", { name: /Restore tp/ }).click(); await page.waitForFunction(() => location.hash === "#/p/tp");
  await page.locator("nav[aria-label=Project]").waitFor(); ok((await api("GET", "/api/projects/tp")).status === 200, "Restore from the 404 page brings the project back and opens it");
  await page.goto(`${base}/#/p/alpha/nope`); await page.getByTestId("not-found").waitFor(); await page.locator("nav[aria-label=Project]").waitFor(); ok(true, "a bad page inside an existing project keeps the project sidebar");
  const nfAx = await (await import("@axe-core/playwright")).default; const r = await new nfAx({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  ok(r.violations.length === 0, "no accessibility violations on the 404 page" + (r.violations.length ? ": " + r.violations.map((v) => `${v.id}(${v.nodes.length})`).join("; ") : ""));

  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  await browser.close();
} catch (e) { console.log("FAIL exception: " + (e.stack || e)); failed = true; }
finally { srv.kill(); }
process.exit(failed ? 1 : 0);
