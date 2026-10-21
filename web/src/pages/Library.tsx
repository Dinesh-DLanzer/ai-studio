import { useCallback, useEffect, useRef, useState } from "react";
import { Film, LayoutGrid, Library as LibraryIcon, List, Music, RefreshCw, Search, Star } from "lucide-react";
import { api, getToken } from "../api";
import { Fragment } from "react";
import { Button, Input, Label, PageHeader, Select, money } from "../ui";
import { EmptyState, RailCard } from "../components/kit";
import { useProposal } from "../Proposal";
import { useToast } from "../toast";
import type { Proposal } from "../types";
import { PageBody } from "../app/Shell";

interface Item { id: string; project: string; kind: string; category: string; file: string; prompt: string; model: string; provider: string; seed: string; params: string; cost: number; status: string; favorite: number; created: number; meta: string }
interface Page { items: Item[]; total: number }
const LIMIT = 60;
const fileSrc = (id: string) => `/api/library/${id}/file?token=${encodeURIComponent(getToken())}`;
const when = (t: number) => new Date(t * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const inLibrary = (i: Item) => i.project === "_library";

function Thumb({ item, className = "" }: { item: Item; className?: string }) {
  return (
    <div className={`thumb ${className}`}>
      {item.kind === "image" ? <img src={fileSrc(item.id)} alt={`${item.kind} ${item.file}`} loading="lazy" />
        : item.kind === "clip" ? <video src={`${fileSrc(item.id)}#t=0.5`} preload="metadata" muted playsInline aria-label={`clip ${item.file}`} />
        : <div className="grid h-full place-items-center text-slate-500">{item.kind === "audio" ? <Music size={22} aria-label="audio" /> : <Film size={22} aria-label={item.kind} />}</div>}
    </div>
  );
}

/** Library: every generation across all projects (and what you promoted for reuse). Search, favourite, remix into a proposal you approve, or copy into a project. */
export default function Library() {
  const toast = useToast();
  const [q, setQ] = useState(""); const [type, setType] = useState(""); const [project, setProject] = useState(""); const [fav, setFav] = useState(false); const [failed, setFailed] = useState(false);
  const [view, setView] = useState<"grid" | "list">("grid"); const [data, setData] = useState<Page | null>(null); const [limit, setLimit] = useState(LIMIT);
  const [sel, setSel] = useState<string | null>(null); const [projects, setProjects] = useState<string[]>([]); const [target, setTarget] = useState(""); const [busy, setBusy] = useState(false);
  const [remixProject, setRemixProject] = useState(""); const [remixMode, setRemixMode] = useState("real");
  const { open: openProposal, dialog } = useProposal(remixProject, remixMode, () => {});
  const rebuilt = useRef(false);

  const load = useCallback(async () => {
    const p = new URLSearchParams({ limit: String(limit) });
    if (q.trim()) p.set("q", q.trim()); if (type) p.set("type", type); if (project) p.set("project", project); if (fav) p.set("favorite", "1"); if (failed) p.set("failed", "1");
    try {
      const r = await api<Page>("GET", `/api/library?${p}`);
      if (!r.total && !rebuilt.current && !q && !type && !project && !fav && !failed) { rebuilt.current = true; await api("POST", "/api/library/rebuild"); return setData(await api<Page>("GET", `/api/library?${p}`)); }
      setData(r);
    } catch (e) { toast("error", (e as Error).message); }
  }, [q, type, project, fav, failed, limit, toast]);
  useEffect(() => { const t = setTimeout(() => void load(), 200); return () => clearTimeout(t); }, [load]);
  useEffect(() => { api<{ projects: { name: string }[] }>("GET", "/api/projects").then((r) => { setProjects(r.projects.map((x) => x.name)); setTarget((t) => t || r.projects[0]?.name || ""); }).catch(() => {}); }, []);

  const cur = data?.items.find((i) => i.id === sel) || null;
  const act = async (fn: () => Promise<void>) => { setBusy(true); try { await fn(); } catch (e) { toast("error", (e as Error).message); } finally { setBusy(false); } };
  const rebuild = () => act(async () => { const r = await api<{ count: number }>("POST", "/api/library/rebuild"); toast("ok", `Index rebuilt: ${r.count} items.`); await load(); });
  const star = (i: Item) => act(async () => { await api("POST", `/api/library/${i.id}/favorite`, { on: !i.favorite }); await load(); });
  const promote = (i: Item) => act(async () => { await api("POST", "/api/library/promote", { project: i.project, file: i.file }); toast("ok", `${i.file} is now in the library for reuse.`); await load(); });
  const use = (i: Item) => act(async () => {
    const r = await api<Item>("POST", "/api/library/use", { id: i.id, project: target, kind: i.kind === "clip" || i.kind === "audio" ? i.kind : "image" });
    toast("ok", `Copied into ${target} as ${r.file}.`);
  });
  const remix = (i: Item) => act(async () => {
    const r = await api<{ proposal: Proposal }>("POST", `/api/projects/${encodeURIComponent(i.project)}/remix`, { meta: `${i.file}.meta.json` });
    const o = await api<{ mode: string }>("GET", `/api/projects/${encodeURIComponent(i.project)}`).catch(() => ({ mode: "real" }));
    setRemixMode(o.mode); setRemixProject(i.project); openProposal(r.proposal);
  });

  const card = (i: Item) => (
    <li key={i.id} className="relative min-w-0">
      <button type="button" onClick={() => setSel(i.id)} aria-pressed={sel === i.id} aria-label={`Open ${i.file} from ${inLibrary(i) ? "the library" : i.project}`}
        className={`panel w-full overflow-hidden text-left transition ${sel === i.id ? "!border-pink shadow-glow-pink" : "hover:border-slate-700"}`}>
        <Thumb item={i} className="aspect-video !rounded-none" />
        <div className="p-2.5">
          <div className="truncate text-sm font-semibold">{i.file.split("/").pop()}</div>
          <div className="mt-0.5 truncate text-[0.7rem] text-slate-400">{inLibrary(i) ? "Library" : i.project} · {i.model.split("/").pop() || i.kind}</div>
          {i.status !== "completed" && <span className="tag tag-red mt-1">{i.status}</span>}
        </div>
      </button>
      <button type="button" onClick={() => void star(i)} aria-pressed={!!i.favorite} aria-label={i.favorite ? `Remove ${i.file} from favourites` : `Add ${i.file} to favourites`} className="icon-btn absolute right-2 top-2 !h-8 !w-8 !bg-black/60"><Star size={15} className={i.favorite ? "fill-amber-300 text-amber-300" : ""} /></button>
    </li>
  );
  const row = (i: Item) => (
    <li key={i.id} className={`flex items-center gap-3 rounded-xl border px-2.5 py-2 ${sel === i.id ? "border-pink" : "border-slate-800"}`}>
      <Thumb item={i} className="h-12 w-20 shrink-0" />
      <button type="button" className="min-w-0 flex-1 text-left" onClick={() => setSel(i.id)} aria-pressed={sel === i.id} aria-label={`Open ${i.file} from ${inLibrary(i) ? "the library" : i.project}`}>
        <span className="block truncate text-sm font-semibold">{i.file}</span>
        <span className="block truncate text-xs text-slate-400">{inLibrary(i) ? "Library" : i.project} · {i.model || i.kind} · {i.prompt.slice(0, 80)}</span>
      </button>
      <span className="shrink-0 text-xs text-slate-400">{money(i.cost)}</span>
      {i.status !== "completed" && <span className="tag tag-red">{i.status}</span>}
      <button type="button" onClick={() => void star(i)} aria-pressed={!!i.favorite} aria-label={i.favorite ? `Remove ${i.file} from favourites` : `Add ${i.file} to favourites`} className="icon-btn !h-8 !w-8"><Star size={15} className={i.favorite ? "fill-amber-300 text-amber-300" : ""} /></button>
    </li>
  );

  const params = (i: Item) => { try { return Object.entries(JSON.parse(i.params || "{}")).filter(([, v]) => v !== "" && v !== null && typeof v !== "object"); } catch { return []; } };

  return (
    <div className="animate-fade-up">
      <PageHeader title="Library" sub="Everything you have generated, across all projects. Remix a result, or copy a favourite into another project." icon={<LibraryIcon size={24} />}
        right={<Button variant="outline" size="sm" disabled={busy} onClick={() => void rebuild()}><RefreshCw size={14} />Rebuild index</Button>} />
      <PageBody rail={cur ? (
        <RailCard title="Details" sub={cur.file}>
          <div data-testid="library-detail" className="space-y-3 text-sm">
            <Thumb item={cur} className="aspect-video" />
            <dl className="kv">
              <dt>Project</dt><dd>{inLibrary(cur) ? "Library" : cur.project}</dd>
              <dt>Type</dt><dd>{cur.kind}{cur.category && cur.category !== cur.kind ? ` · ${cur.category}` : ""}</dd>
              <dt>Model</dt><dd>{cur.model || "unknown"}{cur.provider ? ` (${cur.provider})` : ""}</dd>
              <dt>Seed</dt><dd>{cur.seed || "not sent"}</dd>
              <dt>Cost</dt><dd>{money(cur.cost)}</dd>
              <dt>Status</dt><dd>{cur.status}</dd>
              <dt>Date</dt><dd>{when(cur.created)}</dd>
              {params(cur).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{String(v)}</dd></Fragment>)}
            </dl>
            <div><Label>Prompt</Label><p className="panel-quiet whitespace-pre-wrap px-3 py-2 text-xs">{cur.prompt || "No prompt recorded."}</p></div>
            <div className="flex flex-wrap gap-2">
              {!inLibrary(cur) && <Button variant="outline" size="sm" disabled={busy || cur.status !== "completed"} onClick={() => void promote(cur)}>Add to library</Button>}
              {!inLibrary(cur) && (cur.kind === "image" || cur.kind === "clip") && <Button variant="pink" size="sm" disabled={busy} onClick={() => void remix(cur)}>Remix (shows the price)</Button>}
            </div>
            {inLibrary(cur) ? (
              <div className="flex items-end gap-2">
                <div className="min-w-0 flex-1"><Label>Use in project</Label>
                  <Select aria-label="Project to copy into" value={target} onChange={(e) => setTarget(e.target.value)}>{projects.map((p) => <option key={p} value={p}>{p}</option>)}</Select></div>
                <Button variant="primary" size="sm" disabled={busy || !target} onClick={() => void use(cur)}>Use in project</Button>
              </div>
            ) : <p className="text-xs text-slate-400">To use this in another project, add it to the library first.</p>}
            <p className="text-[0.68rem] text-slate-400">Remix only prepares a proposal. Nothing is generated or spent until you approve the exact price.</p>
          </div>
        </RailCard>
      ) : <RailCard title="Details"><p className="text-sm text-slate-400">Pick an item to see its prompt, model, settings and cost.</p></RailCard>}>
        <div className="panel mb-4 flex flex-wrap items-end gap-3 p-3">
          <div className="relative min-w-[12rem] flex-1">
            <Search size={15} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <Input aria-label="Search the library" placeholder="Search prompts, projects, models" className="!pl-9" value={q} onChange={(e) => { setQ(e.target.value); setLimit(LIMIT); }} />
          </div>
          <Select aria-label="Type" className="!w-32" value={type} onChange={(e) => { setType(e.target.value); setLimit(LIMIT); }}><option value="">All types</option><option value="image">Images</option><option value="clip">Clips</option><option value="audio">Audio</option></Select>
          <Select aria-label="Project" className="!w-40" value={project} onChange={(e) => { setProject(e.target.value); setLimit(LIMIT); }}><option value="">All projects</option><option value="_library">Library only</option>{projects.map((p) => <option key={p} value={p}>{p}</option>)}</Select>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={fav} onChange={(e) => setFav(e.target.checked)} /> Favourites</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={failed} onChange={(e) => setFailed(e.target.checked)} /> Failed runs</label>
          <div role="group" aria-label="View" className="flex gap-1">
            <button type="button" className="icon-btn" aria-pressed={view === "grid"} aria-label="Grid view" onClick={() => setView("grid")}><LayoutGrid size={16} /></button>
            <button type="button" className="icon-btn" aria-pressed={view === "list"} aria-label="List view" onClick={() => setView("list")}><List size={16} /></button>
          </div>
        </div>
        {data === null ? <p className="text-sm text-slate-400">Loading...</p>
          : !data.items.length ? <EmptyState title="Nothing here yet" text="Generated images and clips from every project appear here. Use Rebuild index if you added files by hand." icon={<LibraryIcon size={20} />} />
          : (
            <>
              <p className="mb-2 text-xs text-slate-400" aria-live="polite">{data.total} item{data.total === 1 ? "" : "s"}</p>
              <ul className={view === "grid" ? "grid gap-3 sm:grid-cols-2 xl:grid-cols-3" : "space-y-2"} data-testid="library-items">{data.items.map(view === "grid" ? card : row)}</ul>
              {data.items.length < data.total && <div className="mt-4 text-center"><Button variant="outline" onClick={() => setLimit((n) => n + LIMIT)}>Show more</Button></div>}
            </>
          )}
      </PageBody>
      {dialog}
    </div>
  );
}
