// Agent workflow e2e (test mode, $0): an agent proposes through MCP -> a human approves in the page -> it runs.
import { chromium } from "playwright";
import { go } from "./nav.mjs";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-agent-"));
const shots = process.env.SHOTS_DIR || join(tmpdir(), "aistudio-shots"); mkdirSync(shots, { recursive: true });
const port = 8812, token = "agenttoken", base = `http://127.0.0.1:${port}`;
const env = { ...process.env, AISTUDIO_HOME: home, AISTUDIO_TOKEN: token, AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1" };
const py = join(repo, ".venv/bin/python");
const srv = spawn(py, ["-m", "server.app"], { cwd: repo, env });
let failed = false; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) failed = true; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const api = async (method, path, body) => (await fetch(base + path, { method, headers: { "x-aistudio-token": token, "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined })).json();

// MCP client over stdio
const mcp = spawn(py, ["-m", "aistudio.mcp_server"], { cwd: repo, env });
let buf = "", id = 0; const waiters = new Map();
mcp.stdout.on("data", (d) => { buf += d; let i; while ((i = buf.indexOf("\n")) >= 0) { const line = buf.slice(0, i); buf = buf.slice(i + 1); if (line) { const m = JSON.parse(line); waiters.get(m.id)?.(m); } } });
const rpc = (method, params) => new Promise((res) => { const i = ++id; waiters.set(i, res); mcp.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: i, method, params }) + "\n"); });
const tool = async (name, args) => { const r = await rpc("tools/call", { name, arguments: args }); return { err: r.result.isError, data: JSON.parse(r.result.content[0].text) }; };

try {
  for (let i = 0; i < 40; i++) { try { if ((await fetch(base + "/api/health")).ok) break; } catch {} await sleep(250); }
  await rpc("initialize", {});
  ok((await tool("create_project", { name: "agentdemo" })).data.name === "agentdemo", "agent created a project via MCP");
  await tool("write_doc", { name: "agentdemo", doc: "Story.md", text: readFileSync(join(here, "story.md"), "utf-8") });
  ok((await tool("convert_story", { name: "agentdemo" })).data.shots.shots.length === 3, "agent converted the storyboard");
  await tool("estimate", { name: "agentdemo", failure: 0.2 });
  const prop = await tool("propose", { name: "agentdemo", kind: "image", target: "s01" });
  ok(!prop.err && prop.data.status === "pending" && !("code" in prop.data), "agent proposed an image; no approval code was given to it");
  const early = await tool("run_proposal", { name: "agentdemo", id: prop.data.id });
  ok(early.err, "agent could not run it before approval");
  const tools = (await rpc("tools/list", {})).result.tools.map((t) => t.name);
  ok(!tools.some((t) => /approve|(^|_)mode(_|$)/.test(t)), "MCP exposes no approval or mode tools");

  const browser = await chromium.launch(); const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
  page.on("dialog", (d) => d.accept());
  await page.goto(`${base}/?token=${token}#/p/agentdemo`);
  await go(page, "Costs");
  await page.getByRole("button", { name: "Approve budget" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Approve", exact: true }).click(); await page.getByText("approved").first().waitFor();
  await go(page, "Overview");
  await page.getByText("Waiting for your decision").waitFor(); ok(true, "human sees the agent's proposal waiting for a decision");
  await new Promise((r) => setTimeout(r, 900)); await page.screenshot({ path: join(shots, "9-waiting.png") });
  await page.getByRole("button", { name: "Approve and run" }).click();
  await page.getByText(/Done: stills/).waitFor({ timeout: 20000 }); ok(true, "human approved and it ran");
  await page.screenshot({ path: join(shots, "10-after.png") });
  ok((await tool("get_proposal", { name: "agentdemo", id: prop.data.id })).data.status === "used", "proposal is used (single-use)");
  const again = await tool("run_proposal", { name: "agentdemo", id: prop.data.id });
  ok(again.err, "an approval cannot be reused");
  const o = await api("GET", "/api/projects/agentdemo");
  ok(Math.abs(o.costs.total - 0.036) < 1e-9, "exactly one image was billed ($0.036 in test-mode units)");
  await browser.close();
} catch (e) { console.log("FAIL exception: " + e.message.split("\n")[0]); failed = true; }
finally { srv.kill(); mcp.kill(); }
process.exit(failed ? 1 : 0);
