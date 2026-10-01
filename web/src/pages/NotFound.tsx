import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft, FolderOpen, HelpCircle, RotateCcw, Search } from "lucide-react";
import { api } from "../api";
import { Button } from "../ui";
import { useToast } from "../toast";

interface TrashItem { id: string; name: string; when: string }

/** A real 404: a page that does not exist, or (kind="project") a project that is missing, renamed, deleted or not imported yet. */
export default function NotFound({ kind = "page", name, onRestored }: { kind?: "page" | "project"; name?: string; onRestored?: () => void }) {
  const nav = useNavigate(); const loc = useLocation(); const toast = useToast();
  const [names, setNames] = useState<string[]>([]); const [trash, setTrash] = useState<TrashItem[]>([]); const [busy, setBusy] = useState(false);
  useEffect(() => {
    const old = document.title; document.title = "Page not found - AI Studio";
    api<{ projects: { name: string }[] }>("GET", "/api/projects").then((r) => setNames(r.projects.map((p) => p.name))).catch(() => {});
    api<{ items: TrashItem[] }>("GET", "/api/trash").then((r) => setTrash(r.items)).catch(() => {});
    return () => { document.title = old; };
  }, []);
  const inTrash = kind === "project" && name ? trash.find((t) => t.name === name) : undefined;
  const similar = kind === "project" && name ? names.filter((n) => n.toLowerCase().includes(name.toLowerCase()) || name.toLowerCase().includes(n.toLowerCase())) : [];
  const restore = async () => {
    if (!inTrash) return; setBusy(true);
    try { const r = await api<{ name: string }>("POST", `/api/trash/${inTrash.id}/restore`, {}); toast("ok", `Restored ${r.name}.`); nav(`/p/${r.name}`, { replace: true }); onRestored?.(); }
    catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center px-4 py-12 text-center sm:py-16" data-testid="not-found">
      <div className="bg-gradient-to-r from-pink to-violet bg-clip-text text-8xl font-black leading-none tracking-tighter text-transparent sm:text-9xl" aria-hidden>404</div>
      <h1 className="mt-4 text-2xl font-extrabold tracking-tight">{kind === "project" ? "Project not found" : "Page not found"}</h1>
      {kind === "project"
        ? <p className="mt-2 max-w-md text-sm text-slate-400">There is no project called <b className="text-slate-200">{name}</b> in this workspace. It may have been renamed, deleted, or not imported on this computer yet.</p>
        : <p className="mt-2 max-w-md text-sm text-slate-400">The address <code className="rounded bg-white/5 px-1.5 py-0.5 text-slate-300">{loc.pathname === "/" ? "#" + loc.pathname : "#" + loc.pathname}</code> does not match anything in AI Studio.</p>}

      {inTrash && (
        <div className="panel panel-lit panel-pad mt-6 w-full text-left" data-testid="nf-trash">
          <div className="text-sm font-bold">It is in the trash</div>
          <p className="mt-1 text-xs text-slate-400">{inTrash.name} was moved to the trash on {inTrash.when.replace("T", " ")}. Nothing was erased.</p>
          <Button className="mt-3" onClick={restore} disabled={busy}><RotateCcw size={15} />Restore {inTrash.name}</Button>
        </div>
      )}
      {similar.length > 0 && (
        <div className="mt-6 w-full text-left" data-testid="nf-similar">
          <div className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-400">Did you mean</div>
          <ul className="flex flex-wrap gap-2">{similar.slice(0, 6).map((n) => <li key={n}><Link className="btn btn-outline btn-sm" to={`/p/${n}`}><FolderOpen size={13} />{n}</Link></li>)}</ul>
        </div>
      )}

      <div className="mt-8 flex flex-wrap items-center justify-center gap-2">
        <Link to="/" className="btn btn-lime"><ArrowLeft size={16} />All projects</Link>
        {kind === "page" && name !== undefined && <Link to={`/p/${name}`} className="btn btn-outline">Back to the project</Link>}
        <Link to="/help" className="btn btn-outline"><HelpCircle size={16} />Help &amp; Docs</Link>
        <button type="button" className="btn btn-ghost" onClick={() => nav(-1)}><Search size={15} />Go back</button>
      </div>
    </div>
  );
}
