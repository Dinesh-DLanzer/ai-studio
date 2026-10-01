import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import * as Menu from "@radix-ui/react-dropdown-menu";
import {
  ChevronDown, Clapperboard, Download, FlaskConical, Github, Star, Command as CmdIcon, Film, FolderOpen, HelpCircle, Home, Image as ImageIcon,
  LayoutGrid, Menu as MenuIcon, MessageCircle, Pencil, Plus, Search, Settings, Trash2, Wand2, Wallet, X,
} from "lucide-react";
import { api } from "../api";
import { RenameButton, RenameDialog } from "../Rename";
import { Donut, Logo, LogoMark, ProgressBar } from "../components/kit";
import { REPO_URL } from "../brand";
import Palette from "./Palette";
import Notifications from "./Notifications";
import NewProjectDialog from "./NewProject";
import { useToast } from "../toast";
import { deleteProject, downloadProjectZip } from "../projectActions";

export interface ShellProject { name: string; test?: boolean; counts: { assets: number; shots: number }; spend: { total: number; estimate?: number | null }; }

const money = (n?: number | null) => (n === undefined || n === null ? "-" : `$${n.toFixed(2)}`);

const NAV = [
  { key: "", label: "Overview", icon: Home },
  { key: "chat", label: "Chat", icon: MessageCircle },
  { key: "storyboard", label: "Storyboard", icon: LayoutGrid },
  { key: "assets", label: "Assets", icon: ImageIcon, count: "assets" as const },
  { key: "shots", label: "Shots", icon: Film, count: "shots" as const },
  { key: "review", label: "Review & Export", icon: Clapperboard },
  { key: "costs", label: "Costs", icon: Wallet },
  { key: "discarded", label: "Discarded", icon: Trash2 },
];

function ProjectSwitcher({ project, onRename }: { project: ShellProject; onRename?: (next: string) => Promise<void> }) {
  const nav = useNavigate(); const toast = useToast(); const [list, setList] = useState<{ name: string }[]>([]); const [renaming, setRenaming] = useState(false);
  const doDelete = async () => { try { if (await deleteProject(project.name)) { toast("ok", `${project.name} moved to the trash. You can restore it from the Projects page.`); nav("/"); } } catch (e: any) { toast("error", e.message); } };
  return (
    <>
      <Menu.Root onOpenChange={(o) => o && api<{ projects: { name: string }[] }>("GET", "/api/projects").then((r) => setList(r.projects)).catch(() => {})}>
        <Menu.Trigger className="switcher" aria-label={`Project ${project.name}, switch project`}>
          <span className="min-w-0">
            <span className="block truncate text-sm font-bold">{project.name}</span>
            {project.test && <span className="mt-1 inline-flex items-center gap-1 rounded-lg px-2 py-0.5 text-[0.65rem] font-bold uppercase tracking-wide tag-emerald">Test project</span>}
          </span>
          <ChevronDown size={16} className="shrink-0 text-slate-400" />
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content sideOffset={6} className="menu-surface">
            {list.map((p) => (
              <Menu.Item key={p.name} onSelect={() => nav(`/p/${p.name}`)} className={`menu-item ${p.name === project.name ? "text-brand" : ""}`}>
                <FolderOpen size={14} />{p.name}
              </Menu.Item>
            ))}
            <Menu.Separator className="my-1 h-px bg-slate-800" />
            <Menu.Item onSelect={() => nav("/")} className="menu-item"><LayoutGrid size={14} />All projects</Menu.Item>
            <Menu.Item onSelect={() => nav("/?new=1")} className="menu-item"><Plus size={14} />New project</Menu.Item>
            {onRename && (
              <>
                <Menu.Separator className="my-1 h-px bg-slate-800" />
                <Menu.Item onSelect={() => setTimeout(() => setRenaming(true), 0)} className="menu-item"><Pencil size={14} />Rename project</Menu.Item>
              </>
            )}
            <Menu.Separator className="my-1 h-px bg-slate-800" />
            <Menu.Item onSelect={() => downloadProjectZip(project.name)} className="menu-item"><Download size={14} />Export project (zip)</Menu.Item>
            <Menu.Item onSelect={() => setTimeout(doDelete, 0)} className="menu-item !text-red-300"><Trash2 size={14} />Delete project...</Menu.Item>
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
      {onRename && <RenameDialog open={renaming} onClose={() => setRenaming(false)} kind="project" current={project.name}
        explain="The project folder is renamed. Everything inside it keeps working; bookmarks to the old name stop working."
        onRename={onRename} />}
    </>
  );
}

function NavItem({ to, icon, label, count, end, onNavigate }: { to: string; icon: ReactNode; label: string; count?: number; end?: boolean; onNavigate?: () => void }) {
  return (
    <NavLink to={to} end={end} onClick={onNavigate} className={({ isActive }) => `nav-link ${isActive ? "is-active" : ""}`}>
      {icon}<span className="flex-1 truncate">{label}</span>
      {count !== undefined && <span className="nav-count">{count}</span>}
    </NavLink>
  );
}

/** The spend meter at the foot of the sidebar: donut, amounts, and a gradient bar. */
function SpendCard({ project }: { project: ShellProject }) {
  const est = project.spend.estimate;
  const pct = est ? Math.round((project.spend.total / est) * 100) : 0;
  return (
    <div className="meter-card">
      <div className="mb-2 text-[0.68rem] font-bold uppercase tracking-[0.12em] text-slate-400">Spend</div>
      <div className="flex items-center gap-3">
        <Donut value={project.spend.total} max={est || project.spend.total || 1} size={50} label="Spend compared with the budget" />
        <div className="min-w-0">
          <div className="text-base font-extrabold leading-none">{money(project.spend.total)} <span className="text-xs font-medium text-slate-400">/ {money(est)}</span></div>
          <div className="mt-1.5 w-24"><ProgressBar value={pct} label="Budget used" /></div>
          <div className="mt-1 text-[0.68rem] text-slate-400">{est ? `${pct}% of budget` : "no budget yet"}</div>
        </div>
      </div>
    </div>
  );
}

function SidebarBody({ project, onNavigate, onRenameProject }: { project?: ShellProject; onNavigate?: () => void; onRenameProject?: (next: string) => Promise<void> }) {
  const base = project ? `/p/${project.name}` : "";
  return (
    <div className="flex h-full flex-col gap-3">
      <Link to="/" onClick={onNavigate} aria-label="AI Studio home" className="mb-1 block"><Logo /></Link>
      {project
        ? (
          <div className="flex items-start gap-1.5">
            <div className="min-w-0 flex-1">
              <ProjectSwitcher project={project} onRename={onRenameProject} />
            </div>
            {onRenameProject && (
              <RenameButton kind="project" current={project.name}
                explain="The project folder is renamed. Everything inside it keeps working; bookmarks to the old name stop working."
                onRename={onRenameProject} />
            )}
          </div>
        )
        : <NavItem to="/" end icon={<LayoutGrid size={17} />} label="All projects" onNavigate={onNavigate} />}
      {project && (
        <nav aria-label="Project" className="flex flex-col gap-1">
          {NAV.map((n) => {
            const Icon = n.icon;
            return (
              <NavItem key={n.key} to={`${base}${n.key ? `/${n.key}` : ""}`} end={!n.key}
                icon={<Icon size={17} />} label={n.label}
                count={n.count ? project.counts[n.count] : undefined} onNavigate={onNavigate} />
            );
          })}
          {project.test && (
            <Link to="/settings" onClick={onNavigate} data-testid="mode-label" title="A test project: nothing real was generated in it (simulated images and clips, no cost)."
              className="mt-1 inline-flex items-center justify-center gap-1.5 rounded-xl border border-sky/40 bg-sky/10 px-3 py-2 text-xs font-bold uppercase tracking-wide text-sky transition hover:bg-sky/20">
              <FlaskConical size={14} />Test Project
            </Link>
          )}
        </nav>
      )}
      <div className="mt-auto flex flex-col gap-3 pt-4">
        {project && <SpendCard project={project} />}
        <nav aria-label="Workspace" className="flex flex-col gap-1">
          <NavItem to="/help" icon={<HelpCircle size={17} />} label="Help &amp; Docs" onNavigate={onNavigate} />
          <NavItem to="/settings" icon={<Settings size={17} />} label="Settings" onNavigate={onNavigate} />
        </nav>
        <div className="user-card">
          <span className="avatar" aria-hidden>AI</span>
          <div className="min-w-0 leading-tight">
            <div className="truncate text-sm font-bold">Local workspace</div>
            <div className="truncate text-[0.68rem] text-slate-400">Runs on this computer</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function TopBar({ project, openMenu, openPalette }: { project?: ShellProject; openMenu: () => void; openPalette: () => void }) {
  const loc = useLocation();
  const [newOpen, setNewOpen] = useState(false);

  // The search box doubles as a breadcrumb on a project page.
  const crumb = (loc.pathname.split("/").filter(Boolean)[2] || "").toLowerCase();
  const current = crumb[0] ? crumb[0].toUpperCase() + crumb.slice(1) : "Overview";
  const HINTS: Record<string, string> = {
    "": "Turn your idea into an AI video...",
    chat: "Describe your idea or answer a question...",
    storyboard: "Search the script, scenes and prompts...",
    assets: "Search assets (characters, backgrounds, uploads)...",
    shots: "Search projects, scenes, or models...",
    review: "Edit, trim, add text and export your video...",
    costs: "Search projects, scenes, or models...",
    discarded: "Search discarded items (scenes, shots, assets, videos)...",
  };
  const placeholder = HINTS[crumb] || "Describe your idea... e.g. \"A 30s story about a tea seller\"";

  return (
    <header className="topbar">
      <button type="button" className="icon-btn lg:hidden" onClick={openMenu} aria-label="Open menu"><MenuIcon size={18} /></button>
      {project
        ? <Link to="/" className="lg:hidden" aria-label="AI Studio home"><LogoMark size={30} /></Link>
        : <Link to="/" aria-label="AI Studio home" className="shrink-0"><span className="lg:hidden"><LogoMark size={30} /></span><span className="hidden lg:block"><Logo /></span></Link>}

      <button type="button" onClick={openPalette} aria-label="Open command palette" className="omni max-w-3xl">
        <Search size={16} className="hidden shrink-0 text-slate-400 sm:block" />
        {/* The breadcrumb is plain text: the whole box is one button, so it must hold no focusable children. */}
        {project && <span className="hidden shrink-0 items-center gap-1.5 text-xs font-semibold text-slate-300 sm:flex">
          <LayoutGrid size={13} />
          <span>{current}</span>
          <span className="text-slate-400">/</span>
          <span className="text-slate-400">{project.name}</span>
        </span>}
        <span className="omni-label">{placeholder}</span>
        <kbd className="kbd shrink-0"><CmdIcon size={11} />K</kbd>
      </button>

      <div className="ml-auto flex items-center gap-2">
        <a href={REPO_URL} target="_blank" rel="noreferrer" aria-label="Star AI Studio on GitHub" title="Star AI Studio on GitHub"
          className="hidden items-center gap-2 rounded-xl border border-slate-800 bg-slate-900 px-3.5 py-2 text-sm font-semibold text-slate-100 transition hover:border-slate-700 hover:bg-slate-300/10 md:flex">
          <Github size={16} />Star<Star size={13} className="text-amber-300" fill="currentColor" />
        </a>
        <button type="button" onClick={() => setNewOpen(true)} className="btn btn-lime hidden sm:inline-flex">
          <Wand2 size={15} />Generate New Video<ChevronDown size={14} className="-rotate-90" />
        </button>
        <NewProjectDialog open={newOpen} onClose={() => setNewOpen(false)} />
        {!project && (
          <>
            <NavLink to="/help" className="icon-btn" aria-label="Help &amp; Docs" title="Help &amp; Docs"><HelpCircle size={17} /></NavLink>
            <NavLink to="/settings" className="icon-btn" aria-label="Settings" title="Settings"><Settings size={17} /></NavLink>
          </>
        )}
        <Notifications />
        <span className="avatar" aria-hidden>AI</span>
      </div>
    </header>
  );
}

export default function Shell({ project, children, rail, onRenameProject }: {
  project?: ShellProject; children: ReactNode; rail?: ReactNode; onRenameProject?: (next: string) => Promise<void>;
}) {
  const [drawer, setDrawer] = useState(false); const [palette, setPalette] = useState(false);
  useEffect(() => {
    const f = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette(true); } };
    addEventListener("keydown", f); return () => removeEventListener("keydown", f);
  }, []);
  return (
    <div className={`app-shell ${project ? "lg:grid lg:grid-cols-[var(--side-w)_minmax(0,1fr)]" : ""}`}>
      {/* Only a project has a sidebar; the project list, Settings and Help use the full width. */}
      {project && (
        <aside className="sidebar hidden lg:block" aria-label="Sidebar">
          <SidebarBody project={project} onRenameProject={onRenameProject} />
        </aside>
      )}

      <Dialog.Root open={drawer} onOpenChange={setDrawer}>
        <Dialog.Portal>
          <Dialog.Overlay className="scrim lg:hidden" />
          <Dialog.Content aria-describedby={undefined} className="fixed inset-y-0 left-0 z-50 w-[min(19rem,86vw)] overflow-y-auto border-r border-slate-800 bg-slate-950 p-4 lg:hidden">
            <Dialog.Title className="sr-only">Menu</Dialog.Title>
            <Dialog.Close className="icon-btn absolute right-3 top-3" aria-label="Close menu"><X size={16} /></Dialog.Close>
            <SidebarBody project={project} onNavigate={() => setDrawer(false)} onRenameProject={onRenameProject} />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <div className="min-w-0">
        <TopBar project={project} openMenu={() => setDrawer(true)} openPalette={() => setPalette(true)} />
        <main className="mx-auto w-full max-w-none p-3 md:p-4 lg:px-4">
          {rail ? <div className="page-grid"><div className="min-w-0">{children}</div><aside className="rail" aria-label="Details">{rail}</aside></div> : children}
        </main>
      </div>

      <Palette open={palette} onClose={() => setPalette(false)} project={project?.name} />
    </div>
  );
}

/** Two-column page body: main content on the left, rail on the right. */
export const PageBody = ({ children, rail, stickyMain, stickyRail }: { children: ReactNode; rail?: ReactNode; stickyMain?: boolean | "auto"; stickyRail?: boolean }) =>
  rail ? (
    <div className="page-grid">
      <div className={`min-w-0 ${stickyMain === "auto" ? "xl:sticky xl:top-[4.75rem] xl:max-h-[calc(100vh-5.75rem)] xl:overflow-y-auto" : stickyMain ? "xl:sticky xl:top-[4.75rem] xl:h-[calc(100vh-5.75rem)]" : ""}`}>{children}</div>
      {/* One element, so the rail cards stack in a single column instead of becoming separate grid items. */}
      <aside className={`rail ${stickyRail ? "xl:sticky xl:top-[4.75rem] xl:max-h-[calc(100vh-5.75rem)] xl:overflow-y-auto" : ""}`} aria-label="Details">{rail}</aside>
    </div>
  ) : <div className="min-w-0">{children}</div>;
