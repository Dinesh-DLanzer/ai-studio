import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Button, Input, Modal } from "../ui";
import { useToast } from "../toast";
import { settingsApi } from "./client";
import type { Provider, ProviderType } from "./types";

export const FIELD_LABELS: Record<string, string> = { api_key: "API Key", access_key: "Access key", secret_key: "Secret key" };
export const fieldLabel = (f: string) => FIELD_LABELS[f] || f.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export function AddProviderDialog({ open, onClose, types, onCreated }: {
  open: boolean; onClose: () => void; types: ProviderType[]; onCreated: (p: Provider) => void;
}) {
  const toast = useToast();
  const [preset, setPreset] = useState<ProviderType | null>(null);
  const [name, setName] = useState(""); const [url, setUrl] = useState("");
  const [keys, setKeys] = useState<Record<string, string>>({}); const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setPreset(null); setName(""); setUrl(""); setKeys({}); setBusy(false); } }, [open]);

  const pick = (t: ProviderType) => { setPreset(t); setName(t.label); setUrl(""); setKeys({}); };
  const keyOptional = preset?.type === "custom";
  const canSave = !!preset && !busy && name.trim() !== "" && (!preset.base_url || url.trim() !== "")
    && (keyOptional || preset.fields.every((f) => (keys[f] || "").trim() !== ""));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!preset || !canSave) return;
    setBusy(true);
    try {
      const secret: Record<string, string> = {};
      for (const f of preset.fields) if ((keys[f] || "").trim()) secret[f] = keys[f].trim();
      const created = await settingsApi.createProvider({
        type: preset.type, label: name.trim(),
        ...(preset.base_url ? { base_url: url.trim() } : {}),
        ...(Object.keys(secret).length ? { secret } : {}),
      });
      let final = created;
      try {
        const t = await settingsApi.testProvider(created.id);
        final = t.provider;
        toast(t.result.ok ? "ok" : "error", t.result.ok ? `${name.trim()}: ${t.result.message || "Connected successfully"}` : `${name.trim()} was added, but the test failed: ${t.result.message}`);
      } catch (err) {
        toast("error", `${name.trim()} was added, but the test failed: ${(err as Error).message}`);
      }
      onCreated(final);
      onClose();
    } catch (err) {
      toast("error", (err as Error).message);
    } finally { setBusy(false); }
  };

  return (
    <Modal open={open} onClose={onClose} title={preset ? `Add ${preset.label}` : "Add Provider"}>
      {!preset ? (
        <div>
          <p className="mb-3 text-sm text-slate-400">Choose a provider to connect.</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {types.filter((t) => t.type !== "fake").map((t) => (
              <button key={t.type} type="button" onClick={() => pick(t)}
                className="panel-quiet rounded-xl p-3 text-left transition hover:border-violet-400/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-400">
                <div className="text-sm font-semibold text-slate-100">{t.label}</div>
                <div className="mt-0.5 text-xs text-slate-400">{t.sub}</div>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3">
          <p className="text-sm text-slate-400">{preset.sub}</p>
          <label className="block">
            <span className="mb-1.5 block text-xs font-semibold text-slate-300">Name</span>
            <Input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          {preset.base_url && (
            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold text-slate-300">Base URL</span>
              <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://api.example.com/v1" required inputMode="url" />
            </label>
          )}
          {preset.fields.map((f) => (
            <label key={f} className="block">
              <span className="mb-1.5 block text-xs font-semibold text-slate-300">{fieldLabel(f)}{keyOptional && <span className="font-normal text-slate-400"> (optional)</span>}</span>
              <Input type="password" autoComplete="off" value={keys[f] || ""} onChange={(e) => setKeys({ ...keys, [f]: e.target.value })} placeholder={`Enter your ${fieldLabel(f).toLowerCase()}`} />
            </label>
          ))}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => setPreset(null)} disabled={busy}>Back</Button>
            <Button variant="pink" type="submit" disabled={!canSave}>{busy && <Loader2 size={14} className="animate-spin" />}Save &amp; test</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
