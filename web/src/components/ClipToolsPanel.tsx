import { useState } from "react";
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
  return <section className="panel-quiet space-y-2 p-3" aria-label={`Clip tools for ${clip}`} data-testid="clip-tools">
    <h3 className="text-sm font-bold">Clip tools <span className="text-xs font-normal text-slate-400">Local tools are free and save a new version.</span></h3>
    <div className="flex flex-wrap items-end gap-2"><div><label className="mb-1 block text-xs" htmlFor={`local-tool-${clip}`}>Local tool</label><Select id={`local-tool-${clip}`} aria-label="Local clip tool" value={tool} onChange={(e) => setTool(e.target.value)}>{Object.entries(LOCAL).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</Select></div><Button size="sm" variant="outline" disabled={busy} onClick={() => void runLocal()}>Run free tool</Button></div>
    <div className="flex flex-wrap items-end gap-2"><div><label className="mb-1 block text-xs" htmlFor={`ai-tool-${clip}`}>AI tool</label><Select id={`ai-tool-${clip}`} aria-label="AI clip tool" value={ai} onChange={(e) => setAi(e.target.value)}>{AI.map((v) => <option key={v} value={v}>{v.split("_").join(" ")}</option>)}</Select></div><div className="min-w-40 flex-1"><label className="mb-1 block text-xs" htmlFor={`ai-prompt-${clip}`}>Prompt (when needed)</label><Input id={`ai-prompt-${clip}`} aria-label="AI clip tool prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Describe the change" /></div><Button size="sm" variant="outline" disabled={busy} onClick={() => void propose()}>Propose AI tool</Button></div>
    <p className="text-xs text-slate-400">AI tools create a priced proposal only. The server checks provider support and real-person consent; no approval or spend happens here.</p>
  </section>;
}
