import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import * as Menu from "@radix-ui/react-dropdown-menu";
import { Download, Film, FolderArchive, Image as ImageIcon, LayoutGrid, MoreHorizontal, Plus, RotateCcw, Sparkles, Star, Trash2 } from "lucide-react";
import { api, fileUrl } from "../api";
import { Badge, Button, Input, PageHeader, money } from "../ui";
import { EmptyState, ProgressBar } from "../components/kit";
import type { ProjectRow } from "../types";
import { useToast } from "../toast";
import { deleteProject, downloadProjectZip } from "../projectActions";
import ImportProject from "../app/ImportProject";
import { useSetupNeeded } from "../app/setupContext";

type Filter = "all" | "recent" | "favorites" | "archived";

/** A project card: cover image, duration, title, meta, tags and the budget state. */
function ProjectCard({ p, onOpen, onDelete, onFavorite }: { p: ProjectRow & { cover?: string; seconds?: number; tags?: string[]; model?: string; updated?: string }; onOpen: () => void; onDelete: () => void; onFavorite: () => void }) {
  const [broken, setBroken] = useState(false);
  return (
    <div className="relative">
    <button type="button" onClick={onOpen} className="group panel panel-lit h-full w-full overflow-hidden text-left transition hover:border-pink/50">
      <div className="relative aspect-video overflow-hidden bg-slate-900">
        {p.cover && !broken
          ? <img src={p.cover} alt="" onError={() => setBroken(true)} className="h-full w-full object-cover transition duration-500 group-hover:scale-105" loading="lazy" />
          : <div className="grid h-full place-items-center bg-gradient-to-br from-pink/20 via-violet/10 to-brand/10"><Sparkles size={26} className="text-slate-500" /></div>}
        <div className="absolute inset-x-0 top-0 flex items-start justify-between p-2.5">
          <span className="flex items-center gap-1.5">{p.test && <span className="rounded-md bg-sky/90 px-2 py-0.5 text-[0.65rem] font-extrabold uppercase tracking-wider text-slate-950" data-testid="test-badge" title="Test pipeline project: simulated images and clips, costs nothing">Test</span>}</span>
          {p.seconds ? <span className="thumb-badge !bottom-2.5 !right-2.5 !top-auto">{p.seconds}s</span> : null}
        </div>
      </div>
      <div className="p-3.5">
        <div className="flex items-center gap-1.5 text-[0.95rem] font-bold"><span className="truncate">{p.name}</span>{p.favorite && <Star size={14} className="shrink-0 fill-amber-300 text-amber-300" aria-label="Favorite" />}</div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-200" data-testid="card-counts">
          <span className="inline-flex items-center gap-1.5 rounded-lg bg-white/[.06] px-2 py-1"><ImageIcon size={13} className="text-pink" />{p.assets ?? 0} assets</span>
          <span className="inline-flex items-center gap-1.5 rounded-lg bg-white/[.06] px-2 py-1"><Film size={13} className="text-violet" />{p.shots} shots</span>
        </div>
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          {(p.tags || ["Video", "Tamil"]).map((t, i) => <span key={t} className={`tag ${i === 0 ? "tag-grad" : ""}`}>{t}</span>)}
          <span className="ml-auto"><Badge tone={p.approved ? "green" : "amber"}>{p.approved ? "Completed" : "no budget"}</Badge></span>
        </div>
        {p.estimate ? (
          <div className="mt-3">
            <ProgressBar value={p.spent} max={p.estimate} label={`${p.name} budget used`} />
            <div className="mt-1 text-[0.68rem] text-slate-400">{money(p.spent)} spent of {money(p.estimate)}</div>
          </div>
        ) : (
          <div className="mt-3 text-[0.68rem] text-slate-400">spent {money(p.spent)}</div>
        )}
      </div>
    </button>
    <Menu.Root>
      <Menu.Trigger className="icon-btn absolute right-2.5 top-2.5 !bg-black/60 backdrop-blur" aria-label={`Actions for ${p.name}`}><MoreHorizontal size={16} /></Menu.Trigger>
      <Menu.Portal>
        <Menu.Content align="end" sideOffset={6} className="menu-surface">
          <Menu.Item className="menu-item" onSelect={onFavorite}><Star size={14} className={p.favorite ? "fill-amber-300 text-amber-300" : ""} />{p.favorite ? "Remove from favorites" : "Add to favorites"}</Menu.Item>
          <Menu.Separator className="my-1 h-px bg-slate-800" />
          <Menu.Item className="menu-item" onSelect={() => downloadProjectZip(p.name)}><FolderArchive size={14} />Export project (zip)</Menu.Item>
          <Menu.Item className="menu-item" onSelect={() => downloadProjectZip(p.name, true)}><Download size={14} />Export with discarded files</Menu.Item>
          <Menu.Separator className="my-1 h-px bg-slate-800" />
          <Menu.Item className="menu-item !text-red-300" onSelect={() => setTimeout(onDelete, 0)}><Trash2 size={14} />Delete project...</Menu.Item>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
    </div>
  );
}

export default function Projects() {
  const noProvider = useSetupNeeded();
  const nav = useNavigate(); const [sp] = useSearchParams(); const toast = useToast();
  const [loaded, setLoaded] = useState(false);
  const [trash, setTrash] = useState<{ id: string; name: string; when: string; files: number }[]>([]);
  const [rows, setRows] = useState<ProjectRow[]>([]);
  const [name, setName] = useState(""); const [err, setErr] = useState(""); const [testPipe, setTestPipe] = useState(false);
  const [filter, setFilter] = useState<Filter>("all"); const [q, setQ] = useState("");
  // A cover per project: the first still the project has on disk. Cheap enough to fan out here.
  const [covers, setCovers] = useState<Record<string, { cover: string; seconds: number; tags: string[] }>>({});

  const loadTrash = useCallback(() => api<{ items: { id: string; name: string; when: string; files: number }[] }>("GET", "/api/trash").then((r) => setTrash(r.items)).catch(() => {}), []);
  const load = useCallback(async () => {
    loadTrash();
    const r = await api<{ projects: ProjectRow[] }>("GET", "/api/projects");
    setRows(r.projects); setLoaded(true);
    const entries = await Promise.all(r.projects.map(async (p) => {
      try {
        const o = await api<any>("GET", `/api/projects/${p.name}`);
        const ff = (o.files.stills as string[]).find((f) => /\.(png|jpe?g|webp)$/i.test(f));
        const shot = o.shots.shots[0];
        const tags = [...new Set([...(o.images?.images || []).slice(0, 1).map((i: any) => i.kind), "Tamil"])].map(String);
        return [p.name, { cover: ff ? fileUrl(p.name, `stills/${ff}`) : "", seconds: shot?.seconds ?? 0, tags }] as const;
      } catch { return [p.name, { cover: "", seconds: 0, tags: [] }] as const; }
    }));
    setCovers(Object.fromEntries(entries));
  }, [loadTrash]);

  useEffect(() => { load().catch(() => {}); }, [load]);
  useEffect(() => { if (sp.get("new") === "1") document.getElementById("new-project-name")?.focus(); }, [sp]);

  const remove = async (n: string) => {
    try { if (await deleteProject(n)) { toast("ok", `${n} moved to the trash. Find it in the Archived tab to restore it.`); await load(); } }
    catch (e: any) { toast("error", e.message); }
  };
  const favorite = async (n: string, on: boolean) => {
    try { await api("POST", `/api/projects/${encodeURIComponent(n)}/favorite`, { on }); setRows((r) => r.map((x) => (x.name === n ? { ...x, favorite: on } : x))); toast("ok", on ? `${n} added to favorites.` : `${n} removed from favorites.`); }
    catch (e: any) { toast("error", e.message); }
  };
  const restore = async (id: string) => {
    try {
      let r: { name: string } | null = null;
      try { r = await api("POST", `/api/trash/${id}/restore`, {}); }
      catch (e: any) {
        if (!/already exists/i.test(e.message)) throw e;
        const base = id.split("__")[0]; let k = 2; while (rows.some((x) => x.name === `${base}-restored${k > 2 ? k : ""}`)) k++;
        r = await api("POST", `/api/trash/${id}/restore`, { as_name: `${base}-restored${k > 2 ? k : ""}` });
      }
      toast("ok", `Restored as ${r!.name}.`); await load();
    } catch (e: any) { toast("error", e.message); }
  };

  const create = async () => {
    const n = name.trim(); if (!n) return;
    try { await api("POST", "/api/projects", { name: n, test_pipeline: testPipe || noProvider }); nav(`/p/${n}/chat`); }
    catch (e: any) { setErr(e.message); }
  };

  const counts = useMemo(() => ({
    all: rows.length,
    recent: rows.length,
    favorites: rows.filter((r) => r.favorite).length,
    archived: trash.length,
  }), [rows, trash]);

  const archivedShown = useMemo(() => { const t = q.trim().toLowerCase(); return t ? trash.filter((x) => x.name.toLowerCase().includes(t)) : trash; }, [trash, q]);
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    const list = t ? rows.filter((p) => p.name.toLowerCase().includes(t)) : rows;
    if (filter === "recent") return [...list].reverse();
    if (filter === "favorites") return list.filter((r) => r.favorite);
    return list;
  }, [rows, q, filter]);

  const FILTERS: { id: Filter; label: string; icon: typeof Sparkles }[] = [
    { id: "all", label: "All Projects", icon: LayoutGrid },
    { id: "recent", label: "Recent", icon: Sparkles },
    { id: "favorites", label: "Favorites", icon: Sparkles },
    { id: "archived", label: "Archived", icon: Sparkles },
  ];

  return (
    <div className="animate-fade-up space-y-5">
      <PageHeader
        title="Your" accent="Projects"
        sub="Create, manage and generate AI videos from your ideas."
        right={
          <div className="flex w-full items-center gap-2 sm:w-auto">
            <div className="relative min-w-0 flex-1 sm:w-56 sm:flex-none">
              <input className="field !rounded-xl !py-2 !pl-9" placeholder="Search projects..." aria-label="Search projects" value={q} onChange={(e) => setQ(e.target.value)} />
              <Sparkles size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            </div>
          </div>
        }
      />

      {/* The promo banner: what the app does, in one line. */}
      <div className="panel panel-lit relative overflow-hidden p-5">
        <div className="pointer-events-none absolute -right-16 -top-24 h-64 w-64 rounded-full bg-pink/25 blur-3xl" aria-hidden />
        <div className="pointer-events-none absolute right-40 top-10 h-40 w-40 rounded-full bg-violet/20 blur-3xl" aria-hidden />
        <div className="relative max-w-md">
          <div className="text-lg font-extrabold leading-tight">Turn your ideas into <span className="grad-text">AI videos</span></div>
          <p className="mt-1.5 text-xs text-slate-300">Chat → storyboard → generate → share</p>
        </div>
      </div>

      {/* Filter chips with counts. */}
      <div role="tablist" aria-label="Project filters" className="flex flex-wrap gap-2">
        {FILTERS.map((f) => {
          const Icon = f.icon;
          return (
            <button key={f.id} type="button" role="tab" aria-selected={filter === f.id} onClick={() => setFilter(f.id)} className="pill">
              <Icon size={14} />{f.label}
              <span className={`rounded-full px-1.5 text-[0.68rem] ${filter === f.id ? "bg-black/25" : "bg-white/7"}`}>{counts[f.id]}</span>
            </button>
          );
        })}
      </div>

      {filter !== "archived" && shown.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {/* New project: the create form lives here, as the first grid item. */}
          <div className="panel panel-lit flex flex-col items-center justify-center gap-3 border-dashed p-6 text-center">
            <span className="grid h-12 w-12 place-items-center rounded-full border border-slate-800 bg-slate-300/10 text-slate-300"><Plus size={22} /></span>
            <div>
              <div className="text-sm font-bold">Create New Project</div>
              <div className="mt-1 text-xs text-slate-400">Start a new AI video</div>
            </div>
            <form className="w-full space-y-2" onSubmit={(e) => { e.preventDefault(); create(); }}>
              <Input id="new-project-name" aria-label="New project name" placeholder="project-name (letters, numbers, - _)" value={name}
                onChange={(e) => { setName(e.target.value); setErr(""); }} />
              <label className="flex cursor-pointer items-start gap-2.5 rounded-xl border border-slate-800 bg-white/[.02] p-2.5 text-left">
                <input type="checkbox" role="switch" className="mt-0.5 h-4 w-4 shrink-0 accent-[#d7ff3f]" checked={testPipe || noProvider} onChange={(e) => setTestPipe(e.target.checked)} aria-label="Test project" disabled={noProvider} />
                <span className="min-w-0 text-xs">
                  <span className="block font-bold text-slate-100">Test project (free){noProvider ? " - no provider connected yet" : ""}</span>
                  <span className="mt-0.5 block text-slate-400">Images, clips and reviews are simulated, so it costs nothing. The chat uses your AI provider once you connect one.</span>
                </span>
              </label>
              {err && <p className="text-xs text-red-400" role="alert">{err}</p>}
              <Button type="submit" className="w-full" disabled={!name.trim()}><Plus size={16} />Create</Button>
            </form>
            <ImportProject />
          </div>
          {shown.map((p) => (
            <ProjectCard key={p.name} p={{ ...p, ...covers[p.name] }} onOpen={() => nav(`/p/${p.name}`)} onDelete={() => remove(p.name)} onFavorite={() => favorite(p.name, !p.favorite)} />
          ))}
        </div>
      )}

      {filter !== "archived" && !shown.length && rows.length > 0 && (
        <EmptyState title="Nothing matches that filter" text="Try another search or switch back to All Projects." icon={<Sparkles size={20} />} />
      )}

      {/* No projects at all: a welcome panel with the create form and the import button. */}
      {filter !== "archived" && loaded && rows.length === 0 && (
        <div className="panel panel-lit mx-auto w-full max-w-xl p-6 text-center sm:p-8" data-testid="first-project">
          <span className="mx-auto grid h-14 w-14 place-items-center rounded-full border border-pink/40 bg-pink/10 text-pink"><Sparkles size={24} /></span>
          <h2 className="mt-4 text-2xl font-extrabold tracking-tight">No projects yet</h2>
          <p className="mx-auto mt-1.5 max-w-sm text-sm text-slate-400">Every video is its own project. Name your first one, then describe your idea in the chat. Or import a project zip from another computer.</p>
          <ol className="mx-auto mt-4 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-xs text-slate-300" aria-label="How it works">
            {["Chat", "Storyboard", "Generate", "Review & Export"].map((x, i) => <li key={x} className="inline-flex items-center gap-2">{i > 0 && <span className="text-slate-500" aria-hidden>→</span>}<span className="rounded-full border border-slate-800 bg-white/[.03] px-2.5 py-1">{x}</span></li>)}
          </ol>
          <form className="mt-5 space-y-2 text-left" onSubmit={(e) => { e.preventDefault(); create(); }}>
            <Input aria-label="New project name" placeholder="project-name (letters, numbers, - _)" value={name} onChange={(e) => { setName(e.target.value); setErr(""); }} />
            <label className="flex cursor-pointer items-start gap-2.5 rounded-xl border border-slate-800 bg-white/[.02] p-2.5">
              <input type="checkbox" role="switch" className="mt-0.5 h-4 w-4 shrink-0 accent-[#d7ff3f]" checked={testPipe || noProvider} onChange={(e) => setTestPipe(e.target.checked)} aria-label="Test project" disabled={noProvider} />
              <span className="min-w-0 text-xs"><span className="block font-bold text-slate-100">Test project (free){noProvider ? " - no provider connected yet" : ""}</span><span className="mt-0.5 block text-slate-400">Images, clips and reviews are simulated, so it costs nothing. Good for a first try.</span></span>
            </label>
            {err && <p className="text-xs text-red-400" role="alert">{err}</p>}
            <Button type="submit" className="w-full" disabled={!name.trim()}><Plus size={16} />Create project</Button>
          </form>
          <div className="my-3 flex items-center gap-3 text-[0.7rem] uppercase tracking-wider text-slate-400"><span className="h-px flex-1 bg-slate-800" />or<span className="h-px flex-1 bg-slate-800" /></div>
          <ImportProject />
        </div>
      )}

      {/* Archived = deleted projects. They are moved to the trash folder, never erased, and can be restored here. */}
      {filter === "archived" && archivedShown.length === 0 && (
        <EmptyState title={q.trim() && trash.length ? "No archived project matches" : "Nothing archived"} text="Deleted projects appear here and can be restored." icon={<Trash2 size={20} />} />
      )}
      {filter === "archived" && archivedShown.length > 0 && (
        <section className="panel panel-lit panel-pad" aria-label="Archived projects" data-testid="trash">
          <div className="panel-head"><div><h3 className="panel-title">Archived projects</h3><p className="panel-sub">Deleted projects are kept in the trash folder until you remove them yourself. Restore one to use it again.</p></div></div>
          <ul className="divide-y divide-slate-800">
            {archivedShown.map((t) => (
              <li key={t.id} className="flex items-center gap-3 py-2.5 text-sm">
                <Trash2 size={15} className="shrink-0 text-slate-400" /><span className="min-w-0 flex-1 truncate font-semibold">{t.name}</span>
                <span className="hidden text-xs text-slate-400 sm:block">{t.files} files · {t.when.replace("T", " ")}</span>
                <Button variant="outline" size="sm" aria-label={`Restore ${t.name}`} onClick={() => restore(t.id)}><RotateCcw size={13} />Restore</Button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
