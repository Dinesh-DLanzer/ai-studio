import { useCallback, useEffect, useState } from "react";
import * as Menu from "@radix-ui/react-dropdown-menu";
import { AlertCircle, AlertTriangle, CheckCircle2, Eye, KeyRound, Loader2, MoreVertical, Pencil, Plus, Power, Trash2 } from "lucide-react";
import { Button, Card, IconTile, Input, Modal } from "../ui";
import { useToast } from "../toast";
import { confirmDialog } from "../dialogs";
import { settingsApi } from "./client";
import { AddProviderDialog, fieldLabel } from "./AddProvider";
import type { Capability, Provider, ProviderType, ProvidersResponse } from "./types";

const TINTS: Record<string, string> = {
  openrouter: "border-violet-400/40 bg-violet-400/15 text-violet-200",
  openai: "border-emerald-400/40 bg-emerald-400/15 text-emerald-300",
  anthropic: "border-amber-400/40 bg-amber-400/15 text-amber-300",
  google: "border-sky-400/40 bg-sky-400/15 text-sky-300",
  runway: "border-pink-400/40 bg-pink-400/15 text-pink-300",
  kling: "border-lime-300/40 bg-lime-300/15 text-lime-200",
  replicate: "border-slate-400/40 bg-slate-400/15 text-slate-200",
  custom: "border-sky-400/40 bg-sky-400/15 text-sky-300",
  fake: "border-slate-400/40 bg-slate-400/15 text-slate-200",
};
const MARKS: Record<string, string> = { openrouter: "OR", openai: "AI", anthropic: "A\\", google: "G", runway: "R", kling: "K", replicate: "Rp", custom: "{}", fake: "F" };
const CAPS: [Capability, string][] = [["chat", "Chat"], ["vision", "Vision"], ["image", "Image"], ["video", "Video"]];

function Logo({ p }: { p: Provider }) {
  return <span aria-hidden className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl border text-sm font-extrabold tracking-tight ${TINTS[p.type] || TINTS.custom}`}>{MARKS[p.type] || p.label.slice(0, 2).toUpperCase()}</span>;
}

function StatusBadge({ p }: { p: Provider }) {
  const s = p.status.state;
  if (!p.enabled && s !== "needs_key") return <span className="tag">Inactive</span>;
  if (s === "active") return <span className="tag tag-emerald">Active</span>;
  if (s === "needs_key") return <span className="tag tag-amber">Needs key</span>;
  if (s === "error") return <span className="tag tag-red">Error</span>;
  return <span className="tag">Inactive</span>;
}

function StatusLine({ p }: { p: Provider }) {
  const { state, message, checked_at } = p.status;
  if (state === "active") {
    const when = checked_at ? ` · checked ${new Date(checked_at * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}` : "";
    return <p className="flex items-center gap-1.5 text-xs text-emerald-300"><CheckCircle2 size={14} className="shrink-0" /><span>{checked_at ? "Connected successfully" : message || "Connected"}{when}</span></p>;
  }
  if (state === "error") return <p className="flex items-start gap-1.5 text-xs text-red-300"><AlertCircle size={14} className="mt-px shrink-0" /><span>{message || "Connection failed"}</span></p>;
  if (state === "needs_key") return <p className="flex items-center gap-1.5 text-xs text-amber-300"><AlertTriangle size={14} className="shrink-0" /><span>{message || "Add an API key to connect"}</span></p>;
  return message ? <p className="text-xs text-slate-400">{message}</p> : null;
}

function ProviderCard({ p, busy, run, reload }: { p: Provider; busy: boolean; run: (id: string, fn: () => Promise<string | void>) => Promise<void>; reload: () => Promise<void> }) {
  const toast = useToast();
  const [editing, setEditing] = useState(!p.secret.set && p.fields.length > 0);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [edit, setEdit] = useState(false);
  const [label, setLabel] = useState(p.label); const [url, setUrl] = useState(p.base_url || "");
  const isFake = p.type === "fake";
  const hasSecret = p.secret.set;
  useEffect(() => { if (hasSecret) { setEditing(false); setVals({}); } }, [hasSecret]);
  const ready = p.fields.every((f) => (vals[f] || "").trim() !== "");
  const optionalKey = p.type === "custom";

  const saveKey = (testAfter: boolean) => run(p.id, async () => {
    const fields: Record<string, string> = {};
    for (const f of p.fields) if ((vals[f] || "").trim()) fields[f] = vals[f].trim();
    await settingsApi.putSecret(p.id, fields);
    setVals({}); setEditing(false);
    if (!testAfter) return "Key saved";
    const t = await settingsApi.testProvider(p.id);
    if (!t.result.ok) throw new Error(`Key saved, but the test failed: ${t.result.message}`);
    return `${p.label}: ${t.result.message || "Connected successfully"}`;
  });
  const test = () => run(p.id, async () => {
    const t = await settingsApi.testProvider(p.id);
    if (!t.result.ok) throw new Error(`${p.label}: ${t.result.message}`);
    return `${p.label}: ${t.result.message || "Connected successfully"}`;
  });
  const toggle = () => run(p.id, async () => { await settingsApi.updateProvider(p.id, { enabled: !p.enabled }); return p.enabled ? `${p.label} disabled` : `${p.label} enabled`; });
  const saveEdit = () => run(p.id, async () => {
    await settingsApi.updateProvider(p.id, { label: label.trim() || p.label, ...(p.type === "custom" || p.base_url ? { base_url: url.trim() } : {}) });
    setEdit(false); return "Saved";
  });
  const remove = async () => {
    if (!(await confirmDialog(`Remove ${p.label}? Its saved key will be deleted.`, { title: "Remove provider", ok: "Remove", danger: true }))) return;
    try {
      await settingsApi.deleteProvider(p.id, false);
      toast("ok", `${p.label} removed`); await reload();
    } catch (e) {
      if (!(await confirmDialog(`${(e as Error).message}\n\nRemoving it will also take it out of those roles.`, { title: "Provider is in use", ok: "Remove anyway", danger: true }))) return;
      await run(p.id, async () => { await settingsApi.deleteProvider(p.id, true); return `${p.label} removed`; });
    }
  };

  return (
    <div className="panel-quiet flex flex-col gap-3 rounded-2xl p-3.5" data-testid={`provider-${p.id}`}>
      <div className="flex items-start gap-3">
        <Logo p={p} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><span className="truncate text-sm font-bold text-slate-100">{p.label}</span><StatusBadge p={p} /></div>
          <p className="mt-0.5 text-xs text-slate-400">{p.sub}</p>
        </div>
        {!isFake && (
          <Menu.Root>
            <Menu.Trigger aria-label={`More for ${p.label}`} className="icon-btn !h-8 !w-8 !border-0 !bg-transparent"><MoreVertical size={16} /></Menu.Trigger>
            <Menu.Portal>
              <Menu.Content align="end" sideOffset={6} className="menu-surface">
                <Menu.Item className="menu-item" onSelect={toggle}><Power size={14} />{p.enabled ? "Disable" : "Enable"}</Menu.Item>
                <Menu.Item className="menu-item" onSelect={() => { setLabel(p.label); setUrl(p.base_url || ""); setEdit(true); }}><Pencil size={14} />Edit name &amp; URL</Menu.Item>
                <Menu.Item className="menu-item" onSelect={remove}><Trash2 size={14} />Remove</Menu.Item>
              </Menu.Content>
            </Menu.Portal>
          </Menu.Root>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {CAPS.filter(([c]) => p.capabilities.includes(c)).map(([c, l]) => <span key={c} className="tag">{l}</span>)}
        {p.used_in.length > 0 && <span className="text-xs text-slate-400">Used in: {p.used_in.join(", ")}</span>}
      </div>

      {!isFake && p.fields.length > 0 && (
        <div className="space-y-2">
          {!editing && hasSecret ? (
            <>
              {p.fields.map((f) => (
                <div key={f} className="flex items-center gap-2">
                  <span className="w-20 shrink-0 text-xs text-slate-400">{fieldLabel(f)}</span>
                  <Input disabled readOnly aria-label={`${p.label} ${fieldLabel(f)} (saved)`} value={`••••••••••••${p.secret.fields[f] || ""}`} className="min-w-0 flex-1" />
                  <button type="button" disabled title="Saved keys cannot be shown" aria-label={`Show ${fieldLabel(f)} (not available)`} className="icon-btn !h-8 !w-8 disabled:opacity-40"><Eye size={15} /></button>
                </div>
              ))}
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <button type="button" onClick={() => setEditing(true)} className="inline-flex items-center gap-1 font-semibold text-violet-300 underline-offset-2 hover:underline"><KeyRound size={12} />Replace key</button>
              </div>
            </>
          ) : (
            <>
              {p.fields.map((f) => (
                <div key={f} className="flex items-center gap-2">
                  <label htmlFor={`${p.id}-${f}`} className="w-20 shrink-0 text-xs text-slate-400">{fieldLabel(f)}</label>
                  <Input id={`${p.id}-${f}`} type="password" autoComplete="off" className="min-w-0 flex-1" placeholder={`Enter your ${fieldLabel(f).toLowerCase()}`}
                    value={vals[f] || ""} onChange={(e) => setVals({ ...vals, [f]: e.target.value })} />
                </div>
              ))}
              <div className="flex justify-end gap-2">
                {hasSecret && <Button variant="outline" size="sm" onClick={() => { setEditing(false); setVals({}); }} disabled={busy}>Cancel</Button>}
                <Button variant={hasSecret ? "outline" : "pink"} size="sm" disabled={busy || (!ready && !optionalKey) || (optionalKey && Object.values(vals).every((v) => !v.trim()))}
                  aria-label={hasSecret ? `Save key for ${p.label}` : `Connect ${p.label}`} onClick={() => saveKey(!hasSecret)}>
                  {busy && <Loader2 size={13} className="animate-spin" />}{hasSecret ? "Save" : "Connect"}
                </Button>
              </div>
            </>
          )}
        </div>
      )}

      <div className="mt-auto flex items-end justify-between gap-2">
        <div className="min-w-0 flex-1"><StatusLine p={p} /></div>
        {(hasSecret || isFake || p.fields.length === 0) && (
          <Button variant="outline" size="sm" onClick={test} disabled={busy} aria-label={`Test ${p.label}`}>
            {busy && <Loader2 size={13} className="animate-spin" />}Test
          </Button>
        )}
      </div>

      <Modal open={edit} onClose={() => setEdit(false)} title={`Edit ${p.label}`}>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); saveEdit(); }}>
          <label className="block"><span className="mb-1.5 block text-xs font-semibold text-slate-300">Name</span><Input value={label} onChange={(e) => setLabel(e.target.value)} required /></label>
          {(p.type === "custom" || p.base_url) && (
            <label className="block"><span className="mb-1.5 block text-xs font-semibold text-slate-300">Base URL</span><Input value={url} onChange={(e) => setUrl(e.target.value)} inputMode="url" /></label>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" onClick={() => setEdit(false)}>Cancel</Button>
            <Button variant="pink" type="submit" disabled={busy || !label.trim()}>Save</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

export default function ProvidersSection({ onChanged }: { onChanged: () => void }) {
  const toast = useToast();
  const [data, setData] = useState<ProvidersResponse | null>(null);
  const [types, setTypes] = useState<ProviderType[]>([]);
  const [err, setErr] = useState("");
  const [adding, setAdding] = useState(false);
  const [busyIds, setBusyIds] = useState<Record<string, boolean>>({});

  const reload = useCallback(async () => {
    try { setData(await settingsApi.providers()); setErr(""); } catch (e) { setErr((e as Error).message); }
  }, []);
  useEffect(() => { reload(); settingsApi.types().then(setTypes).catch(() => {}); }, [reload]);

  const changed = async () => { await reload(); onChanged(); };

  const run = async (id: string, fn: () => Promise<string | void>) => {
    setBusyIds((b) => ({ ...b, [id]: true }));
    try { const msg = await fn(); if (msg) toast("ok", msg); }
    catch (e) { toast("error", (e as Error).message); }
    finally { setBusyIds((b) => ({ ...b, [id]: false })); await changed(); }
  };

  const providers = data?.providers ?? [];
  const onlyFake = !!data && providers.length === 0;
  const addBtn = <Button variant="pink" onClick={() => setAdding(true)}><Plus size={15} />Add Provider</Button>;

  return (
    <Card
      title={<span className="flex items-center gap-3"><IconTile tone="violet"><KeyRound size={15} /></IconTile>AI Providers</span>}
      sub="Connect your AI providers to generate content. You can enable several and choose which one each task uses."
      right={addBtn}>
      {!data && !err && <div role="status" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="panel-quiet h-36 animate-pulse rounded-2xl" />)}<span className="sr-only">Loading providers…</span></div>}
      {err && (
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-xl border border-red-400/40 bg-red-400/10 p-3 text-sm text-red-200">
          <AlertCircle size={16} />Could not load providers: {err}
          <Button variant="outline" size="sm" onClick={reload}>Retry</Button>
        </div>
      )}
      {data && (
        <div className="space-y-3">
          {onlyFake && (
            <div className="rounded-2xl border border-dashed border-slate-700 p-6 text-center">
              <h4 className="text-base font-bold text-slate-100">Connect your first provider</h4>
              <p className="mx-auto mt-1 max-w-md text-sm text-slate-400">Add a provider and a key to generate real content. To try the whole workflow for free, create a test project (switch on "Test project").</p>
              <div className="mt-3 flex justify-center">{addBtn}</div>
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {providers.map((p) => <ProviderCard key={p.id} p={p} busy={!!busyIds[p.id]} run={run} reload={changed} />)}
          </div>
          <p className="text-xs text-slate-400">Keys are stored in {data.secrets_backend === "keychain" ? "your OS keychain" : "a private file outside the project"} and are never shown again.</p>
        </div>
      )}
      <AddProviderDialog open={adding} onClose={() => setAdding(false)} types={types} onCreated={() => { changed(); }} />
    </Card>
  );
}
