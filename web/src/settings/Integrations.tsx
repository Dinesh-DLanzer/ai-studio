import { useCallback, useEffect, useState } from "react";
import { KeyRound, Plug, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { api } from "../api";
import { Button, Card, IconTile, Input, Modal } from "../ui";
import { useToast } from "../toast";
import { confirmDialog } from "../dialogs";
import CodeBlock from "../components/CodeBlock";

interface Info { mcp: { python: string; repo: string; home: string; module: string }; tools: { name: string; description: string }[]; base_url: string }
interface Key { id: string; name: string; prefix: string; created: string; last_used: string | null }
type Client = "claude" | "opencode" | "other";

const sh = (s: string) => (/^[\w@%+=:,./-]+$/.test(s) ? s : `'${s.replace(/'/g, `'\\''`)}'`);

/** Snippets that connect an AI agent (Claude Code, OpenCode, any MCP client) to this install. The MCP server runs on this computer and can only propose, never approve. */
export function mcpSnippets(i: Info) {
  const env = { PYTHONPATH: i.mcp.repo, AISTUDIO_HOME: i.mcp.home };
  return {
    claude: `claude mcp add ai-studio -e PYTHONPATH=${sh(env.PYTHONPATH)} -e AISTUDIO_HOME=${sh(env.AISTUDIO_HOME)} -- ${sh(i.mcp.python)} -m ${i.mcp.module}`,
    opencode: JSON.stringify({ $schema: "https://opencode.ai/config.json", mcp: { "ai-studio": { type: "local", command: [i.mcp.python, "-m", i.mcp.module], enabled: true, environment: env } } }, null, 2),
    other: JSON.stringify({ mcpServers: { "ai-studio": { command: i.mcp.python, args: ["-m", i.mcp.module], env } } }, null, 2),
  };
}

export default function IntegrationsSection() {
  const toast = useToast();
  const [info, setInfo] = useState<Info | null>(null); const [keys, setKeys] = useState<Key[]>([]); const [client, setClient] = useState<Client>("claude");
  const [creating, setCreating] = useState(false); const [name, setName] = useState(""); const [busy, setBusy] = useState(false); const [fresh, setFresh] = useState<string>("");
  const [showTools, setShowTools] = useState(false);
  const load = useCallback(async () => {
    try { setInfo(await api<Info>("GET", "/api/integrations")); setKeys((await api<{ keys: Key[] }>("GET", "/api/keys")).keys); }
    catch (e: any) { toast("error", e.message); }
  }, [toast]);
  useEffect(() => { void load(); }, [load]);

  const create = async () => {
    setBusy(true);
    try { const r = await api<{ key: string }>("POST", "/api/keys", { name: name.trim() }); setFresh(r.key); setName(""); await load(); }
    catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  const revoke = async (k: Key) => {
    if (!(await confirmDialog(`Revoke the key "${k.name}" (${k.prefix}...)? Anything using it stops working at once.`, { title: "Revoke API key", ok: "Revoke", danger: true }))) return;
    try { await api("DELETE", `/api/keys/${k.id}`); toast("ok", "Key revoked."); await load(); } catch (e: any) { toast("error", e.message); }
  };
  const snip = info ? mcpSnippets(info) : null;
  const TABS: [Client, string][] = [["claude", "Claude Code"], ["opencode", "OpenCode"], ["other", "Other MCP client"]];

  return (
    <div className="space-y-5">
      <Card title={<span className="flex items-center gap-2"><IconTile tone="violet"><Plug size={15} /></IconTile> Connect an AI agent (MCP)</span>}
        sub="Let Claude Code, OpenCode or any MCP client write your story and propose generations. It runs on this computer; no key is needed.">
        {!info || !snip ? <p className="text-sm text-slate-400">Loading...</p> : (
          <>
            <div role="tablist" aria-label="MCP client" className="mb-3 flex flex-wrap gap-2">
              {TABS.map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={client === id} onClick={() => setClient(id)} className={`pill !px-3 !py-1.5 text-xs ${client === id ? "" : "!bg-slate-900"}`}>{label}</button>)}
            </div>
            {client === "claude" && <p className="mb-2 text-xs text-slate-400">Run this once in a terminal. Check it with <code className="text-slate-200">claude mcp list</code>.</p>}
            {client === "opencode" && <p className="mb-2 text-xs text-slate-400">Save as <code className="text-slate-200">opencode.json</code> in your project folder (or merge the "mcp" part into your OpenCode config).</p>}
            {client === "other" && <p className="mb-2 text-xs text-slate-400">Paste into the MCP server list of your client (Claude Desktop, Cursor and others use this shape).</p>}
            <CodeBlock code={snip[client]} label={`${client} MCP setup`} lang={client === "claude" ? "bash" : "json"} />
            <p className="mt-3 flex items-start gap-2 text-xs text-slate-400"><ShieldCheck size={14} className="mt-0.5 shrink-0 text-emerald-300" />The agent can read and write the story, estimate and propose. It cannot approve a budget or a price, change providers or keys, or delete projects: you approve in this page.</p>
            <button type="button" className="mt-3 text-xs font-semibold text-brand underline-offset-2 hover:underline" onClick={() => setShowTools((v) => !v)} aria-expanded={showTools}>{showTools ? "Hide" : "Show"} the {info.tools.length} tools the agent gets</button>
            {showTools && <ul className="mt-2 grid gap-1.5 text-xs sm:grid-cols-2" data-testid="mcp-tools">{info.tools.map((t) => <li key={t.name} className="rounded-lg border border-slate-800 bg-white/[.02] p-2"><code className="font-bold text-slate-100">{t.name}</code><div className="mt-0.5 text-slate-400">{t.description}</div></li>)}</ul>}
          </>
        )}
      </Card>

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
