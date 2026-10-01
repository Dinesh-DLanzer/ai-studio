import { useCallback, useEffect, useState } from "react";
import { Link, Outlet, useOutletContext } from "react-router-dom";
import { api } from "../api";
import { Card, Button } from "../ui";
import { useProposal } from "../Proposal";
import BudgetDialog from "../BudgetDialog";
import TodoList from "../Todos";
import { VerifyProvider } from "../Verify";
import { Skeleton } from "../components/kit";
import type { TabProps } from "../ProjectPage";
import type { Overview, Todos } from "../types";
import Shell from "./Shell";
import NotFound from "../pages/NotFound";
import { useNavigate } from "react-router-dom";

/** Loads one project and provides it to every page under /p/:name (the screens read it with useProject()). */
export default function ProjectLayout({ name }: { name: string }) {
  const nav = useNavigate();
  const [o, setO] = useState<Overview | null>(null); const [err, setErr] = useState(""); const [todos, setTodos] = useState<Todos | null>(null); const [budgetOpen, setBudgetOpen] = useState(false);
  const load = useCallback(() => {
    api<Overview>("GET", `/api/projects/${name}`).then((x) => { setO(x); setErr(""); }).catch((e) => setErr(e.message));
    api<Todos>("GET", `/api/projects/${name}/todos`).then(setTodos).catch(() => {});
  }, [name]);
  useEffect(() => { load(); }, [load]);
  const { start, dialog, running } = useProposal(name, o?.mode || "real", load);
  if (err) return <Shell>{/no such project/i.test(err) ? <NotFound kind="project" name={name} onRestored={() => { setErr(""); setO(null); load(); }} /> : <Card title="Could not open the project"><p className="text-sm text-slate-400">{err}</p><Link to="/" className="mt-3 inline-block"><Button variant="outline">Back to all projects</Button></Link></Card>}</Shell>;
  if (!o) return <Shell><div className="space-y-4"><Skeleton className="h-16 w-72" /><Skeleton className="h-64" /><Skeleton className="h-72" /></div></Shell>;
  const shellProject = { name, test: !!(o as any).is_test, counts: { assets: o.images.images.length, shots: o.shots.shots.length }, spend: { total: o.costs.total, estimate: o.budget.estimate ?? null } };
  const ctx: TabProps = { todosDone: !!todos && [...todos.auto, ...todos.manual].every((t) => t.done), o, name, load, start, running, openBudget: () => setBudgetOpen(true), todoNode: <TodoList project={name} todos={todos} reload={load} go={(t) => nav(t === "overview" ? `/p/${name}` : `/p/${name}/${t === "story" ? "storyboard" : t}`)} /> };
  return (
    <VerifyProvider project={name} tick={o}>
      <Shell project={shellProject} onRenameProject={async (n) => { await api("POST", `/api/projects/${name}/rename`, { new: n }); nav(`/p/${n}`, { replace: true }); }}>
        {/* The project's accessible name. It is on screen in the top-bar breadcrumb and the sidebar switcher. */}
        <h1 className="sr-only">{name}</h1>
        <Outlet context={ctx} />
      </Shell>
      {dialog}
      <BudgetDialog project={name} open={budgetOpen} onClose={() => setBudgetOpen(false)} onDone={load} />
    </VerifyProvider>
  );
}
export const useProject = () => useOutletContext<TabProps>();
