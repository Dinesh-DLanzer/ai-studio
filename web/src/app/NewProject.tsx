import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import { api } from "../api";
import { Button, Input, Label, Modal, Select } from "../ui";
import ImportProject from "./ImportProject";
import { useSetupNeeded } from "./setupContext";

interface Fmt { id: string; label: string; aspect_ratio: string; shots: number; seconds_per_shot: number; resolution: string; audio: boolean; brief: { purpose: string } }

/** The "Generate New Video" popup: name a project (optionally as a free test pipeline) and open its chat. */
export default function NewProjectDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate(); const noProvider = useSetupNeeded();
  const [name, setName] = useState(""); const [test, setTest] = useState(false); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const [formats, setFormats] = useState<Fmt[]>([]); const [fmt, setFmt] = useState(""); const [kits, setKits] = useState<{ id: string; name: string }[]>([]); const [kit, setKit] = useState("");
  useEffect(() => {
    if (!open) return;
    api<{ formats: Fmt[] }>("GET", "/api/formats").then((r) => setFormats(r.formats)).catch(() => {});
    api<{ kits: { id: string; name: string }[] }>("GET", "/api/brand-kits").then((r) => setKits(r.kits)).catch(() => {});
  }, [open]);
  const close = () => { setName(""); setTest(false); setFmt(""); setKit(""); setErr(""); onClose(); };
  const create = async () => {
    const n = name.trim(); if (!n || busy) return;
    setBusy(true);
    try { await api("POST", "/api/projects", { name: n, test_pipeline: test || noProvider, ...(fmt ? { format: fmt } : {}), ...(kit ? { brand_kit: kit } : {}) }); close(); nav(`/p/${n}/chat`); }
    catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={close} title="Generate New Video">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void create(); }}>
        <p className="text-sm text-slate-400">Every video is its own project. Name it, then describe your idea in the chat.</p>
        <Input autoFocus aria-label="New project name" placeholder="project-name (letters, numbers, - _)" value={name} onChange={(e) => { setName(e.target.value); setErr(""); }} />
        <fieldset>
          <legend className="mb-1.5 text-xs font-semibold text-slate-300">Format</legend>
          <div role="radiogroup" aria-label="Format" className="grid max-h-56 grid-cols-2 gap-2 overflow-auto pr-1 sm:grid-cols-3" data-testid="format-grid">
            {[{ id: "", label: "Blank", sub: "Start from nothing, as before" }, ...formats.map((f) => ({ id: f.id, label: f.label, sub: `${f.aspect_ratio} · ${f.shots} shots × ${f.seconds_per_shot}s` }))].map((f) => {
              const on = fmt === f.id;
              return (
                <button key={f.id || "blank"} type="button" role="radio" aria-checked={on} onClick={() => setFmt(f.id)} data-testid={`format-${f.id || "blank"}`}
                  className={`rounded-xl border p-2.5 text-left transition ${on ? "border-pink/70 bg-pink/10 shadow-glow-pink" : "border-slate-800 hover:border-slate-600"}`}>
                  <span className="block text-sm font-bold">{f.label}{on ? <span className="sr-only"> (selected)</span> : null}</span>
                  <span className="block text-[0.7rem] text-slate-400">{f.sub}</span>
                </button>
              );
            })}
          </div>
        </fieldset>
        {kits.length > 0 && (
          <div><Label>Brand kit (optional)</Label>
            <Select aria-label="Brand kit" value={kit} onChange={(e) => setKit(e.target.value)}><option value="">none</option>{kits.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}</Select></div>
        )}
        <label className="flex cursor-pointer items-start gap-2.5 rounded-xl border border-slate-800 bg-white/[.02] p-2.5 text-left">
          <input type="checkbox" role="switch" className="mt-0.5 h-4 w-4 shrink-0 accent-[#d7ff3f]" checked={test || noProvider} onChange={(e) => setTest(e.target.checked)} aria-label="Test project" disabled={noProvider} />
          <span className="min-w-0 text-xs">
            <span className="block font-bold text-slate-100">Test project (free){noProvider ? " - no provider connected yet" : ""}</span>
            <span className="mt-0.5 block text-slate-400">Images, clips and reviews are simulated, so it costs nothing. The chat uses your AI provider once you connect one.</span>
          </span>
        </label>
        {err && <p className="text-xs text-red-400" role="alert">{err}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={close}>Cancel</Button>
          <Button type="submit" disabled={!name.trim() || busy}><Plus size={16} />Create</Button>
        </div>
        <div className="flex items-center gap-3 text-[0.7rem] uppercase tracking-wider text-slate-400"><span className="h-px flex-1 bg-slate-800" />or<span className="h-px flex-1 bg-slate-800" /></div>
        <ImportProject onDone={close} />
      </form>
    </Modal>
  );
}
