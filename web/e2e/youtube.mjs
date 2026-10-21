// Human-only YouTube OAuth and fake upload transport smoke. No Google network calls are made.
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import net from "node:net";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../..");
const home = mkdtempSync(join(tmpdir(), "aistudio-youtube-"));
const freePort = () => new Promise((resolvePort) => { const s = net.createServer(); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolvePort(p)); }); });
const port = await freePort();
const token = "youtube-e2e-human";
const base = `http://127.0.0.1:${port}`;
const server = spawn(join(repo, ".venv/bin/python"), ["-m", "server.app"], {
  cwd: repo,
  env: { ...process.env, AISTUDIO_HOME: home, AISTUDIO_SECRETS_DIR: join(home, "secrets"), AISTUDIO_TOKEN: token,
    AISTUDIO_PORT: String(port), AISTUDIO_ALL_TEST: "1", AISTUDIO_NO_NETWORK: "1", AISTUDIO_FAKE_YOUTUBE: "1" },
  stdio: "ignore",
});
const H = { "x-aistudio-token": token, "content-type": "application/json" };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const api = async (method, path, body, headers = H) => {
  const response = await fetch(base + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: response.status, body: await response.json().catch(() => ({})) };
};
let failed = false;
const ok = (value, label) => { console.log(`${value ? "PASS" : "FAIL"} ${label}`); if (!value) failed = true; };
try {
  let ready = false;
  for (let i = 0; i < 50; i++) { try { if ((await fetch(base + "/api/health")).ok) { ready = true; break; } } catch {} await sleep(200); }
  ok(ready, "server started in fake YouTube test mode");
  let result = await api("PUT", "/api/youtube/client", { client_id: "test-client-id", client_secret: "never-return-this-secret" });
  ok(result.status === 200 && !JSON.stringify(result.body).includes("never-return-this-secret"), "OAuth client is write-only");
  result = await api("POST", "/api/youtube/connect", {});
  const authorize = new URL(result.body.url);
  const redirect = authorize.searchParams.get("redirect_uri");
  const state = authorize.searchParams.get("state");
  const callback = new URL(redirect);
  callback.searchParams.set("code", "fake-code"); callback.searchParams.set("state", state);
  const callbackResult = await fetch(callback);
  ok(callbackResult.ok, "PKCE callback succeeds using only fake transport");
  result = await api("GET", "/api/youtube/status");
  ok(result.status === 200 && result.body.connected && result.body.channel_title === "AI Studio Test Channel" && !JSON.stringify(result.body).includes("token"), "status returns channel only, never tokens");
  const key = await api("POST", "/api/keys", { name: "youtube-e2e-agent" });
  const agentHeaders = { "x-aistudio-token": key.body.key, "content-type": "application/json" };
  result = await api("GET", "/api/youtube/status", undefined, agentHeaders);
  ok(result.status === 403, "API keys cannot read YouTube status");
  result = await api("POST", "/api/projects/test/publish/youtube", { confirm_title: "anything" }, agentHeaders);
  ok(result.status === 403, "API keys cannot start a YouTube upload");
  result = await api("POST", "/api/youtube/disconnect", {});
  ok(result.status === 200 && result.body.connected === false, "disconnect removes the OAuth session");
} catch (e) { console.log("FAIL " + e.message); failed = true; }
finally { server.kill(); rmSync(home, { recursive: true, force: true }); }
process.exit(failed ? 1 : 0);
