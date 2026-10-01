// Assets e2e (test mode, $0): add + upload + replace images in every category, choose references, reject bad files.
import { chromium } from "playwright";
import { go } from "./nav.mjs";
import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-assets-"));
const shots = process.env.SHOTS_DIR || join(tmpdir(), "aistudio-shots"); mkdirSync(shots, { recursive: true });
const port = 8815, token = "assettoken";
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" } });
const dbg = []; let failed = false, pageRef = null; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
const JPG = Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0]), Buffer.alloc(40)]);
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`http://127.0.0.1:${port}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch(); const page = await browser.newPage({ viewport: { width: 1300, height: 1000 } }); pageRef = page;
  page.on("dialog", (d) => d.accept("replaced in test"));
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  page.on("response", async (r) => { if (/upload|rename|images/.test(r.url()) && r.request().method() !== "GET") dbg.push(`DBG ${r.request().method()} ${r.url().split("?")[0].split("/api/")[1]} ${r.url().includes("replace=1") ? "replace " : ""}-> ${r.status()}`); });
  await page.goto(`http://127.0.0.1:${port}/?token=${token}`);
  await page.getByPlaceholder(/project-name/).fill("assetdemo"); await page.getByRole("button", { name: "Create" }).click();
  await go(page, "Assets");
  const addBtn = (title, label) => page.getByRole("region", { name: title }).getByRole("button", { name: `Add ${label}` }).first();
  await page.getByText(/No backgrounds yet/).waitFor(); ok(true, "empty categories explain how to add an asset");
  for (const [t, k] of [["Characters", "Character"], ["Backgrounds", "Background"], ["Scene Frames", "Frame"]]) ok(await addBtn(t, k).isVisible(), `an Add ${k.toLowerCase()} button exists`);

  // invalid id
  await addBtn("Characters", "Character").click();
  await page.getByLabel("Asset id").fill("Bad Id!"); await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByText(/Use a short id/).waitFor(); ok(true, "an invalid id is rejected with a helpful message");

  // character: add + upload
  await page.getByLabel("Asset id").fill("hero_sheet"); await page.getByLabel("Asset description").fill("Hero, 40s, white shirt"); await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.locator('[data-asset="hero_sheet"]').getByText("not made yet").waitFor(); ok(true, "a new character asset appears without an image");
  await page.locator('[data-asset="hero_sheet"]').getByLabel("Upload image for hero_sheet").setInputFiles({ name: "hero.png", mimeType: "image/png", buffer: PNG });
  await page.locator('[data-asset="hero_sheet"] img').waitFor(); ok(true, "uploading an image makes the character ready");
  await page.screenshot({ path: join(shots, "14-assets-upload.png") });

  // replace with a jpeg: old image must be kept in Discarded
  await page.locator('[data-asset="hero_sheet"]').getByLabel("Replace image for hero_sheet").setInputFiles({ name: "hero.jpg", mimeType: "image/jpeg", buffer: JPG });
  await page.getByText(/Replaced hero_sheet/).waitFor(); ok(true, "an image can be replaced by another upload");

  // bad file
  await page.locator('[data-asset="hero_sheet"]').getByLabel("Replace image for hero_sheet").setInputFiles({ name: "notes.png", mimeType: "image/png", buffer: Buffer.from("this is not an image") });
  await page.getByText(/not a supported image/).waitFor(); ok(true, "a file that is not really an image is rejected");

  // other formats are accepted and converted: a real GIF upload
  const GIF = Buffer.from("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7", "base64");
  await page.locator('[data-asset="hero_sheet"]').getByLabel("Replace image for hero_sheet").setInputFiles({ name: "photo.gif", mimeType: "image/gif", buffer: GIF });
  await page.getByText(/Replaced hero_sheet/).first().waitFor(); ok(true, "a GIF (another image format) is accepted and converted");

  // background
  await addBtn("Backgrounds", "Background").click();
  await page.getByLabel("Asset id").fill("shop_empty"); await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByLabel("Upload image for shop_empty").setInputFiles({ name: "shop.png", mimeType: "image/png", buffer: PNG });
  await page.getByText(/Uploaded shop_empty/).waitFor(); ok(true, "a background can be added and uploaded");

  // drag and drop a file onto a card
  await addBtn("Scene Frames", "Frame").click();
  await page.getByLabel("Asset id").fill("dropme"); await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.locator('[data-asset="dropme"]').waitFor();
  await page.evaluate((b64) => {
    const dt = new DataTransfer(); dt.items.add(new File([Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))], "dropped.png", { type: "image/png" }));
    const el = document.querySelector('[data-asset="dropme"]');
    for (const t of ["dragenter", "dragover", "drop"]) el.dispatchEvent(new DragEvent(t, { dataTransfer: dt, bubbles: true, cancelable: true }));
  }, PNG.toString("base64"));
  await page.getByText(/Uploaded dropme/).waitFor(); ok(true, "dragging a file onto a card uploads it");
  await page.locator('[data-asset="dropme"]').getByRole("button", { name: "Remove" }).count();

  // scene frame with references
  await addBtn("Scene Frames", "Frame").click();
  await page.getByLabel("Asset id").fill("s01"); await page.getByRole("button", { name: "Add", exact: true }).click();
  // the new frame is open in the preview rail: add its references from the "Add a reference" menu
  await page.getByRole("button", { name: "Add a reference", exact: true }).click(); await page.getByRole("menuitem", { name: "hero_sheet", exact: true }).click();
  await page.getByRole("button", { name: "Add a reference", exact: true }).click(); await page.getByRole("menuitem", { name: "shop_empty", exact: true }).click();
  await page.getByText("unsaved changes").waitFor(); ok(true, "choosing references marks the list as unsaved");
  await page.getByRole("button", { name: "Save list" }).click(); await page.getByText("Image list saved.").waitFor();
  await page.reload(); await go(page, "Assets");
  await page.getByRole("button", { name: "Open s01 in the preview" }).click();
  ok((await page.getByRole("button", { name: "Remove reference hero_sheet" }).isVisible()) && (await page.getByRole("button", { name: "Remove reference shop_empty" }).isVisible()), "the chosen references were saved");
  await page.screenshot({ path: join(shots, "15-assets-refs.png"), fullPage: true });

  // the old image was kept
  await go(page, "Discarded"); await page.getByText(/stills\/hero_sheet\.(png|jpg)/).first().waitFor(); ok(true, "the replaced image is kept in Discarded with its reason");
  await page.getByText("replaced by an upload").first().waitFor();
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  await browser.close();
} catch (e) { console.log("FAIL exception: " + e.message.split("\n").slice(0, 3).join(" | ")); failed = true; if (pageRef) { await pageRef.screenshot({ path: join(shots, "FAIL-assets.png"), fullPage: true }).catch(() => {}); console.log(dbg.join("\n")); console.log("PAGE: " + (await pageRef.locator("body").innerText().catch(() => "")).replace(/\n+/g, " | ").slice(0, 900)); } }
finally { srv.kill(); }
process.exit(failed ? 1 : 0);
