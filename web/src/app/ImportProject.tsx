import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FileArchive, Upload } from "lucide-react";
import { getToken } from "../api";
import { Button, Input } from "../ui";
import { useToast } from "../toast";

const safeName = (file: string) => file.replace(/\.zip$/i, "").replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^[-_]+|[-_]+$/g, "").slice(0, 64);
const mb = (n: number) => (n / 1024 / 1024).toFixed(n > 10 * 1024 * 1024 ? 0 : 1);

/** "Import project (zip)": pick a zip made by Export Project, name it, upload.  The server checks every file and refuses the whole zip if anything is wrong. */
export default function ImportProject({ onDone, compact = false }: { onDone?: () => void; compact?: boolean }) {
  const nav = useNavigate(); const toast = useToast(); const pick = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null); const [name, setName] = useState(""); const [busy, setBusy] = useState(false); const [problems, setProblems] = useState<string[]>([]);
  const choose = (f?: File | null) => { if (!f) return; setFile(f); setName(safeName(f.name)); setProblems([]); };
  const run = async () => {
    if (!file || busy) return; setBusy(true); setProblems([]);
    try {
      const r = await fetch(`/api/projects/import?filename=${encodeURIComponent(file.name)}&name=${encodeURIComponent(name.trim())}`, { method: "POST", headers: { "x-aistudio-token": getToken() }, body: file });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { setProblems((j as any).problems || [(j as any).detail || r.statusText]); return; }
      toast("ok", `Imported ${j.name} (${j.files} files).${(j.notes || []).length ? " " + j.notes.join(" ") : ""}`);
      onDone?.(); nav(`/p/${j.name}`);
    } catch (e: any) { setProblems([e.message || "Upload failed"]); }
    finally { setBusy(false); }
  };
  return (
    <div className={`w-full text-left ${compact ? "" : "space-y-2"}`} data-testid="import-project">
      <input ref={pick} type="file" accept=".zip,application/zip,application/x-zip-compressed" className="sr-only" aria-label="Project zip file" onChange={(e) => { choose(e.target.files?.[0]); e.target.value = ""; }} />
      {!file ? (
        <Button variant="outline" className="w-full" onClick={() => pick.current?.click()}><Upload size={16} />Import project (zip)</Button>
      ) : (
        <div className="space-y-2 rounded-xl border border-slate-800 bg-white/[.02] p-2.5">
          <div className="flex items-center gap-2 text-xs text-slate-300"><FileArchive size={15} className="shrink-0" /><span className="min-w-0 flex-1 truncate">{file.name}</span><span className="shrink-0 text-slate-400">{mb(file.size)} MB</span></div>
          <Input aria-label="Imported project name" placeholder="project-name" value={name} onChange={(e) => { setName(e.target.value); setProblems([]); }} />
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => { setFile(null); setProblems([]); }} disabled={busy}>Choose another</Button>
            <Button size="sm" className="flex-1" onClick={run} disabled={busy || !name.trim()}>{busy ? "Checking and importing..." : "Import"}</Button>
          </div>
        </div>
      )}
      {problems.length > 0 && (
        <div role="alert" className="rounded-xl border border-red-400/40 bg-red-400/10 p-2.5 text-xs text-red-200" data-testid="import-problems">
          <div className="mb-1 font-bold">This zip was not imported. Nothing was changed.</div>
          <ul className="max-h-40 list-disc space-y-0.5 overflow-auto pl-4">{problems.slice(0, 30).map((p, i) => <li key={i} className="break-words">{p}</li>)}</ul>
          {problems.length > 30 && <div className="mt-1">...and {problems.length - 30} more.</div>}
        </div>
      )}
    </div>
  );
}
