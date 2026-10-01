// Review & Export e2e (test mode, $0): the editor screen, text/transition/split/audio edits, autosave, undo, export video (real ffmpeg),
// export project (zip), delete + restore project, accessibility.  Needs ffmpeg on PATH.
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, statSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-editor-"));
const shots = process.env.SHOTS_DIR || join(tmpdir(), "aistudio-shots"); mkdirSync(shots, { recursive: true });
const port = 8821, token = "edtoken", base = `http://127.0.0.1:${port}`; const H = { "x-aistudio-token": token, "content-type": "application/json" };
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" } });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const api = async (m, u, b) => { const r = await fetch(base + u, { method: m, headers: H, body: b === undefined ? undefined : JSON.stringify(b) }); return { status: r.status, json: await r.json().catch(() => ({})) }; };
const ff = (...a) => execFileSync("ffmpeg", ["-y", "-loglevel", "error", ...a]);
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  await api("POST", "/api/projects", { name: "ed" });
  const pdir = join(home, "projects", "ed"); mkdirSync(join(pdir, "clips"), { recursive: true });
  // 3 clips of 2 s (VP9 + Opus so the headless browser can play them), a short sound file to upload
  [["s01", "red"], ["s02", "green"], ["s03", "blue"]].forEach(([id, c]) => ff("-f", "lavfi", "-i", `color=c=${c}:s=320x568:r=24:d=2`, "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libvpx-vp9", "-b:v", "200k", "-c:a", "libopus", "-shortest", join(pdir, "clips", `${id}_final_a1.mp4`)));
  const wav = join(tmpdir(), "e2e-music.wav"); ff("-f", "lavfi", "-i", "sine=frequency=330:duration=4", wav);
  await api("PUT", "/api/projects/ed/shots", { aspect_ratio: "9:16", audio: false, shots: ["s01", "s02", "s03"].map((id) => ({ id, model: "m", seconds: 2, prompt: "p" })) });

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1672, height: 941 }, acceptDownloads: true });
  const page = await context.newPage(); const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}/?token=${token}`); await page.goto(`${base}/#/p/ed`);
  await page.locator("nav[aria-label=Project]").getByRole("link", { name: /^Review & Export/ }).click();
  await page.waitForFunction(() => location.hash === "#/p/ed/review"); ok(true, "the sidebar has Review & Export and opens #/p/ed/review");
  await page.getByRole("heading", { name: "Review & Export" }).waitFor();
  ok(await page.getByText("Edit your short video and export or save the project").isVisible(), "the header shows the title and subtitle from the design");
  ok(await page.getByRole("button", { name: "Export Project" }).isVisible() && await page.getByRole("button", { name: "Export Video" }).isVisible(), "Export Project and Export Video buttons are in the header");
  const tools = ["Media", "Text", "Elements", "Audio", "Transitions", "Filters", "Effects", "Subtitles", "Aspect Ratio", "Background"];
  const rail = page.getByRole("navigation", { name: "Editor tools" });
  ok((await rail.getByRole("button").allInnerTexts()).map((s) => s.trim()).join("|") === tools.join("|"), "the left rail has the 10 tools in the design's order");
  await page.locator("[data-testid=vbar-s01]").waitFor();
  ok(await page.locator("[data-testid^=vbar-]").count() === 3, "the timeline starts with the 3 shot clips on the Video track");
  ok((await page.getByTestId("time").innerText()).replace(/\s+/g, " ").includes("00:00 / 00:06"), "time shows 00:00 / 00:06");
  ok((await page.locator(".re-tl-label").allInnerTexts()).map((s) => s.trim()).join() === "Text,Video,Audio", "track labels are Text, Video, Audio");
  await page.waitForFunction(() => document.querySelectorAll(".re-film img").length >= 3, null, { timeout: 15000 }).catch(() => {});
  ok(await page.locator(".re-film img").count() >= 3, "the video track shows filmstrip thumbnails");

  await page.evaluate(() => window.scrollTo(0, 0));
  ok(await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight + 2), "the whole screen fits a 1672x941 window without page scrolling, like the design");

  // ---- text
  await rail.getByRole("button", { name: "Text" }).click();
  await page.getByRole("button", { name: "Caption bubble" }).click();
  const insp = page.getByTestId("inspector");
  await insp.getByRole("heading", { name: "Text" }).waitFor();
  ok((await insp.getByLabel("Text", { exact: true }).inputValue()) === "Turn Ideas into\nStunning Videos", "adding a caption opens the Text inspector with its text");
  ok((await insp.innerText()).includes("31/100"), "the character counter shows the length (31/100)");
  for (const l of ["Font", "Size", "Color", "Alignment", "Style", "Opacity", "Shadow", "Blur"]) if (!(await insp.getByText(l, { exact: true }).first().isVisible())) ok(false, `inspector row ${l}`);
  ok(true, "the inspector has Font, Size, Color, Alignment, Style, Opacity, Shadow and Blur rows");
  await insp.getByLabel("Text", { exact: true }).fill("Hello world");
  ok(await page.getByTestId("overlay-text").innerText() === "Hello world", "typing updates the text on the preview");
  ok((await insp.innerText()).includes("11/100"), "the counter follows the typing");
  await insp.getByRole("button", { name: "Align left" }).click();
  ok(await insp.getByRole("button", { name: "Align left" }).getAttribute("aria-pressed") === "true", "alignment buttons toggle");
  await insp.getByRole("button", { name: "Underline" }).click();
  ok((await page.getByTestId("overlay-text").evaluate((e) => getComputedStyle(e).textDecorationLine)) === "underline", "underline shows in the preview");
  await insp.getByRole("button", { name: "Larger" }).click();
  ok(await insp.getByLabel("Size").inputValue() === "58", "the size stepper steps by 2");
  await insp.getByLabel("Shadow", { exact: true }).click();
  ok(await insp.getByLabel("Shadow", { exact: true }).getAttribute("aria-checked") === "true", "the shadow switch turns on");
  // drag the text in the preview
  const ov = page.getByTestId("overlay-" + (await page.locator("[data-testid^=tbar-]").first().getAttribute("data-testid")).replace("tbar-", ""));
  const b0 = await ov.boundingBox();
  await page.mouse.move(b0.x + b0.width / 2, b0.y + b0.height / 2); await page.mouse.down(); await page.mouse.move(b0.x + b0.width / 2 + 40, b0.y + b0.height / 2 - 60, { steps: 6 }); await page.mouse.up();
  const b1 = await ov.boundingBox(); ok(b1.x > b0.x + 20 && b1.y < b0.y - 30, "dragging the text in the preview moves it");

  // ---- autosave
  await page.waitForFunction(() => document.querySelector("[data-testid=save-state]")?.textContent === "Saved", null, { timeout: 8000 });
  let saved = (await api("GET", "/api/projects/ed/edit")).json;
  ok(saved.saved && saved.edit.tracks.text[0].text === "Hello world" && saved.edit.tracks.text[0].underline && saved.edit.tracks.text[0].x > 0.5 - 0.5, "the edit is auto-saved to edit.json");
  ok(saved.edit.tracks.text[0].y < 0.62, "the dragged position was saved");

  // ---- transition + total time
  await page.locator("[data-testid=vbar-s02]").click({ position: { x: 60, y: 20 } });
  await insp.getByRole("heading", { name: "Clip", exact: true }).waitFor();
  await insp.getByRole("button", { name: "Crossfade" }).click();
  ok((await page.getByTestId("time").innerText()).replace(/\s+/g, " ").includes("/ 00:05"), "a 0.5 s crossfade shortens the total (5.5 s shows as 00:05)");

  await insp.getByLabel("Transition into this clip").selectOption("dissolve");
  ok(await insp.getByLabel("Transition into this clip").inputValue() === "dissolve" && (await insp.getByLabel("Transition into this clip").locator("optgroup").count()) >= 7, "the transition list has Dissolve and 7 groups of transitions");
  ok((await api("GET", "/api/projects/ed/edit")).status === 200 && (await page.getByTestId("time").innerText()).replace(/\s+/g, " ").includes("/ 00:05"), "a dissolve overlaps the clips like a crossfade");

  // ---- split
  await page.getByRole("slider", { name: "Seek" }).evaluate((el) => { const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set; set.call(el, "1"); el.dispatchEvent(new Event("input", { bubbles: true })); });
  await page.locator("[data-testid=vbar-s01]").click({ position: { x: 30, y: 20 } });
  await page.getByRole("button", { name: "Split at playhead" }).click();
  await page.waitForFunction(() => document.querySelectorAll("[data-testid^=vbar-]").length === 4);
  ok(true, "Split at playhead cuts the selected clip in two (4 clips)");
  // ---- undo / redo
  await page.getByRole("button", { name: "Undo" }).first().click();
  await page.waitForFunction(() => document.querySelectorAll("[data-testid^=vbar-]").length === 3); ok(true, "Undo restores the clip");
  await page.getByRole("button", { name: "Redo" }).first().click();
  await page.waitForFunction(() => document.querySelectorAll("[data-testid^=vbar-]").length === 4); ok(true, "Redo splits it again");
  await page.keyboard.press("Control+z"); await page.waitForFunction(() => document.querySelectorAll("[data-testid^=vbar-]").length === 3); ok(true, "Ctrl+Z works from the keyboard");

  // ---- audio upload
  await rail.getByRole("button", { name: "Audio" }).click();
  await page.getByLabel("Upload a sound file").setInputFiles(wav);
  await page.locator("[data-testid^=abar-]").first().waitFor({ timeout: 10000 }); ok(true, "uploading a sound adds it to the Audio track");
  await page.waitForFunction(() => { const c = document.querySelector(".re-wave"); return c && c.width > 10; }); ok(true, "the waveform canvas is drawn");
  await insp.getByRole("heading", { name: "Audio" }).waitFor();
  await insp.getByLabel("Fade out").evaluate((el) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, "1"); el.dispatchEvent(new Event("input", { bubbles: true })); });
  ok((await insp.innerText()).includes("1.0s"), "the audio fade-out slider updates its value");
  // ---- playback
  await page.getByRole("button", { name: "Play", exact: true }).click(); await sleep(1500);
  const tNow = (await page.getByTestId("time").innerText()).replace(/\s+/g, " ");
  ok(!tNow.startsWith("00:00 /"), "Play advances the playhead (" + tNow + ")");
  await page.getByRole("button", { name: "Pause", exact: true }).click();

  await page.screenshot({ path: join(shots, "review-export.png") });
  const ax = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  ok(ax.violations.length === 0, "no accessibility violations on Review & Export" + (ax.violations.length ? ": " + ax.violations.map((v) => `${v.id}(${v.nodes.length}) ${v.nodes[0].target}`).join("; ") : ""));

  // ---- responsive: phone width has no sideways page scroll and the tools stay reachable
  for (const [w, h, n] of [[390, 844, "phone"], [900, 800, "tablet"]]) {
    await page.setViewportSize({ width: w, height: h }); await sleep(300);
    ok(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1), `no sideways page scroll on a ${n}`);
    ok(await page.getByRole("button", { name: "Export Video" }).isVisible() && await page.getByRole("button", { name: "Split at playhead" }).isVisible(), `Export Video and the timeline tools are reachable on a ${n}`);
  }
  await page.setViewportSize({ width: 1672, height: 941 });

  // ---- export video
  await page.getByRole("button", { name: "Export Video" }).click();
  await page.getByRole("button", { name: "Start export" }).click();
  await page.getByTestId("export-result").waitFor({ timeout: 90000 }); ok(true, "Export Video renders with ffmpeg and shows the result");
  const ex = (await api("GET", "/api/projects/ed/exports")).json.exports;
  ok(ex.length === 1 && ex[0].bytes > 2000 && existsSync(join(pdir, ex[0].file)), "the MP4 is saved in the project's exports folder");
  const dur = parseFloat(execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", join(pdir, ex[0].file)]).toString());
  ok(dur > 5.3 && dur < 6.5, `exported length matches the edit (${dur.toFixed(2)} s)`);
  await page.getByRole("button", { name: "Done" }).click();

  // ---- export project (zip)
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Export Project" }).click()]);
  ok(dl.suggestedFilename() === "ed.zip", "Export Project downloads ed.zip");
  const zp = join(tmpdir(), "e2e-ed.zip"); await dl.saveAs(zp); ok(statSync(zp).size > 1000, "the zip has content");
  const listing = execFileSync("unzip", ["-l", zp]).toString();
  ok(/ed\/edit\.json/.test(listing) && /ed\/clips\/s01_final_a1\.mp4/.test(listing) && /ed\/exports\//.test(listing), "the zip holds edit.json, the clips and the exports");

  // ---- delete + restore
  await page.getByRole("button", { name: "More actions" }).click();
  await page.getByRole("menuitem", { name: /Delete project/ }).click();
  const dlg = page.getByRole("dialog"); await dlg.getByLabel(/Type the project name/).fill("wrong"); await dlg.getByRole("button", { name: "Move to trash" }).click();
  await page.getByText(/does not match/).waitFor(); ok((await api("GET", "/api/projects")).json.projects.length === 1, "a wrong name deletes nothing");
  await page.getByRole("button", { name: "More actions" }).click(); await page.getByRole("menuitem", { name: /Delete project/ }).click();
  await page.getByRole("dialog").getByLabel(/Type the project name/).fill("ed"); await page.getByRole("dialog").getByRole("button", { name: "Move to trash" }).click();
  await page.waitForFunction(() => location.hash === "#/"); ok(true, "deleting returns to the projects page");
  await page.getByRole("tab", { name: /All Projects/ }).waitFor();
  await page.waitForFunction(() => [...document.querySelectorAll("[role=tab]")].some((t) => /Archived/.test(t.textContent) && /1/.test(t.textContent)));
  ok(await page.getByTestId("trash").count() === 0 && (await page.getByRole("tab", { name: /Archived/ }).innerText()).includes("1"), "a deleted project is not listed on All Projects; the Archived tab counts it");
  await page.getByRole("tab", { name: /Archived/ }).click(); await page.getByTestId("trash").waitFor();
  ok((await api("GET", "/api/projects")).json.projects.length === 0 && existsSync(join(home, "_trash")), "the project left the list and went to _trash (not erased)");
  await page.getByRole("button", { name: "Restore ed" }).click();
  await page.waitForFunction(() => !document.querySelector("[data-testid=trash]"));
  ok((await api("GET", "/api/projects")).json.projects.length === 1 && existsSync(join(pdir, "edit.json")), "Restore brings the project back with its edit");
  // project card menu
  await page.getByRole("tab", { name: /All Projects/ }).click(); await page.getByRole("button", { name: "Actions for ed" }).click(); ok(await page.getByRole("menuitem", { name: /Export project \(zip\)/ }).isVisible() && await page.getByRole("menuitem", { name: /Delete project/ }).isVisible(), "the project card menu offers export and delete");
  await page.keyboard.press("Escape");

  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  await browser.close();
} catch (e) { console.log("FAIL exception: " + (e.stack || e)); failed = true; }
finally { srv.kill(); }
process.exit(failed ? 1 : 0);
