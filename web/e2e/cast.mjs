// Cast UI smoke check in test mode ($0): consent entry (human, sha-bound), identity sheet button showing batch price,
// variants N picker showing N x price, version strip select, drift badge, remix proposal creation.
import { chromium } from "playwright";
import { go } from "./nav.mjs";
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), repo = resolve(here, "../.."), home = mkdtempSync(join(tmpdir(), "aistudio-cast-"));
const port = 8831, token = "casttoken", base = `http://127.0.0.1:${port}`;
const srv = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], {
  cwd: repo,
  env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" }
});
srv.stderr?.on("data", (d) => console.log("SERVER STDERR:", d.toString()));
srv.stdout?.on("data", (d) => console.log("SERVER STDOUT:", d.toString()));
let failed = false;
const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");

try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(`${base}/api/health`)).ok) break; } catch {} await sleep(250); }
  const browser = await chromium.launch(), page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (msg) => console.log("PAGE CONSOLE:", msg.type(), msg.text()));

  await page.goto(`${base}/?token=${token}`);
  await page.getByPlaceholder(/project-name/).fill("castdemo");
  await page.getByRole("button", { name: "Create" }).click();
  await page.getByRole("log", { name: "Conversation" }).waitFor({ timeout: 15000 });
  await go(page, "Assets");

  // Click the Characters tab
  await page.getByRole("tab", { name: "Characters" }).click();

  // Click "Add Character" button in the add-tile
  await page.getByRole("button", { name: /Add Character/ }).first().click();
  await page.getByLabel("Asset id").fill("maya");
  await page.getByLabel("Asset description").fill("Test character");
  await page.getByRole("button", { name: "Add", exact: true }).click();

  // Open maya in the preview rail
  await page.locator('[data-asset="maya"]').waitFor({ state: "attached" });
  await page.locator('[data-asset="maya"]').getByRole("button", { name: /Open maya in the preview/ }).click();

  // The CastPanel should now be visible in the right rail
  await page.getByTestId("cast-panel").waitFor({ timeout: 10000 });

  // Baseline assertions before master image is uploaded
  ok(await page.getByRole("button", { name: /Build identity sheet/ }).isVisible(), "identity sheet control is shown");
  ok(await page.getByLabel("Consent subject").isVisible(), "consent form has subject input");
  ok(await page.getByLabel("Consent statement").isVisible(), "consent form asks for a written statement");
  ok(await page.getByLabel("Consent kind").isVisible(), "consent form has kind select");
  ok(await page.getByLabel("Number of candidates").isVisible(), "variant count picker is labelled");
  ok(await page.getByRole("button", { name: /Check drift/ }).isVisible(), "drift check button is shown");
  await page.getByText("No other versions yet").waitFor();

  // Master image: upload PNG for maya
  await page.locator('[data-asset="maya"]').getByLabel("Upload image for maya").setInputFiles({ name: "maya.png", mimeType: "image/png", buffer: PNG });
  await page.waitForTimeout(3000);
  const keepBtn = page.getByRole("button", { name: "Keep as Character Image Anyway" });
  if (await keepBtn.isVisible().catch(() => false)) {
    await keepBtn.click();
  }
  await page.locator('[data-asset="maya"]').getByRole("button", { name: /Open maya in the preview/ }).click();
  await page.getByTestId("cast-panel").waitFor({ timeout: 10000 });

  // 1. Identity sheet button showing batch price (5 views * 0.036 = $0.180 in test mode)
  await page.getByRole("button", { name: /Build identity sheet.*\$0\.18/ }).waitFor({ timeout: 8000 });
  ok(true, "identity sheet button shows batch price ($0.180)");

  // 2. Variants N picker showing N x price
  await page.getByRole("button", { name: /Generate 2 variants · 2 × \$0\.036 \(\$0\.072\)/ }).waitFor({ timeout: 8000 });
  await page.getByLabel("Number of candidates").selectOption("3");
  await page.getByRole("button", { name: /Generate 3 variants · 3 × \$0\.036 \(\$0\.108\)/ }).waitFor({ timeout: 8000 });
  ok(true, "variants N picker shows N x price (2x and 3x)");

  // 3. Consent entry (human, sha-bound)
  // Mark current file as a real person to bind sha
  await page.getByRole("button", { name: "Mark current file as a real person" }).click();
  await page.getByRole("button", { name: /File marked ·/ }).waitFor({ timeout: 8000 });
  ok(true, "asset file is marked with sha for consent binding");

  await page.getByLabel("Consent subject").fill("Maya");
  await page.getByLabel("Consent statement").fill("I consent to be shown in this video");
  await page.getByRole("button", { name: "Record consent" }).click();
  await page.getByText("Consent recorded for Maya.").waitFor({ timeout: 8000 });
  await page.getByText(/Maya \(real person.*I consent to be shown/).waitFor({ timeout: 8000 });
  ok(true, "consent entry (human, sha-bound) is recorded and listed");

  // 4. Remix proposal creation
  const projectStills = join(home, "projects", "castdemo", "stills");
  const meta = {
    kind: "image",
    target: "maya",
    model: "fake/image",
    provider: "fake",
    prompt: "Maya in market",
    refs: [],
    params: {},
    cost: 0.036
  };
  writeFileSync(join(projectStills, "maya.png.meta.json"), JSON.stringify(meta));

  // The Remix button in AssetPreview rail
  await page.getByRole("button", { name: "Remix" }).click();
  await page.getByRole("heading", { name: "Approve this paid action?" }).waitFor({ timeout: 8000 });
  ok(true, "remix proposal creation opens approval modal");
  await page.getByRole("button", { name: "Cancel" }).click();

  // 5. Version strip select
  // Create versions maya.v1.png and maya.v2.png
  writeFileSync(join(projectStills, "maya.v1.png"), PNG);
  writeFileSync(join(projectStills, "maya.v2.png"), PNG);
  await page.reload();
  await go(page, "Assets");
  await page.getByRole("tab", { name: "Characters" }).click();
  await page.locator('[data-asset="maya"]').click();
  await page.getByTestId("cast-panel").waitFor({ timeout: 10000 });

  await page.getByTestId("variants-strip").waitFor({ timeout: 8000 });
  await page.getByTestId("variants-strip").getByRole("button", { name: "Select version 2 of maya" }).click();
  // Confirm dialog appears
  await page.getByRole("button", { name: "Use version 2" }).click();
  await page.getByText("Using version 2 of maya.").waitFor({ timeout: 8000 });
  await page.getByTestId("variants-strip").getByText("Selected").waitFor({ timeout: 8000 });
  ok(true, "version strip select chooses version and updates selected indicator");

  // 6. Drift badge
  const checksDir = join(home, "projects", "castdemo", "checks");
  mkdirSync(checksDir, { recursive: true });
  writeFileSync(join(checksDir, "maya.json"), JSON.stringify({
    scores: { maya: 0.45 },
    summary: "Drift detected across frames",
    threshold: 0.6
  }));
  await page.reload();
  await go(page, "Assets");
  await page.getByRole("tab", { name: "Characters" }).click();
  await page.locator('[data-asset="maya"]').click();
  await page.getByTestId("cast-panel").waitFor({ timeout: 10000 });

  await page.getByTestId("drift-badge").waitFor({ timeout: 8000 });
  ok(/Drift:.*0\.45.*below 0\.6/.test(await page.getByTestId("drift-badge").innerText()), "drift badge shows low drift warning");

  writeFileSync(join(checksDir, "maya.json"), JSON.stringify({
    scores: { maya: 0.92 },
    summary: "Consistent identity",
    threshold: 0.6
  }));
  await page.reload();
  await go(page, "Assets");
  await page.getByRole("tab", { name: "Characters" }).click();
  await page.locator('[data-asset="maya"]').click();
  await page.getByTestId("cast-panel").waitFor({ timeout: 10000 });

  await page.getByTestId("drift-badge").waitFor({ timeout: 8000 });
  ok(/Identity match:.*0\.92/.test(await page.getByTestId("drift-badge").innerText()), "drift badge shows passing identity match");

  await browser.close();
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  console.log("FAIL exception: " + e.message.split("\n").slice(0, 3).join(" | "));
  failed = true;
} finally {
  srv.kill("SIGTERM");
}
if (failed) process.exitCode = 1;
