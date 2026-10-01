import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronRight, Search } from "lucide-react";
import { Button, Input, Label, Modal, Select } from "../ui";
import { useToast } from "../toast";
import { settingsApi } from "./client";
import type { Capability, ModelInfo, Provider } from "./types";

export default function ModelPicker({ open, onClose, capability, roleTitle, taken, onPick }: {
  open: boolean; onClose: () => void; capability: Capability; roleTitle: string;
  /** "provider\u0000model" keys already in the chain. */
  taken: Set<string>; onPick: (m: ModelInfo) => void;
}) {
  const toast = useToast();
  const [models, setModels] = useState<ModelInfo[]>([]); const [errors, setErrors] = useState<Record<string, string>>({});
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(false); const [loadErr, setLoadErr] = useState("");
  const [q, setQ] = useState("");
  const [adv, setAdv] = useState(false); const [prov, setProv] = useState(""); const [mid, setMid] = useState(""); const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setLoadErr("");
    try {
      const [m, p] = await Promise.all([settingsApi.models(capability), settingsApi.providers()]);
      setModels(m.models); setErrors(m.errors || {});
      const usable = p.providers.filter((x) => x.enabled && x.capabilities.includes(capability));
      setProviders(usable); setProv((cur) => cur || usable[0]?.id || "");
    } catch (e) { setLoadErr((e as Error).message); }
    finally { setLoading(false); }
  }, [capability]);

  useEffect(() => { if (open) { setQ(""); setAdv(false); setMid(""); void load(); } }, [open, load]);

  const groups = useMemo(() => {
    const t = q.trim().toLowerCase();
    const g = new Map<string, { label: string; items: ModelInfo[] }>();
    for (const m of models) {
      if (t && !`${m.id} ${m.name} ${m.provider_label}`.toLowerCase().includes(t)) continue;
      if (!g.has(m.provider)) g.set(m.provider, { label: m.provider_label, items: [] });
      g.get(m.provider)!.items.push(m);
    }
    return [...g.entries()];
  }, [models, q]);

  const addById = async () => {
    if (!prov || !mid.trim()) return;
    setAdding(true);
    const id = mid.trim();
    if (taken.has(`${prov}\u0000${id}`)) { toast("error", `${id} is already in the chain`); return; }
    try {
      // save it in the provider's model list (so it is offered again later), then put it straight into the chain
      const r = await settingsApi.addModel(prov, id, capability);
      const label = providers.find((x) => x.id === prov);
      const info: ModelInfo = r.models?.find((m) => m.provider === prov && m.id === id) || {
        provider: prov, provider_label: label?.label || prov, ptype: label?.type || "", id, name: id, capability, price: null, priced: false, free: false, card: null, suggest: null, custom: true };
      setMid(""); onPick(info);
    }
    catch (e) { toast("error", `Could not add model: ${(e as Error).message}`); }
    finally { setAdding(false); }
  };

  return (
    <Modal open={open} onClose={onClose} title={`Add a model for ${roleTitle}`}>
      <div className="space-y-4">
        <div className="relative">
          <Search size={15} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <Input aria-label="Search models" placeholder="Search models or providers" className="!pl-9" autoFocus value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {Object.entries(errors).map(([id, msg]) => (
          <p key={id} className="tag tag-amber !h-auto !whitespace-normal" role="note">Could not list {models.find((m) => m.provider === id)?.provider_label || id} models: {msg}</p>
        ))}
        <div className="max-h-[50vh] space-y-3 overflow-auto pr-1" aria-busy={loading}>
          {loading && <div className="space-y-2" aria-label="Loading models">{[0, 1, 2].map((i) => <div key={i} className="h-11 animate-pulse rounded-xl bg-white/5" />)}</div>}
          {loadErr && <div role="alert" className="text-sm text-red-300">Could not load models: {loadErr} <Button variant="outline" size="sm" onClick={() => void load()}>Retry</Button></div>}
          {!loading && !loadErr && groups.length === 0 && <p className="text-sm text-slate-400">{models.length ? "No models match your search." : "No models available. Connect a provider, or add one by id below."}</p>}
          {!loading && groups.map(([pid, g]) => (
            <section key={pid} aria-label={g.label}>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">{g.label}</h4>
              <ul className="space-y-1">
                {g.items.map((m) => {
                  const used = taken.has(`${m.provider}\u0000${m.id}`);
                  return (
                    <li key={m.id}>
                      <button type="button" disabled={used} onClick={() => onPick(m)} aria-label={used ? `${m.id} is already in the chain` : `Add ${m.id}`}
                        className="panel-quiet flex w-full items-center justify-between gap-3 px-3 py-2 text-left transition hover:border-pink/40 disabled:cursor-not-allowed disabled:opacity-50">
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold text-slate-100">{m.name || m.id}</span>
                          <span className="block truncate font-mono text-xs text-slate-400">{m.provider_label} <span aria-hidden className="mx-0.5 text-slate-500">&bull;</span> {m.id}</span>
                        </span>
                        <span className="flex shrink-0 items-center gap-1.5">
                          {used && <span className="tag">In chain</span>}
                          {m.free ? <span className="tag tag-emerald">free</span> : m.priced && m.price ? <span className="tag">{m.price}</span> : <span className="tag tag-amber">price unknown</span>}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
        <div className="border-t border-slate-800 pt-3">
          <button type="button" aria-expanded={adv} onClick={() => setAdv((v) => !v)} className="flex items-center gap-1 text-sm text-slate-300 hover:text-white">
            <ChevronRight size={14} aria-hidden className={`transition ${adv ? "rotate-90" : ""}`} /> Model not listed? Add by id
          </button>
          {adv && (
            <form className="mt-3 grid gap-3 sm:grid-cols-[1fr_2fr_auto] sm:items-end" onSubmit={(e) => { e.preventDefault(); void addById(); }}>
              <div><Label>Provider</Label>
                <Select aria-label="Provider" value={prov} onChange={(e) => setProv(e.target.value)}>
                  {providers.length === 0 && <option value="">No provider</option>}
                  {providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                </Select></div>
              <div><Label>Model id</Label><Input aria-label="Model id" className="font-mono" placeholder="e.g. vendor/model-name" value={mid} onChange={(e) => setMid(e.target.value)} /></div>
              <Button variant="primary" type="submit" disabled={adding || !prov || !mid.trim()}>Add</Button>
            </form>
          )}
        </div>
      </div>
    </Modal>
  );
}
