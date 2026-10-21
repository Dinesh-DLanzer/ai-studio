import { useEffect, useState } from "react";
import { api } from "../api";
import { Button, Input, Select } from "../ui";
import { useToast } from "../toast";
import type { Proposal } from "../types";

const LOCAL: Record<string, { params: Record<string, unknown>; label: string }> = {
  speed: { label: "Change speed", params: { factor: 1.5 } },
  loop: { label: "Loop clip", params: { times: 2 } },
  interpolate: { label: "Smooth motion", params: { fps: 48, slowmo: 2 } },
  reframe_local: { label: "Reframe", params: { aspect: "9:16", mode: "pad" } },
  upscale_local: { label: "Upscale", params: { scale: 2 } },
  stabilize: { label: "Stabilize", params: {} },
};
const AI = ["upscale_ai", "reframe_ai", "restyle", "replace", "motion_transfer", "character_swap"];

/** Local transforms run free into a new version. AI transforms only open the human approval proposal dialog. */
export default function ClipToolsPanel({ project, clip, reload, openProposal }: { project: string; clip: string; reload: () => void; openProposal?: (p: Proposal) => void }) {
  const toast = useToast(); const [tool, setTool] = useState("speed"); const [ai, setAi] = useState(AI[0]); const [prompt, setPrompt] = useState(""); const [busy, setBusy] = useState(false);
  // Which tools the configured providers/ffmpeg can really do (display only; the server re-checks on every call and fails closed). If the lookup fails, show everything.
  const [avail, setAvail] = useState<Record<string, { available: boolean; reason: string | null }> | null>(null);
  useEffect(() => {
    api<{ tools: { id: string; available: boolean; reason: string | null }[] }>("GET", `/api/projects/${encodeURIComponent(project)}/clip-tools`)
      .then((r) => setAvail(Object.fromEntries(r.tools.map((t) => [t.id, t])))).catch(() => setAvail(null));
  }, [project]);
  const ok = (id: string) => !avail || avail[id]?.available !== false;
  const localIds = Object.keys(LOCAL).filter(ok); const aiIds = AI.filter(ok);
  const hidden = avail ? [...Object.keys(LOCAL), ...AI].filter((id) => !ok(id)) : [];
  useEffect(() => { if (!localIds.includes(tool) && localIds[0]) setTool(localIds[0]); if (!aiIds.includes(ai) && aiIds[0]) setAi(aiIds[0]); }, [avail]);   // eslint-disable-line react-hooks/exhaustive-deps
  const runLocal = async () => {
    setBusy(true);
    try { const out = await api<{ file: string }>("POST", `/api/projects/${encodeURIComponent(project)}/clips/${encodeURIComponent(clip)}/local-tool`, { tool, params: LOCAL[tool].params }); toast("ok", `Free local version saved: ${out.file}`); reload(); }
    catch (e) { toast("error", (e as Error).message); } finally { setBusy(false); }
  };
  const propose = async () => {
    setBusy(true);
    try { const p = await api<Proposal>("POST", `/api/projects/${encodeURIComponent(project)}/clips/${encodeURIComponent(clip)}/tool`, { tool: ai, ...(prompt.trim() ? { prompt: prompt.trim() } : {}) }); if (openProposal) openProposal(p); else toast("info", `Proposal created at ${p.price == null ? "the quoted price" : `$${p.price.toFixed(3)}`}; approve it from Proposals.`); }
    catch (e) { toast("error", (e as Error).message); } finally { setBusy(false); }
  };
  const pretty = (id: string) => id.split("_").join(" ");
  return <section className="panel-quiet space-y-4 p-3" aria-label={`Clip tools for ${clip}`} data-testid="clip-tools">
    <header>
      <h3 className="text-sm font-bold">Clip tools</h3>
      <p className="mt-0.5 text-xs text-slate-400">Free local tools save a new version. AI tools only create a priced proposal for you to approve.</p>
    </header>
    <div className="space-y-1.5">
      <label className="block text-xs font-semibold text-slate-300" htmlFor={`local-tool-${clip}`}>Local tool <span className="font-normal text-slate-400">(free)</span></label>
      <div className="flex items-center gap-2">
        <Select id={`local-tool-${clip}`} aria-label="Local clip tool" className="min-w-0 flex-1" value={tool} onChange={(e) => setTool(e.target.value)}>{Object.entries(LOCAL).filter(([k]) => ok(k)).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</Select>
        <Button size="sm" variant="outline" className="shrink-0" disabled={busy || !localIds.length} onClick={() => void runLocal()}>Run free tool</Button>
      </div>
    </div>
    <div className="space-y-1.5">
      <label className="block text-xs font-semibold text-slate-300" htmlFor={`ai-tool-${clip}`}>AI tool <span className="font-normal text-slate-400">(paid, you approve the price)</span></label>
      {aiIds.length ? <>
        <Select id={`ai-tool-${clip}`} aria-label="AI clip tool" className="w-full" value={ai} onChange={(e) => setAi(e.target.value)}>{aiIds.map((v) => <option key={v} value={v}>{pretty(v)}</option>)}</Select>
        <Input id={`ai-prompt-${clip}`} aria-label="AI clip tool prompt" className="w-full" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Describe the change (when needed)" />
        <Button size="sm" variant="outline" className="w-full" disabled={busy} onClick={() => void propose()}>Propose AI tool</Button>
      </> : <p className="rounded-lg border border-slate-800 px-3 py-2 text-xs text-slate-400" data-testid="clip-tools-none">No AI clip tool is available with your current video models.</p>}
    </div>
    {!!hidden.length && <details className="text-xs text-slate-400" data-testid="clip-tools-hidden">
      <summary className="cursor-pointer text-slate-300">Why are some tools missing?</summary>
      <ul className="mt-2 list-disc space-y-1 pl-4">{hidden.map((id) => <li key={id}><b className="font-semibold text-slate-300">{pretty(id)}</b>: {avail?.[id]?.reason || "not supported"}</li>)}</ul>
    </details>}
    <p className="text-[0.7rem] leading-relaxed text-slate-500">The server checks provider support and real-person consent every time. Nothing is approved or spent from this panel.</p>
  </section>;
}
