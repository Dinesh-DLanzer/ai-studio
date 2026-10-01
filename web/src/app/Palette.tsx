import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Compass, FolderOpen, Lightbulb, Search, Settings as Cog } from "lucide-react";
import { api } from "../api";
import { Modal } from "../ui";
import { useToast } from "../toast";

interface Cmd { id: string; label: string; hint?: string; icon: JSX.Element; run: () => void | Promise<void>; }
const slug = (t: string) => t.toLowerCase().replace(/[^a-z0-9\s-]/g, " ").split(/\s+/).filter(Boolean).slice(0, 4).join("-").slice(0, 30) || "new-video";

/** ⌘K palette: jump to a page or project, or type an idea to start a new project (Tara, the producer, then interviews you in Chat). */
export default function Palette({ open, onClose, project }: { open: boolean; onClose: () => void; project?: string }) {
  const nav = useNavigate(); const toast = useToast();
  const [q, setQ] = useState(""); const [sel, setSel] = useState(0); const [projects, setProjects] = useState<string[]>([]);
  useEffect(() => { if (open) { setQ(""); setSel(0); api<{ projects: { name: string }[] }>("GET", "/api/projects").then((r) => setProjects(r.projects.map((p) => p.name))).catch(() => {}); } }, [open]);
  const go = (to: string) => () => { nav(to); onClose(); };
  const createFromIdea = async (idea: string) => {
    let name = slug(idea);
    for (let n = 0; n < 6; n++) {
      const tryName = n ? `${name}-${n + 1}` : name;
      try { await api("POST", "/api/projects", { name: tryName }); sessionStorage.setItem(`ai-studio-idea:${tryName}`, idea); toast("ok", `Created ${tryName}. Tara will start with your idea.`); nav(`/p/${tryName}/chat`); onClose(); return; }
      catch (e: any) { if (!/already exists/i.test(e.message)) return toast("error", e.message); }
    }
    toast("error", "Could not find a free project name; rename one and try again.");
  };
  const cmds = useMemo<Cmd[]>(() => {
    const base: Cmd[] = [{ id: "home", label: "All projects", icon: <FolderOpen size={16} />, run: go("/") }, { id: "settings", label: "AI Model Config", hint: "chat, verify, video models", icon: <Cog size={16} />, run: go("/settings") },
      { id: "help", label: "Help & Docs", icon: <Compass size={16} />, run: go("/help") }];
    const pages = project ? [["Overview", ""], ["Chat", "/chat"], ["Storyboard", "/storyboard"], ["Assets", "/assets"], ["Shots", "/shots"], ["Review & Export", "/review"], ["Costs", "/costs"], ["Discarded", "/discarded"]]
      .map(([l, s]) => ({ id: `page-${l}`, label: `Go to ${l}`, hint: project, icon: <Compass size={16} />, run: go(`/p/${project}${s}`) })) : [];
    const projs = projects.filter((n) => n !== project).map((n) => ({ id: `proj-${n}`, label: `Open project ${n}`, icon: <FolderOpen size={16} />, run: go(`/p/${n}`) }));
    const all = [...pages, ...base, ...projs];
    const t = q.trim().toLowerCase();
    const hits = t ? all.filter((c) => c.label.toLowerCase().includes(t)) : all;
    return t.length > 3 && !hits.some((c) => c.label.toLowerCase() === t) ? [{ id: "idea", label: `Start a new project: "${q.trim()}"`, hint: "Tara interviews you", icon: <Lightbulb size={16} />, run: () => createFromIdea(q.trim()) }, ...hits] : hits;
  }, [q, project, projects]); // eslint-disable-line
  useEffect(() => setSel(0), [q]);

  return (
    <Modal open={open} onClose={onClose} title="What do you want to do?">
      <div className="relative mb-3">
        <Search size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
        <input autoFocus aria-label="Command or idea" placeholder='Jump to a page, or describe your idea: "A 30s story about a tea seller"' value={q} onChange={(e) => setQ(e.target.value)}
          className="field !py-2.5 !pl-10"
          onKeyDown={(e) => { if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, cmds.length - 1)); } else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); } else if (e.key === "Enter") { e.preventDefault(); cmds[sel]?.run(); } }} />
      </div>
      <ul role="listbox" aria-label="Commands" className="max-h-72 overflow-auto">
        {cmds.map((c, i) => (
          <li key={c.id} role="option" aria-selected={i === sel}>
            <button type="button" onClick={() => c.run()} onMouseEnter={() => setSel(i)}
              className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition ${i === sel ? "bg-pink/15 text-white ring-1 ring-pink/40" : "hover:bg-slate-300/8"}`}>
              <span className="text-brand">{c.icon}</span><span className="min-w-0 flex-1 truncate">{c.label}</span>
              {c.hint && <span className="shrink-0 text-xs text-slate-400">{c.hint}</span>}
            </button>
          </li>))}
        {!cmds.length && <li className="p-3 text-sm text-slate-400">Nothing matches.</li>}
      </ul>
    </Modal>
  );
}
