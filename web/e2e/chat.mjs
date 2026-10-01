// Chat with Tara e2e (test mode, $0): interview -> drafted storyboard -> apply -> automatic budget popup -> TODO progress.
import { chromium } from "playwright";
import { go } from "./nav.mjs";
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-chat-"));
const shots = process.env.SHOTS_DIR || join(tmpdir(), "aistudio-shots"); mkdirSync(shots, { recursive: true });
const port = 8814, token = "chattoken";
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], { cwd: repo, env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" } });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`http://127.0.0.1:${port}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch(); const page = await browser.newPage({ viewport: { width: 1300, height: 950 } });
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`http://127.0.0.1:${port}/?token=${token}`);
  await page.getByPlaceholder(/project-name/).fill("chatdemo"); await page.getByRole("button", { name: "Create" }).click();
  await page.getByRole("log", { name: "Conversation" }).waitFor(); ok(true, "a new project opens on the Chat tab");
  ok(await page.getByText("Model & Settings").count() === 0, "the Chat screen has no side panels (brief and TODO live on Overview and Storyboard)");
  await page.getByRole("button", { name: "Start", exact: true }).click();
  await page.getByText(/What is the brand/).waitFor(); ok(true, "the producer asks the first question");
  ok(await page.getByRole("heading", { name: "Chat with Tara" }).isVisible() && /I'm Tara/.test(await page.getByRole("log").innerText()) && (await page.locator(".chat-bubble b", { hasText: "Tara" }).count()) >= 1, "the chat AI is called Tara: in the title, its greeting and the label on its messages");
  const answers = ["Chai Corner, a street tea stall", "Get more walk-ins", "Meena pours tea. Customers smile. She waves goodbye.", "12", "English", "Meena, 40s, cotton saree, warm smile", "A small street tea stall in the morning", "5"];
  for (let i = 0; i < answers.length; i++) {
    await page.getByPlaceholder(/Describe your idea/).fill(answers[i]); await page.getByRole("button", { name: "Send" }).click();
    await page.getByText(answers[i], { exact: true }).first().waitFor();
    await page.waitForFunction((n) => document.querySelectorAll("[role=log] .chat-bubble").length >= n, (i + 1) * 2 + 2, { timeout: 10000 });
  }
  ok(true, "each answer gets a producer reply");
  await page.screenshot({ path: join(shots, "11-chat.png") });
  // before drafting, the producer asks about the logo and brand colours; the user attaches a logo
  await page.getByText(/logo or other files/i).first().waitFor(); ok(true, "the producer asks about a logo and brand colours before drafting the story");
  const logo = join(tmpdir(), "e2e-logo.png"); execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0xf08c14:s=120x120", "-frames:v", "1", logo]);
  await page.getByLabel(/Attach an image \(logo/).setInputFiles(logo);
  await page.getByTestId("pending-attachment").waitFor(); ok(true, "an attached logo shows as a chip before it is sent");
  await page.getByPlaceholder(/Describe your idea/).fill("Yes, use my brand colours"); await page.getByRole("button", { name: "Send" }).click();
  await page.getByTestId("msg-attachments").locator("img").waitFor(); ok(await page.getByAltText("Attached image e2e_logo").isVisible(), "the sent message shows the attached logo in the chat");
  await page.getByText(/I wrote Story\.md/).first().waitFor(); ok(true, "the finished brief becomes Story.md and TODO.md by itself");
  const story = (await (await fetch(`http://127.0.0.1:${port}/api/projects/chatdemo/docs/Story.md`, { headers: { "x-aistudio-token": token } })).json()).text;
  const hex = (story.match(/Brand colours: (#[0-9a-f]{6})/i) || [])[1] || "#000000"; const near = [1, 3, 5].every((i, k) => Math.abs(parseInt(hex.slice(i, i + 2), 16) - [240, 140, 20][k]) <= 12);   // ffmpeg's PNG is a few shades off the colour we asked for
  ok(/## Shared style/.test(story) && near && /## Characters/.test(story) && /## Backgrounds/.test(story), "Story.md has a shared style with the logo's colours (" + hex + "), characters and backgrounds");
  const imgs = (await (await fetch(`http://127.0.0.1:${port}/api/projects/chatdemo`, { headers: { "x-aistudio-token": token } })).json()).images.images;
  ok(imgs.some((i) => i.id === "e2e_logo" && i.kind === "other") && imgs.some((i) => i.kind === "character") && imgs.some((i) => i.kind === "background") && imgs.filter((i) => i.kind === "frame").length === 3, "the asset list has the uploaded logo, a character, a background and 3 scene frames");
  await page.getByRole("dialog").getByText("Set the budget").first().waitFor(); ok(true, "budget popup opens automatically after applying the storyboard");
  await page.getByRole("dialog").getByText(/estimated total/).waitFor();
  await page.screenshot({ path: join(shots, "12-budget-popup.png") });
  await page.getByRole("dialog").getByRole("button", { name: /Approve budget/ }).click();
  await page.getByText(/Budget approved/).first().waitFor(); ok(true, "budget approved from the popup");
  // the checklist knows the budget is approved and leads through the assets in order
  await page.getByTestId("checklist").waitFor();
  await page.waitForFunction(() => /Budget approved\s*1\/1/.test(document.querySelector("[data-testid=checklist]")?.innerText || ""), null, { timeout: 8000 }); ok(true, "the chat checklist shows the budget as approved");
  await page.waitForFunction(() => /character image: meena/i.test(document.querySelector("[data-testid=next-step]")?.textContent || ""), null, { timeout: 8000 });
  ok(/character image: meena/i.test(await page.getByTestId("next-step").innerText()), "the next step is the character image (assets before scene frames and clips)");
  ok(await page.getByTestId("generate-all").isVisible() && /Generate all \(\d+\)/.test(await page.getByTestId("generate-all").innerText()), "a Generate all button sits next to Generate");
  await page.getByTestId("next-action").click(); await page.getByText("Approve this paid action?").waitFor();
  await page.getByRole("button", { name: /Approve and run/ }).click();
  await page.waitForFunction(() => document.querySelector("[data-testid=next-action]")?.disabled === true);
  ok(await page.getByTestId("generate-all").isDisabled() && /Generating/.test(await page.getByTestId("next-action").innerText()) && await page.getByTestId("next-action").locator("svg.animate-spin").count() === 1, "while one item is being made both buttons are disabled and show a loader");
  await page.waitForFunction(() => /background image: main_place/i.test(document.querySelector("[data-testid=next-step]")?.textContent || ""), null, { timeout: 15000 });
  ok(true, "after the character image is generated the checklist moves on to the background");
  await page.waitForFunction(() => document.querySelector("[data-testid=next-action]")?.disabled === false);
  // Generate all: one approval for the whole list with every exact price, then the items run in order
  await page.getByTestId("generate-all").click(); await page.getByTestId("plan").waitFor();
  const items = await page.getByTestId("plan").locator("li").allInnerTexts();
  ok(items.length === 7 && /main_place/.test(items[0]) && /s01/.test(items[1]) && /video clip: s01/.test(items[4]) && items.every((t) => /\$\d/.test(t)), "the plan lists the remaining images then clips, each with its price (" + items.length + " items)");
  ok(/\$\d/.test(await page.getByTestId("plan-total").innerText()), "and shows the total");
  await page.getByTestId("approve-all").click();
  await page.getByTestId("batch-status").waitFor(); ok(await page.getByTestId("generate-all").isDisabled() && await page.getByTestId("next-action").isDisabled(), "during Generate all both buttons are disabled with a loader and the progress is shown");
  await page.waitForFunction(() => /Watch and approve clip s01/i.test(document.querySelector("[data-testid=next-step]")?.textContent || ""), null, { timeout: 60000 });
  const grp = await page.getByTestId("checklist").innerText();
  ok(/Scene frames\s*3\/3/.test(grp) && /Video clips\s*3\/3/.test(grp), "Generate all made every frame and clip in order (" + grp.replace(/\s+/g, " ").slice(0, 160) + ")");
  await sleep(900); await page.screenshot({ path: join(shots, "14-chat-checklist.png") });
  await go(page, "Overview"); await page.waitForFunction(() => location.hash === "#/p/chatdemo"); await page.getByText("Approve the storyboard").first().waitFor();
  const body = await page.locator("body").innerText();
  ok(/Approve the storyboard/.test(body) && /Set and approve the budget/.test(body), "TODO list shows the automatic steps");
  await page.getByRole("checkbox", { name: /Native speaker/ }).click();
  await page.waitForFunction(() => [...document.querySelectorAll("input[type=checkbox]")].some((c) => (c.getAttribute("aria-label") || "").includes("Native speaker") && c.checked)); ok(true, "a manual TODO can be ticked and is saved");
  await page.getByPlaceholder("Add a task").fill("Get the shop logo"); await page.keyboard.press("Enter"); await page.getByText("Get the shop logo").waitFor(); ok(true, "a custom TODO can be added");
  await page.screenshot({ path: join(shots, "13-todos.png") });
  await go(page, "Shots"); await page.getByRole("button", { name: "Open shot s01" }).waitFor(); ok(true, "the applied storyboard became shots");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  await browser.close();
} catch (e) { console.log("FAIL exception: " + e.message.split("\n")[0]); failed = true; }
finally { srv.kill(); }
process.exit(failed ? 1 : 0);
