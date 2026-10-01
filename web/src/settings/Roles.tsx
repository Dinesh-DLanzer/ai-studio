import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, ChevronRight, Eye, Image as ImageIcon, MessageSquare, RotateCcw, ShieldCheck, SlidersHorizontal, Video, XCircle, type LucideIcon } from "lucide-react";
import { Button, Card, IconTile, Input, Label, type TileTone } from "../ui";
import { useToast } from "../toast";
import { confirmDialog } from "../dialogs";
import { settingsApi } from "./client";
import ChainEditor from "./ChainEditor";
import ModelPicker from "./ModelPicker";
import PriceDialog, { type PriceTarget } from "./PriceDialog";
import type { ChainEntry, ChainRef, ModelInfo, Role, RoleView, RolesResponse, TestRow } from "./types";

const ORDER: Role[] = ["chat", "vision", "image", "video", "verify"];
const LOOK: Record<Role, { icon: LucideIcon; tone: TileTone }> = {
  chat: { icon: MessageSquare, tone: "pink" }, vision: { icon: Eye, tone: "violet" }, image: { icon: ImageIcon, tone: "emerald" },
  video: { icon: Video, tone: "amber" }, verify: { icon: ShieldCheck, tone: "sky" },
};
const refs = (c: ChainEntry[]): ChainRef[] => c.map((e) => ({ provider: e.provider, model: e.model }));
const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Math.round(n)));

function RoleCard({ role, view, project, hasProviders, busy, onSave, onAnnounce, onReload }: {
  role: Role; view: RoleView; project?: string; hasProviders: boolean; busy: boolean;
  onSave: (chain: ChainRef[], policy?: { retries?: number; timeout?: number }) => void; onAnnounce: (s: string) => void; onReload: () => void;
}) {
  const toast = useToast();
  const { icon: Icon, tone } = LOOK[role];
  const [pick, setPick] = useState(false); const [price, setPrice] = useState<PriceTarget | null>(null);
  const [adv, setAdv] = useState(false);
  const [retries, setRetries] = useState(String(view.policy.retries)); const [timeout, setTimeoutS] = useState(String(view.policy.timeout));
  const [tests, setTests] = useState<TestRow[] | null>(null); const [testing, setTesting] = useState(false);
  useEffect(() => { setRetries(String(view.policy.retries)); setTimeoutS(String(view.policy.timeout)); }, [view.policy.retries, view.policy.timeout]);
  useEffect(() => { setTests(null); }, [view.chain.length]);

  const chain = view.chain;
  const reorder = (from: number, to: number) => {
    if (to < 0 || to >= chain.length || from === to) return;
    const next = [...chain]; const [m] = next.splice(from, 1); next.splice(to, 0, m);
    onAnnounce(`${m.model} moved to position ${to + 1} of ${next.length} in the ${view.title} chain`);
    onSave(refs(next));
  };
  const remove = (i: number) => { onAnnounce(`${chain[i].model} removed from the ${view.title} chain`); onSave(refs(chain.filter((_, j) => j !== i))); };
  const add = (m: ModelInfo) => { setPick(false); onAnnounce(`${m.id} added to the ${view.title} chain`); onSave([...refs(chain), { provider: m.provider, model: m.id }]); };
  const savePolicy = () => {
    const r = clamp(Number(retries), 0, 5), t = clamp(Number(timeout), 5, 1800);
    const rr = Number.isFinite(r) ? r : view.policy.retries, tt = Number.isFinite(t) ? t : view.policy.timeout;
    setRetries(String(rr)); setTimeoutS(String(tt));
    if (rr !== view.policy.retries || tt !== view.policy.timeout) onSave(refs(chain), { retries: rr, timeout: tt });
  };
  const runTest = async () => {
    setTesting(true); setTests(null);
    try { setTests((await settingsApi.testRole(role, project)).results); }
    catch (e) { toast("error", `Test failed: ${(e as Error).message}`); }
    finally { setTesting(false); }
  };

  return (
    <Card className="flex flex-col" bodyClass="space-y-3">
      <div className="flex items-start gap-3">
        <IconTile tone={tone} size="lg"><Icon size={20} aria-hidden /></IconTile>
        <div className="min-w-0 flex-1">
          <h4 className="font-bold text-slate-100">{view.title}</h4>
          <p className="text-xs text-slate-400">{view.sub}</p>
        </div>
        {view.overridden && <span className="tag tag-violet shrink-0">This project</span>}
      </div>
      {project && view.overridden && (
        <button type="button" className="text-xs text-pink underline underline-offset-2 hover:text-white" disabled={busy}
          onClick={() => onSave([], undefined)}>Use workspace default</button>
      )}
      <ChainEditor role={role} chain={chain} hasProviders={hasProviders} disabled={busy} onReorder={reorder} onRemove={remove}
        onAdd={() => setPick(true)} onSetPrice={(e) => setPrice({ provider: e.provider, provider_label: e.provider_label, model: e.model, capability: view.capability })} />
      <div className="flex flex-wrap items-center gap-2 border-t border-slate-800 pt-3">
        <Button variant="outline" size="sm" onClick={() => void runTest()} disabled={testing || chain.length === 0}>{testing ? "Testing..." : "Test chain"}</Button>
        <button type="button" aria-expanded={adv} onClick={() => setAdv((v) => !v)} className="ml-auto flex items-center gap-1 text-xs text-slate-300 hover:text-white">
          <ChevronRight size={13} aria-hidden className={`transition ${adv ? "rotate-90" : ""}`} /> Advanced
        </button>
      </div>
      {tests && (
        <ul className="space-y-1 text-xs" aria-label={`${view.title} test results`}>
          {tests.map((t) => (
            <li key={`${t.provider}${t.model}`} className={`flex items-start gap-1.5 ${t.ok ? "text-emerald-300" : "text-red-300"}`}>
              {t.ok ? <CheckCircle2 size={13} aria-hidden className="mt-0.5 shrink-0" /> : <XCircle size={13} aria-hidden className="mt-0.5 shrink-0" />}
              <span><span className="font-mono">{t.model}</span>: {t.ok ? "OK" : "Failed"}{t.message ? `. ${t.message}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
      {adv && (
        <div className="grid grid-cols-2 gap-3">
          <div><Label>Retries per model</Label>
            <Input aria-label={`Retries per model for ${view.title}`} type="number" min={0} max={5} value={retries} onChange={(e) => setRetries(e.target.value)} onBlur={savePolicy} /></div>
          <div><Label>Timeout seconds</Label>
            <Input aria-label={`Timeout seconds for ${view.title}`} type="number" min={5} max={1800} value={timeout} onChange={(e) => setTimeoutS(e.target.value)} onBlur={savePolicy} /></div>
        </div>
      )}
      <ModelPicker open={pick} onClose={() => setPick(false)} capability={role === "verify" ? "chat" : view.capability} roleTitle={view.title}
        taken={new Set(chain.map((e) => `${e.provider}\u0000${e.model}`))} onPick={add} />
      <PriceDialog target={price} onClose={() => setPrice(null)} onSaved={onReload} />
    </Card>
  );
}

export default function RolesSection({ reloadKey, project, onChanged }: { reloadKey: number; project?: string; onChanged?: () => void }) {
  const toast = useToast();
  const [data, setData] = useState<RolesResponse | null>(null); const [err, setErr] = useState("");
  const [hasProviders, setHasProviders] = useState(true);
  const [busy, setBusy] = useState(false); const [live, setLive] = useState("");
  const seq = useRef(0);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setErr("");
    const my = ++seq.current;
    try {
      const [r, p] = await Promise.all([settingsApi.roles(project), settingsApi.providers().catch(() => null)]);
      if (my !== seq.current) return;
      setData(r); if (p) setHasProviders(p.providers.length > 0);
    } catch (e) { if (my === seq.current) { if (quiet) toast("error", (e as Error).message); else setErr((e as Error).message); } }
  }, [project, toast]);

  useEffect(() => { setData(null); void load(); }, [load, reloadKey]);

  const save = async (role: Role, chain: ChainRef[], policy?: { retries?: number; timeout?: number }) => {
    if (!data) return;
    const before = data; const my = ++seq.current;
    const byKey = new Map(before.roles[role].chain.map((e) => [`${e.provider}\u0000${e.model}`, e]));
    const optimistic: ChainEntry[] = chain.flatMap((c) => { const e = byKey.get(`${c.provider}\u0000${c.model}`); return e ? [e] : []; });
    // Newly added entries have no row data yet; keep the old chain on screen until the server answers, unless it only shrank/reordered.
    if (optimistic.length === chain.length && (chain.length > 0 || !project)) {
      setData({ ...before, roles: { ...before.roles, [role]: { ...before.roles[role], chain: optimistic, policy: { ...before.roles[role].policy, ...policy } } } });
    }
    setBusy(true);
    try {
      const r = await settingsApi.putRole(role, chain, policy, project);
      if (my === seq.current) setData(r); else void load(true);
      onChanged?.();
    } catch (e) {
      if (my === seq.current) setData(before);
      toast("error", `Could not save the ${before.roles[role].title} chain: ${(e as Error).message}`);
    } finally { setBusy(false); }
  };

  const reset = async () => {
    if (!(await confirmDialog("Reset every chain to the defaults from your connected providers?", { title: "Reset to default", ok: "Reset" }))) return;
    setBusy(true);
    try { setData(await settingsApi.resetRoles()); toast("ok", "Model chains reset to defaults"); onChanged?.(); }
    catch (e) { toast("error", `Could not reset: ${(e as Error).message}`); }
    finally { setBusy(false); }
  };

  return (
    <section aria-labelledby="model-config-title" id="set-models" className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <IconTile tone="muted" size="lg"><SlidersHorizontal size={20} aria-hidden /></IconTile>
          <div className="min-w-0">
            <h2 id="model-config-title" className="text-xl font-bold text-slate-100">Model Configuration</h2>
            <p className="mt-0.5 max-w-2xl text-sm text-slate-400">Set default models for each process. Each process tries its models in order: if one fails, the next one is used.</p>
          </div>
        </div>
        {!project && <Button variant="outline" size="sm" onClick={() => void reset()} disabled={busy || !data}><RotateCcw size={14} aria-hidden /> Reset to default</Button>}
      </div>
      <div className="sr-only" aria-live="polite" role="status">{live}</div>
      {err ? (
        <div role="alert" className="panel-quiet flex flex-wrap items-center gap-3 p-4 text-sm text-red-300">
          <span>Could not load model settings: {err}</span><Button variant="outline" size="sm" onClick={() => void load()}>Retry</Button>
        </div>
      ) : !data ? (
        <div className="grid gap-4 md:grid-cols-2" aria-busy="true" aria-label="Loading model settings">
          {ORDER.map((r) => <div key={r} className="panel h-56 animate-pulse" />)}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {ORDER.filter((r) => data.roles[r]).map((r) => (
            <RoleCard key={r} role={r} view={data.roles[r]} project={project} hasProviders={hasProviders} busy={busy}
              onSave={(c, p) => void save(r, c, p)} onAnnounce={setLive} onReload={() => void load(true)} />
          ))}
        </div>
      )}
    </section>
  );
}
