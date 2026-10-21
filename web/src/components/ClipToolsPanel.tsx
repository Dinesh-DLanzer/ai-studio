import { useEffect, useState } from "react";
import { api } from "../api";
import { RailCard } from "./kit";

interface ClipTool { id: string; kind: "local" | "ai"; available: boolean; reason: string | null; consent: string }

/** Shows only tools verified for this installation; unavailable tools stay discoverable with their reason. */
export default function ClipToolsPanel({ project }: { project: string }) {
  const [tools, setTools] = useState<ClipTool[]>([]);
  useEffect(() => { api<{ tools: ClipTool[] }>("GET", `/api/projects/${encodeURIComponent(project)}/clip-tools`).then((r) => setTools(r.tools)).catch(() => setTools([])); }, [project]);
  const available = tools.filter((tool) => tool.available);
  const unavailable = tools.filter((tool) => !tool.available);
  return <RailCard title="Clip tools" sub="Tools available with your FFmpeg and configured video models">
    {available.length ? <ul className="flex flex-wrap gap-1.5">{available.map((tool) => <li key={tool.id}><span className="tag tag-emerald" title={`${tool.kind === "ai" ? "AI proposal; human approval required. " : "Local processing. "}${tool.consent}`}>{tool.id}</span></li>)}</ul>
      : <p className="text-xs text-slate-400">No clip tools are available yet.</p>}
    {unavailable.length > 0 && <details className="mt-3 text-xs">
      <summary className="cursor-pointer text-slate-400">Unavailable tools ({unavailable.length})</summary>
      <ul className="mt-2 space-y-1.5">{unavailable.map((tool) => <li key={tool.id} className="flex justify-between gap-2" title={tool.reason || "Unavailable"}><span>{tool.id}</span><span className="text-right text-slate-500">{tool.reason || "Unavailable"}</span></li>)}</ul>
    </details>}
  </RailCard>;
}
