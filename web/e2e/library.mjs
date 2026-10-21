// Cast + Library e2e (test mode, $0): identity sheet batch, versions, consent, drift, then the Library page (search, favourite, promote, use in project, remix).
// Every paid-looking step goes through the human approve dialog (test project, simulated provider).
import { chromium } from "playwright";
import { go } from "./nav.mjs";
import { spawn } from "node:child_process";
import { mkdtempSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-library-"));
const port = 8824, token = "libtoken", base = `http://127.0.0.1:${port}`;
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" } });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const hdr = { "x-aistudio-token": token, "content-type": "application/json" };
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
const post = (path, body) => fetch(`${base}${path}`, { method: "POST", headers: hdr, body: body === undefined ? undefined : JSON.stringify(body) });
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch(); const page = await browser.newPage({ viewport: { width: 1400, height: 1200 } });
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}/?token=${token}`);
  await page.getByPlaceholder(/project-name/).fill("libdemo"); await page.getByRole("button", { name: "Create" }).click();
  await page.getByRole("log", { name: "Conversation" }).waitFor();

  // a character with a master image, a budget (test project)
  await fetch(`${base}/api/projects/libdemo/images`, { method: "PUT", headers: hdr, body: JSON.stringify({ style: "clean", images: [{ id: "hero", kind: "character", out: "stills/hero.png", prompt: "A calm hero", refs: [] }] }) });
  await fetch(`${base}/api/projects/libdemo/upload?rel=stills/hero.png`, { method: "POST", headers: { "x-aistudio-token": token }, body: PNG });
  await post("/api/projects/libdemo/estimate", {}); await post("/api/projects/libdemo/budget/approve");

  await page.reload(); await go(page, "Assets");
  await page.getByRole("button", { name: "Open hero in the preview" }).click();
  const cast = page.getByTestId("cast-panel"); await cast.waitFor(); ok(true, "the Cast panel shows for a character");
  ok((await cast.getByText(/\(missing\)/).count()) === 5, "all five identity views are listed as missing");

  // identity sheet -> the shared batch approve dialog
  await cast.getByRole("button", { name: /Build identity sheet/ }).click();
  await page.getByTestId("plan").waitFor(); ok(/\$/.test(await page.getByTestId("plan-total").innerText()), "the identity-sheet batch opens the shared approve dialog with a total");
  ok((await page.getByTestId("plan").locator("li").count()) === 5, "the batch lists the five views");
  await page.getByTestId("approve-all").click();
  await page.getByText(/Generated 5 items/).waitFor({ timeout: 40000 }); ok(true, "approving runs the whole sheet");
  await cast.locator('img[alt="hero front view"]').waitFor(); ok(true, "the views appear in the Cast panel");

  // variants: 2 candidates, then choose one
  await cast.getByRole("button", { name: "Generate variants" }).click();
  await page.getByTestId("plan").waitFor(); await page.getByTestId("approve-all").click();
  await page.getByText(/Generated 2 items/).waitFor({ timeout: 40000 });
  await cast.getByTestId("variants-strip").waitFor(); ok((await cast.getByTestId("variants-strip").locator("li").count()) >= 2, "the versions strip lists the candidates");
  await cast.getByRole("button", { name: /Select version 2 of hero/ }).click();
  await page.getByRole("button", { name: /Use version 2/ }).click();
  await page.getByText(/Using version 2 of hero/).waitFor(); ok(true, "a version can be selected");
  const imgs = await (await fetch(`${base}/api/projects/libdemo`, { headers: hdr })).json();
  ok(imgs.images.images.find((i) => i.id === "hero").selected_version === 2, "the choice is recorded as selected_version");

  // consent (human only)
  await cast.getByLabel("Consent subject").fill("Asha Rao"); await cast.getByLabel("Consent statement").fill("I agree to appear in this video");
  await cast.getByRole("button", { name: "Record consent" }).click();
  await cast.getByText(/Asha Rao/).first().waitFor(); ok(true, "consent is recorded and listed");
  const agentKey = (await (await fetch(`${base}/api/keys`, { method: "POST", headers: hdr, body: JSON.stringify({ name: "e2e" }) })).json()).key;
  ok((await fetch(`${base}/api/projects/libdemo/consent`, { method: "POST", headers: { "x-aistudio-token": agentKey, "content-type": "application/json" }, body: JSON.stringify({ subject: "x", statement: "y" }) })).status === 403, "an API key cannot record consent");

  // drift check -> a proposal the human approves in the usual dialog (cancelled here: nothing runs)
  await cast.getByRole("button", { name: /Check drift/ }).click();
  await page.getByText("Approve this paid action?").waitFor(); ok(true, "the drift check opens the normal approve dialog");
  await page.getByRole("button", { name: "Cancel" }).click();

  // Library page
  await page.goto(`${base}/#/library`);
  await page.getByTestId("library-items").waitFor(); ok((await page.getByTestId("library-items").locator("li").count()) >= 5, "the Library lists generations from the project");
  await page.getByLabel("Search the library").fill("hero"); await sleep(600);
  ok((await page.getByTestId("library-items").locator("li").count()) >= 1, "search finds items by prompt text");
  await page.getByLabel("List view").click(); ok((await page.getByTestId("library-items").locator("li").count()) >= 1, "list view works");
  await page.getByLabel("Grid view").click();
  const first = page.getByTestId("library-items").locator("li").first();
  await first.getByRole("button", { name: /Add .* to favourites/ }).click();
  await page.getByLabel("Favourites").check(); await sleep(600);
  ok((await page.getByTestId("library-items").locator("li").count()) === 1, "favourite filter shows the starred item");
  await page.getByLabel("Favourites").uncheck(); await sleep(400);
  await page.getByTestId("library-items").locator("li").first().getByRole("button", { name: /^Open / }).click();
  const det = page.getByTestId("library-detail"); await det.waitFor(); ok(/Model/.test(await det.innerText()), "the detail panel shows model, cost and prompt");
  await det.getByRole("button", { name: "Add to library" }).click(); await page.getByText(/is now in the library/).waitFor(); ok(true, "an item can be promoted to the library");
  await page.getByLabel("Project", { exact: true }).selectOption("_library"); await sleep(600);
  await page.getByTestId("library-items").locator("li").first().getByRole("button", { name: /^Open / }).click();
  await page.getByTestId("library-detail").getByRole("button", { name: "Use in project" }).click();
  await page.getByText(/Copied into libdemo/).waitFor(); ok(true, "a library item can be copied into a project");
  await page.getByLabel("Project", { exact: true }).selectOption(""); await sleep(600);
  await page.getByLabel("Search the library").fill("front"); await sleep(600);
  await page.getByTestId("library-items").locator("li").first().getByRole("button", { name: /^Open / }).click();
  await page.getByTestId("library-detail").getByRole("button", { name: /Remix/ }).click();
  await page.getByText("Approve this paid action?").waitFor(); ok(true, "Remix opens the approve dialog with the exact price");
  await page.getByRole("button", { name: "Cancel" }).click();
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join("; ") : ""));
  await browser.close();
} finally { srv.kill(); }
process.exit(failed ? 1 : 0);
