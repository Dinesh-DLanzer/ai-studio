import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Bot, KeyRound, Search, ShieldCheck, Terminal } from "lucide-react";
import { api } from "../../api";
import { Card, IconTile, Input } from "../../ui";
import CodeBlock from "../../components/CodeBlock";
import { mcpSnippets } from "../../settings/Integrations";

interface Endpoint { method: string; path: string; agent: boolean; group: string; summary: string; body: string; returns: string }
interface Info { mcp: { python: string; repo: string; home: string; module: string }; tools: { name: string; description: string }[]; base_url: string }

const TONE: Record<string, string> = { GET: "bg-emerald-400/15 text-emerald-300", POST: "bg-sky/15 text-sky", PUT: "bg-amber-400/15 text-amber-300", PATCH: "bg-amber-400/15 text-amber-300", DELETE: "bg-red-400/15 text-red-300" };

const WORKFLOW = `1  create_project            name                      -> a project folder
2  update_brief / write_doc  brief fields, Story.md    -> free
3  convert_story                                       -> shots.json + images.json
4  estimate                                            -> price and stop-loss (free)
   --- a HUMAN approves the budget in the page ---
5  propose  kind=image target=ramesh                   -> exact price + proposal id (no code for agents)
   --- a HUMAN approves that price in the page ---
6  run_proposal  id                                    -> the image is made
7  repeat 5-6 for characters, backgrounds, frames, then kind=clip
8  get_costs / get_project                             -> read progress and spend`;

/** The Help page's API tab: three ways in, authentication and scope, and the full live endpoint list (read from the running server, so it cannot go out of date). */
export default function ApiReference() {
  const [eps, setEps] = useState<Endpoint[]>([]); const [groups, setGroups] = useState<string[]>([]); const [info, setInfo] = useState<Info | null>(null); const [q, setQ] = useState(""); const [err, setErr] = useState("");
  useEffect(() => {
    api<{ endpoints: Endpoint[]; groups: string[] }>("GET", "/api/docs/endpoints").then((r) => { setEps(r.endpoints); setGroups(r.groups); }).catch((e) => setErr(e.message));
    api<Info>("GET", "/api/integrations").then(setInfo).catch(() => {});
  }, []);
  const shown = useMemo(() => { const t = q.trim().toLowerCase(); return t ? eps.filter((e) => `${e.method} ${e.path} ${e.summary} ${e.group}`.toLowerCase().includes(t)) : eps; }, [eps, q]);
  const base = info?.base_url || "http://127.0.0.1:8765";
  const snip = info ? mcpSnippets(info) : null;

  return (
    <div className="space-y-4">
      <Card title={<span className="flex items-center gap-2"><IconTile tone="violet"><Bot size={15} /></IconTile> Three ways in</span>} sub="Pick the one that matches who is doing the work.">
        <div className="grid gap-3 md:grid-cols-3">
          {[
            ["The page", "For you. Everything, including every approval. Uses the session token from the start-up link."],
            ["MCP (Claude Code, OpenCode, ...)", "For an AI agent on this computer. Runs as a local process: no network, no key. It can write the story and propose work, not approve it."],
            ["HTTP API + API key", "For scripts and tools. Same limits as the MCP agent. Create keys in Settings > Integrations; revoke any time."],
          ].map(([t, d]) => <div key={t} className="panel-quiet p-3.5"><div className="text-sm font-bold">{t}</div><p className="mt-1 text-xs leading-relaxed text-slate-400">{d}</p></div>)}
        </div>
        <p className="mt-3 flex items-start gap-2 text-xs text-slate-300"><ShieldCheck size={14} className="mt-0.5 shrink-0 text-emerald-300" />The safety rule is the same everywhere: an agent or a key can propose and run what a human has already approved. Approving a budget or a price, changing providers, keys or limits, and deleting projects stay with the page.</p>
      </Card>

      <Card title={<span className="flex items-center gap-2"><IconTile tone="pink"><Terminal size={15} /></IconTile> Connect an agent with MCP</span>} sub="These commands are filled in for this install. The same snippets, with a tool list, are in Settings > Integrations.">
        {snip ? (
          <div className="space-y-3">
            <div><div className="mb-1 text-xs font-semibold">Claude Code (run once in a terminal)</div><CodeBlock code={snip.claude} label="Claude Code command" lang="bash" /></div>
            <div><div className="mb-1 text-xs font-semibold">OpenCode (opencode.json)</div><CodeBlock code={snip.opencode} label="OpenCode config" lang="json" /></div>
            <div><div className="mb-1 text-xs font-semibold">Any other MCP client</div><CodeBlock code={snip.other} label="generic MCP config" lang="json" /></div>
            <div><div className="mb-1 text-xs font-semibold">What an agent does, in order</div><CodeBlock code={WORKFLOW} label="agent workflow" /></div>
            <details className="text-xs"><summary className="cursor-pointer font-semibold text-brand">The {info?.tools.length} MCP tools</summary>
              <ul className="mt-2 grid gap-1.5 sm:grid-cols-2">{info?.tools.map((t) => <li key={t.name} className="rounded-lg border border-slate-800 bg-white/[.02] p-2"><code className="font-bold text-slate-100">{t.name}</code><div className="mt-0.5 text-slate-400">{t.description}</div></li>)}</ul></details>
          </div>
        ) : <p className="text-sm text-slate-400">Loading...</p>}
      </Card>

      <Card title={<span className="flex items-center gap-2"><IconTile tone="sky"><KeyRound size={15} /></IconTile> HTTP API basics</span>}>
        <div className="space-y-3 text-sm text-slate-300">
          <p><b>Base URL:</b> <code>{base}</code> (this computer only; other hosts are refused). Everything is JSON except uploads (raw bytes) and file downloads.</p>
          <p><b>Authentication:</b> send a key in <code>Authorization: Bearer aisk_...</code> or <code>x-aistudio-token: aisk_...</code>. The page uses its session token the same way. Endpoints that save a provider key or create an API key accept the token <i>only</i> in the header, never in a URL.</p>
          <p><b>Scope:</b> in the list below, <span className="rounded bg-emerald-400/15 px-1.5 text-emerald-300">key ok</span> means an API key may call it; <span className="rounded bg-slate-300/10 px-1.5 text-slate-300">page only</span> needs a human at the page (403 for a key).</p>
          <p><b>Errors:</b> <code>400</code> bad input or a rule refused it (the message says which), <code>401</code> missing or wrong token, <code>403</code> a key may not do that, <code>404</code> not found, <code>413</code> upload too large.</p>
          <p><b>Long jobs</b> (running an approved proposal, exporting a video) return <code>{`{"job": "<id>"}`}</code>; poll <code>GET /api/jobs/&lt;id&gt;</code> until <code>status</code> is <code>done</code> or <code>error</code>.</p>
          <div><div className="mb-1 text-xs font-semibold">Create a project, write its story, estimate, propose</div>
            <CodeBlock label="API example" lang="bash" code={`K="Authorization: Bearer aisk_YOUR_KEY"
curl -H "$K" -H 'content-type: application/json' -d '{"name":"my-ad"}' ${base}/api/projects
curl -H "$K" -X PUT -H 'content-type: application/json' -d '{"text":"# My Ad: AI VIDEO STORYBOARD ..."}' ${base}/api/projects/my-ad/docs/Story.md
curl -H "$K" -X POST ${base}/api/projects/my-ad/estimate -H 'content-type: application/json' -d '{"failure":0.2}'
# a human approves the budget in the page, then:
curl -H "$K" -H 'content-type: application/json' -d '{"kind":"image","target":"s01"}' ${base}/api/projects/my-ad/proposals
# a human approves the price in the page, then:
curl -H "$K" -X POST ${base}/api/projects/my-ad/proposals/<id>/execute   # -> {"job":"..."}; poll /api/jobs/<job>`} /></div>
          <p className="text-xs text-slate-400">Manage keys in <Link to="/settings" className="text-brand underline">Settings &gt; Integrations</Link>. A key is shown once when created and only its hash is stored.</p>
        </div>
      </Card>

      <Card title="Endpoint reference" sub={`Read live from this server: ${eps.length || "..."} routes in ${groups.length || "..."} groups.`}
        right={<div className="relative"><Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" /><Input className="!w-56 !pl-8" placeholder="Filter, e.g. proposals" aria-label="Filter endpoints" value={q} onChange={(e) => setQ(e.target.value)} /></div>}>
        {err && <p role="alert" className="text-sm text-red-300">Could not load the endpoint list: {err}</p>}
        <div className="space-y-5" data-testid="endpoint-list">
          {groups.map((g) => { const rows = shown.filter((e) => e.group === g); if (!rows.length) return null; return (
            <section key={g} aria-label={g}>
              <h3 className="mb-1.5 text-xs font-bold uppercase tracking-wider text-slate-400">{g}</h3>
              <ul className="divide-y divide-slate-800 rounded-xl border border-slate-800">
                {rows.map((e) => (
                  <li key={`${e.method} ${e.path}`} className="px-3 py-2.5 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`w-14 rounded px-1.5 py-0.5 text-center font-mono font-bold ${TONE[e.method] || ""}`}>{e.method}</span>
                      <code className="break-all font-semibold text-slate-100">{e.path}</code>
                      <span className={`ml-auto rounded px-1.5 py-0.5 text-[0.65rem] font-semibold ${e.agent ? "bg-emerald-400/15 text-emerald-300" : "bg-slate-300/10 text-slate-300"}`}>{e.agent ? "key ok" : "page only"}</span>
                    </div>
                    <p className="mt-1 text-slate-300">{e.summary}</p>
                    {(e.body !== "-" || e.returns !== "-") && <p className="mt-1 text-slate-400">{e.body !== "-" && <>Send: <code>{e.body}</code> </>}{e.returns !== "-" && <>Returns: <code>{e.returns}</code></>}</p>}
                  </li>
                ))}
              </ul>
            </section>); })}
          {eps.length > 0 && shown.length === 0 && <p className="text-sm text-slate-400">No endpoint matches that filter.</p>}
        </div>
      </Card>
    </div>
  );
}
