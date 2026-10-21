import { useCallback, useEffect, useState } from "react";
import { Users } from "lucide-react";
import { Badge, Button, Card, Field, IconTile, Input } from "../ui";
import { useToast } from "../toast";
import { confirmDialog } from "../dialogs";
import { crewApi } from "../hooks/useCrew";
import type { CrewAgent, CrewAgents, CrewLimits } from "../types/crew";

const LIMITS: { key: keyof CrewLimits; label: string; step: number }[] = [
  { key: "max_steps", label: "Max steps", step: 1 }, { key: "max_tokens", label: "Max tokens", step: 1000 }, { key: "max_llm_usd", label: "Max AI text cost (USD)", step: 0.05 },
];

function AgentEditor({ a, hard, reload }: { a: CrewAgent; hard: CrewLimits; reload: () => void }) {
  const toast = useToast();
  const [prompt, setPrompt] = useState(a.prompt);
  const [lim, setLim] = useState<CrewLimits>(a.limits);
  useEffect(() => { setPrompt(a.prompt); setLim(a.limits); }, [a]);
  const save = async () => {
    try { await crewApi.putAgent(a.id, { prompt, limits: lim }); toast("ok", `${a.name} saved.`); reload(); } catch (e: any) { toast("error", e.message); }
  };
  const reset = async () => {
    if (!(await confirmDialog(`Reset ${a.name} to its default prompt and limits?`, { title: "Reset to default?", ok: "Reset" }))) return;
    try { await crewApi.putAgent(a.id, {}); toast("ok", `${a.name} is back to its defaults.`); reload(); } catch (e: any) { toast("error", e.message); }
  };
  return (
    <details className="rounded-xl border border-slate-800 p-3" data-testid={`crew-agent-${a.id}`}>
      <summary className="flex cursor-pointer flex-wrap items-center gap-2">
        <b>{a.name}</b><code className="text-xs text-slate-400">@{a.id}</code>
        <span className="text-xs text-slate-400">{a.role}</span>
        {a.overridden.length > 0 && <Badge tone="amber">customised: {a.overridden.join(" and ")}</Badge>}
      </summary>
      <div className="mt-3 space-y-3 text-sm">
        <label className="block"><span className="mb-1 block font-semibold">Prompt</span>
          <Field rows={8} value={prompt} onChange={(e) => setPrompt(e.target.value)} aria-label={`${a.name} prompt`} />
        </label>
        <div className="flex flex-wrap gap-4">
          {LIMITS.map((l) => (
            <label key={l.key} className="block"><span className="mb-1 block text-xs font-semibold">{l.label} (hard limit {hard[l.key]})</span>
              <Input type="number" className="!w-36" min={l.step} max={hard[l.key]} step={l.step} value={lim[l.key]} onChange={(e) => setLim({ ...lim, [l.key]: Number(e.target.value) })} aria-label={`${a.name} ${l.label}`} />
            </label>
          ))}
        </div>
        <div>
          <div className="mb-1 text-xs font-semibold">Tools (read-only)</div>
          <ul className="flex flex-wrap gap-1.5" aria-label={`${a.name} tools`}>{a.tools.map((t) => <li key={t}><Badge>{t}</Badge></li>)}</ul>
          <p className="mt-1 text-xs text-slate-400">Tools can never be changed here. Approving, running paid work and deleting are human-only for every agent.</p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="pink" onClick={save}>Save</Button>
          <Button size="sm" variant="outline" onClick={reset} disabled={a.overridden.length === 0} aria-label={`Reset ${a.name} to default`}>Reset to default</Button>
        </div>
      </div>
    </details>
  );
}

/** Settings > Agents: the crew's prompts and limits (tools are shown, never editable). */
export default function CrewAgentsSection() {
  const toast = useToast();
  const [d, setD] = useState<CrewAgents | null>(null);
  const load = useCallback(() => crewApi.agents().then(setD).catch((e) => toast("error", e.message)), [toast]);
  useEffect(() => { void load(); }, [load]);
  return (
    <Card title={<span className="flex items-center gap-2"><IconTile tone="violet"><Users size={15} /></IconTile> Agents</span>}
      sub="The in-app crew. You can edit an agent's prompt and limits. Tools can never be changed, and no agent can approve or spend anything.">
      {!d ? <p className="text-sm text-slate-400">Loading...</p> : (
        <div className="space-y-2">
          <p className="text-xs text-slate-400">Hard limits: {d.hard_limits.max_steps} steps, {d.hard_limits.max_tokens} tokens, ${d.hard_limits.max_llm_usd} AI text cost per run.</p>
          {d.agents.map((a) => <AgentEditor key={a.id} a={a} hard={d.hard_limits} reload={load} />)}
        </div>
      )}
    </Card>
  );
}
