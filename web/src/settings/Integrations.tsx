import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Cpu, KeyRound, Play, Plug, Plus, ShieldCheck, Square, Terminal, Trash2 } from "lucide-react";
import { api, getToken } from "../api";
import { Button, Card, IconTile, Input, Modal } from "../ui";
import { useToast } from "../toast";
import { confirmDialog } from "../dialogs";
import CodeBlock from "../components/CodeBlock";

interface Info { mcp: { python: string; repo: string; home: string; module: string }; tools: { name: string; description: string }[]; base_url: string }
interface Key { id: string; name: string; prefix: string; created: string; last_used: string | null }
interface AgentInfo { id: string; name: string; binary: string | null; detected: boolean; description: string }
type Client = "claude" | "agy" | "opencode" | "other";

const sh = (s: string) => (/^[\w@%+=:,./-]+$/.test(s) ? s : `'${s.replace(/'/g, `'\\''`)}'`);

/** Snippets that connect an AI agent (Claude Code, Antigravity CLI, OpenCode, any MCP client) to this install. */
export function mcpSnippets(i: Info) {
  const env = { PYTHONPATH: i.mcp.repo, AISTUDIO_HOME: i.mcp.home };
  return {
    claude: `claude mcp add ai-studio -e PYTHONPATH=${sh(env.PYTHONPATH)} -e AISTUDIO_HOME=${sh(env.AISTUDIO_HOME)} -- ${sh(i.mcp.python)} -m ${i.mcp.module}`,
    agy: `agy skill add ${sh(i.mcp.repo)}/.agents/skills/aistudio`,
    opencode: JSON.stringify({ $schema: "https://opencode.ai/config.json", model: "opencode/mimo-v2.6-flash-free", mcp: { "ai-studio": { type: "local", command: [i.mcp.python, "-m", i.mcp.module], enabled: true, environment: env } } }, null, 2),
    other: JSON.stringify({ mcpServers: { "ai-studio": { command: i.mcp.python, args: ["-m", i.mcp.module], env } } }, null, 2),
  };
}

export default function IntegrationsSection() {
  const toast = useToast();
  const [info, setInfo] = useState<Info | null>(null);
  const [keys, setKeys] = useState<Key[]>([]);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [client, setClient] = useState<Client>("claude");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [fresh, setFresh] = useState<string>("");
  const [showTools, setShowTools] = useState(false);

  // Agent runner state
  const [selectedAgent, setSelectedAgent] = useState<string>("claude");
  const [agentPrompt, setAgentPrompt] = useState<string>("Analyze the project Story.md and suggest 3 shot improvements");
  const [agentOutput, setAgentOutput] = useState<string>("");
  const [agentRunning, setAgentRunning] = useState<boolean>(false);

  const load = useCallback(async () => {
    try {
      const [i, k, a] = await Promise.all([
        api<Info>("GET", "/api/integrations"),
        api<{ keys: Key[] }>("GET", "/api/keys"),
        api<{ agents: AgentInfo[] }>("GET", "/api/agents").catch(() => ({ agents: [] })),
      ]);
      setInfo(i);
      setKeys(k.keys);
      setAgents(a.agents);
      if (a.agents.length > 0 && !a.agents.some((ag) => ag.id === selectedAgent)) {
        setSelectedAgent(a.agents[0].id);
      }
    } catch (e: any) {
      toast("error", e.message);
    }
  }, [toast, selectedAgent]);

  useEffect(() => { void load(); }, [load]);

  const create = async () => {
    setBusy(true);
    try {
      const r = await api<{ key: string }>("POST", "/api/keys", { name: name.trim() });
      setFresh(r.key);
      setName("");
      await load();
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (k: Key) => {
    if (!(await confirmDialog(`Revoke the key "${k.name}" (${k.prefix}...)? Anything using it stops working at once.`, { title: "Revoke API key", ok: "Revoke", danger: true }))) return;
    try {
      await api("DELETE", `/api/keys/${k.id}`);
      toast("ok", "Key revoked.");
      await load();
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  const runAgent = async () => {
    if (!agentPrompt.trim() || agentRunning) return;
    setAgentRunning(true);
    setAgentOutput(`> Invoking terminal agent [${selectedAgent}]...\n`);
    try {
      const resp = await fetch("/api/agents/run", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-aistudio-token": getToken(),
        },
        body: JSON.stringify({
          agent_id: selectedAgent,
          prompt: agentPrompt.trim(),
        }),
      });
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
      }
      const reader = resp.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) return;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value);
        const lines = chunk.split("\n\n");
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const msg = JSON.parse(line.slice(6));
              if (msg.type === "chunk") {
                setAgentOutput((prev) => prev + msg.text);
              } else if (msg.type === "error") {
                setAgentOutput((prev) => prev + "\n[Agent error] " + msg.error + "\n");
              } else if (msg.type === "done") {
                setAgentOutput((prev) => prev + "\n[Agent task complete]\n");
              }
            } catch {}
          }
        }
      }
    } catch (e: any) {
      setAgentOutput((prev) => prev + "\n[Execution failed: " + e.message + "]\n");
    } finally {
      setAgentRunning(false);
    }
  };

  const abortAgent = async () => {
    try {
      await api("POST", "/api/agents/abort", { agent_id: selectedAgent });
      setAgentOutput((prev) => prev + "\n[Terminated by user]\n");
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setAgentRunning(false);
    }
  };

  const snip = info ? mcpSnippets(info) : null;
  const TABS: [Client, string][] = [
    ["claude", "Claude Code"],
    ["agy", "Antigravity CLI"],
    ["opencode", "OpenCode"],
    ["other", "Other MCP client"],
  ];

  return (
    <div className="space-y-5">
      {/* MCP Integration Card */}
      <Card title={<span className="flex items-center gap-2"><IconTile tone="violet"><Plug size={15} /></IconTile> Connect an AI Agent (MCP)</span>}
        sub="Let Claude Code, Antigravity CLI, OpenCode or any MCP client drive your projects, convert storyboards, and propose generations safely.">
        {!info || !snip ? <p className="text-sm text-slate-400">Loading...</p> : (
          <>
            <div role="tablist" aria-label="MCP client" className="mb-3 flex flex-wrap gap-2">
              {TABS.map(([id, label]) => (
                <button key={id} type="button" role="tab" aria-selected={client === id} onClick={() => setClient(id)} className={`pill !px-3 !py-1.5 text-xs ${client === id ? "" : "!bg-slate-900"}`}>{label}</button>
              ))}
            </div>
            {client === "claude" && <p className="mb-2 text-xs text-slate-400">Run this once in your terminal. Check with <code className="text-slate-200">claude mcp list</code>.</p>}
            {client === "agy" && <p className="mb-2 text-xs text-slate-400">Add the AI Studio skill to your Antigravity CLI environment.</p>}
            {client === "opencode" && <p className="mb-2 text-xs text-slate-400">Save as <code className="text-slate-200">opencode.json</code> in your project folder.</p>}
            <CodeBlock code={snip[client]} label={`${client} setup`} lang={client === "claude" || client === "agy" ? "bash" : "json"} />
            <p className="mt-3 flex items-start gap-2 text-xs text-slate-400"><ShieldCheck size={14} className="mt-0.5 shrink-0 text-emerald-300" />Approval by design: Agents can perform all processes end-to-end (budget approvals, proposals, shot reviews, and project management). High-impact actions require confirmation and trigger approval popups in the agent client.</p>
            <button type="button" className="mt-3 text-xs font-semibold text-brand underline-offset-2 hover:underline" onClick={() => setShowTools((v) => !v)} aria-expanded={showTools}>{showTools ? "Hide" : "Show"} the {info.tools.length} available MCP tools</button>
            {showTools && <ul className="mt-2 grid gap-1.5 text-xs sm:grid-cols-2" data-testid="mcp-tools">{info.tools.map((t) => <li key={t.name} className="rounded-lg border border-slate-800 bg-white/[.02] p-2"><code className="font-bold text-slate-100">{t.name}</code><div className="mt-0.5 text-slate-400">{t.description}</div></li>)}</ul>}
          </>
        )}
      </Card>

      {/* Terminal Agent Sidecar Runner Card */}
      <Card title={<span className="flex items-center gap-2"><IconTile tone="sky"><Terminal size={15} /></IconTile> Terminal AI Agents (Sidecar Runner)</span>}
        sub="Dispatch background coding, scriptwriting, and review tasks to local CLI agents with live streaming output.">
        <div className="space-y-4">
          {/* Detected agents list */}
          <div>
            <div className="mb-2 text-xs font-semibold text-slate-300">Installed Terminal Agents</div>
            <div className="grid gap-2 sm:grid-cols-3">
              {agents.map((ag) => (
                <div key={ag.id} className={`rounded-xl border p-3 ${ag.detected ? "border-emerald-500/30 bg-emerald-500/5" : "border-slate-800 bg-slate-900/40"}`}>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold text-slate-200">{ag.name}</span>
                    {ag.detected ? (
                      <span className="flex items-center gap-1 text-[11px] font-medium text-emerald-400"><CheckCircle2 size={12} /> Detected</span>
                    ) : (
                      <span className="flex items-center gap-1 text-[11px] font-medium text-slate-500"><AlertCircle size={12} /> Not in PATH</span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-slate-400">{ag.description}</p>
                  {ag.binary && <div className="mt-2 truncate text-[11px] text-slate-500"><code>{ag.binary}</code></div>}
                </div>
              ))}
            </div>
          </div>

          {/* Test Task Execution Console */}
          <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5"><Cpu size={14} className="text-cyan-400" /> Execute Sidecar Agent Task</span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400">Agent:</span>
                <select
                  value={selectedAgent}
                  onChange={(e) => setSelectedAgent(e.target.value)}
                  className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
                  disabled={agentRunning}
                >
                  {agents.map((ag) => (
                    <option key={ag.id} value={ag.id} disabled={!ag.detected}>
                      {ag.name} {!ag.detected ? "(Not installed)" : ""}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="space-y-3">
              <Input
                value={agentPrompt}
                onChange={(e) => setAgentPrompt(e.target.value)}
                placeholder="Enter prompt or task for the terminal agent..."
                disabled={agentRunning}
                className="w-full text-xs"
              />
              <div className="flex items-center justify-end gap-2">
                {agentRunning ? (
                  <Button variant="danger" size="sm" onClick={abortAgent}>
                    <Square size={13} /> Abort Process
                  </Button>
                ) : (
                  <Button variant="primary" size="sm" onClick={runAgent} disabled={!agentPrompt.trim()}>
                    <Play size={13} /> Run Agent Task
                  </Button>
                )}
              </div>
            </div>

            {agentOutput && (
              <div className="mt-3">
                <div className="mb-1 text-[11px] font-semibold text-slate-400">Agent Output Stream</div>
                <pre className="max-h-60 overflow-y-auto rounded-lg border border-slate-800 bg-black/80 p-3 font-mono text-xs text-emerald-400 whitespace-pre-wrap">
                  {agentOutput}
                </pre>
              </div>
            )}
          </div>
        </div>
      </Card>

      {/* API Keys Card */}
      <Card title={<span className="flex items-center gap-2"><IconTile tone="pink"><KeyRound size={15} /></IconTile> API keys</span>}
        sub="For scripts and tools that call the HTTP API. A key has the same limits as the MCP agent: it cannot approve spending."
        right={<Button variant="pink" size="sm" onClick={() => { setFresh(""); setCreating(true); }} data-testid="new-key"><Plus size={14} />Create key</Button>}>
        {keys.length === 0 ? <p className="rounded-xl border border-dashed border-slate-700 p-4 text-center text-sm text-slate-400">No keys yet. Create one to call the API from a script.</p> : (
          <ul className="divide-y divide-slate-800" data-testid="key-list">
            {keys.map((k) => (
              <li key={k.id} className="flex flex-wrap items-center gap-3 py-2.5 text-sm">
                <span className="min-w-0 flex-1"><span className="block truncate font-semibold">{k.name}</span><span className="block text-xs text-slate-400"><code>{k.prefix}...</code> · created {k.created.replace("T", " ")} · {k.last_used ? `last used ${k.last_used.replace("T", " ")}` : "never used"}</span></span>
                <Button variant="outline" size="sm" aria-label={`Revoke ${k.name}`} onClick={() => revoke(k)}><Trash2 size={13} />Revoke</Button>
              </li>
            ))}
          </ul>
        )}
        {info && <div className="mt-4"><div className="mb-1.5 text-xs font-semibold text-slate-300">Example (replace the key)</div>
          <CodeBlock code={`curl -H "Authorization: Bearer aisk_YOUR_KEY" ${info.base_url}/api/projects`} label="curl example" lang="bash" /></div>}
        <p className="mt-3 text-xs text-slate-400">The full list of endpoints, and which ones a key may call, is in Help &amp; Docs under API &amp; Integrations.</p>
      </Card>

      {/* Create Key Modal */}
      <Modal open={creating} onClose={() => { setCreating(false); setFresh(""); }} title={fresh ? "Your new API key" : "Create an API key"}>
        {fresh ? (
          <div className="space-y-3" data-testid="new-key-result">
            <p className="text-sm text-amber-200">Copy it now. For safety it is shown only once and cannot be read back later.</p>
            <CodeBlock code={fresh} label="API key" />
            <div className="flex justify-end"><Button variant="pink" onClick={() => { setCreating(false); setFresh(""); }}>I saved it</Button></div>
          </div>
        ) : (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (name.trim() && !busy) void create(); }}>
            <label className="block text-sm font-semibold">Name <span className="font-normal text-slate-400">(what will use it, for example "nightly script")</span>
              <Input className="mt-1.5" autoFocus value={name} maxLength={60} onChange={(e) => setName(e.target.value)} aria-label="API key name" />
            </label>
            <div className="flex justify-end gap-2"><Button variant="outline" onClick={() => setCreating(false)}>Cancel</Button><Button type="submit" variant="pink" disabled={!name.trim() || busy}>Create key</Button></div>
          </form>
        )}
      </Modal>
    </div>
  );
}
