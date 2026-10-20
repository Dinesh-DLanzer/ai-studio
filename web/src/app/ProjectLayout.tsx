import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Link, Outlet, useOutletContext } from "react-router-dom";
import { api, getToken } from "../api";
import { Card, Button } from "../ui";
import { useProposal, runKey, Spinner, type Running } from "../Proposal";
import BudgetDialog from "../BudgetDialog";
import TodoList from "../Todos";
import { VerifyProvider } from "../Verify";
import { Skeleton } from "../components/kit";
import { useToast } from "../toast";
import { notifyDone, notifyStart } from "../notify";
import type { TabProps } from "../ProjectPage";
import type { Overview, Todos, ActivityJob } from "../types";
import Shell from "./Shell";
import NotFound from "../pages/NotFound";
import { useNavigate } from "react-router-dom";

/** Loads one project and provides it to every page under /p/:name (the screens read it with useProject()). */
export default function ProjectLayout({ name }: { name: string }) {
  const nav = useNavigate();
  const toast = useToast();
  const [o, setO] = useState<Overview | null>(null);
  const [err, setErr] = useState("");
  const [todos, setTodos] = useState<Todos | null>(null);
  const [budgetOpen, setBudgetOpen] = useState(false);
  const [mcpRunning, setMcpRunning] = useState<Running>({});
  const [activeJobsList, setActiveJobsList] = useState<ActivityJob[]>([]);

  const activeNoticeIds = useRef<Record<string, string>>({});
  const prevStatuses = useRef<Record<string, string>>({});

  const handleActivity = useCallback((items: ActivityJob[]) => {
    const runningMap: Running = {};
    const runningList: ActivityJob[] = [];

    for (const job of items) {
      const prevStatus = prevStatuses.current[job.id];
      const isRunning = job.status === "running";

      if (isRunning) {
        const key = runKey(job.kind, job.target);
        runningMap[key] = job.kind;
        runningList.push(job);

        if (!activeNoticeIds.current[job.id]) {
          const label =
            job.kind === "image"
              ? "Generating image"
              : job.kind === "clip"
              ? "Generating video clip"
              : "Reviewing clip";
          const nid = notifyStart(
            `${label} ${job.target}`,
            `${job.model} · $${Number(job.price || 0).toFixed(3)} (live process)`,
            { project: name, to: `/p/${name}/${job.kind === "image" ? "assets" : "shots"}` }
          );
          activeNoticeIds.current[job.id] = nid;
          toast("info", `Live AI process: ${label} ${job.target} (${job.model})...`);
        }
      } else if (prevStatus === "running" && job.status === "done") {
        const nid = activeNoticeIds.current[job.id];
        const resMsg = job.result?.file
          ? `Done: ${job.result.file} ($${Number(job.result.cost ?? job.price).toFixed(3)})`
          : "Done.";
        if (nid) {
          notifyDone(nid, "ok", resMsg);
          delete activeNoticeIds.current[job.id];
        }
        toast("ok", `${job.kind} ${job.target}: ${resMsg}`);
        api<Overview>("GET", `/api/projects/${name}`).then((x) => { setO(x); setErr(""); }).catch(() => {});
      } else if (prevStatus === "running" && (job.status === "error" || job.status === "timeout")) {
        const nid = activeNoticeIds.current[job.id];
        const errMsg = job.error || "Generation failed";
        if (nid) {
          notifyDone(nid, "error", errMsg);
          delete activeNoticeIds.current[job.id];
        }
        toast("error", `${job.kind} ${job.target} failed: ${errMsg}`);
        api<Overview>("GET", `/api/projects/${name}`).then((x) => { setO(x); setErr(""); }).catch(() => {});
      }

      prevStatuses.current[job.id] = job.status;
    }

    setMcpRunning(runningMap);
    setActiveJobsList(runningList);
  }, [name, toast]);

  const load = useCallback(() => {
    api<Overview>("GET", `/api/projects/${name}`)
      .then((x) => {
        setO(x);
        setErr("");
        if (x.activity) handleActivity(x.activity);
      })
      .catch((e) => setErr(e.message));
    api<Todos>("GET", `/api/projects/${name}/todos`).then(setTodos).catch(() => {});
  }, [name, handleActivity]);

  useEffect(() => {
    load();
  }, [load]);

  // Live SSE event stream & fallback polling
  useEffect(() => {
    let es: EventSource | null = null;
    let pollTimer: any = null;

    const checkActivity = () => {
      api<{ activity: ActivityJob[] }>("GET", `/api/projects/${name}/activity`)
        .then((r) => {
          if (r?.activity) handleActivity(r.activity);
        })
        .catch(() => {});
    };

    checkActivity();
    pollTimer = setInterval(checkActivity, 2000);

    try {
      const token = getToken();
      const sseUrl = `/api/projects/${encodeURIComponent(name)}/events${token ? `?token=${encodeURIComponent(token)}` : ""}`;
      es = new EventSource(sseUrl);

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "activity" && Array.isArray(data.activity)) {
            handleActivity(data.activity);
          } else if (data.type === "refresh") {
            api<Overview>("GET", `/api/projects/${name}`).then((x) => { setO(x); setErr(""); }).catch(() => {});
          }
        } catch {}
      };

      es.onerror = () => {
        // Fallback polling keeps state up to date
      };
    } catch {}

    return () => {
      if (es) es.close();
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [name, handleActivity]);

  const { start, dialog, running } = useProposal(name, o?.mode || "real", load);

  const combinedRunning = { ...running, ...mcpRunning };

  if (err) return <Shell>{/no such project/i.test(err) ? <NotFound kind="project" name={name} onRestored={() => { setErr(""); setO(null); load(); }} /> : <Card title="Could not open the project"><p className="text-sm text-slate-400">{err}</p><Link to="/" className="mt-3 inline-block"><Button variant="outline">Back to all projects</Button></Link></Card>}</Shell>;
  if (!o) return <Shell><div className="space-y-4"><Skeleton className="h-16 w-72" /><Skeleton className="h-64" /><Skeleton className="h-72" /></div></Shell>;
  const shellProject = { name, test: !!(o as any).is_test, counts: { assets: o.images.images.length, shots: o.shots.shots.length }, spend: { total: o.costs.total, estimate: o.budget.estimate ?? null } };
  const ctx: TabProps = { todosDone: !!todos && [...todos.auto, ...todos.manual].every((t) => t.done), o, name, load, start, running: combinedRunning, openBudget: () => setBudgetOpen(true), todoNode: <TodoList project={name} todos={todos} reload={load} go={(t) => nav(t === "overview" ? `/p/${name}` : `/p/${name}/${t === "story" ? "storyboard" : t}`)} /> };

  return (
    <VerifyProvider project={name} tick={o}>
      <Shell project={shellProject} onRenameProject={async (n) => { await api("POST", `/api/projects/${name}/rename`, { new: n }); nav(`/p/${n}`, { replace: true }); }}>
        {/* The project's accessible name. It is on screen in the top-bar breadcrumb and the sidebar switcher. */}
        <h1 className="sr-only">{name}</h1>

        {/* Live process banner when MCP or AI is actively generating in background */}
        {activeJobsList.length > 0 && (
          <div className="mb-4 flex flex-col gap-2 animate-fade-in">
            {activeJobsList.map((job) => (
              <div
                key={job.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-sky-500/40 bg-gradient-to-r from-sky-950/70 via-purple-950/40 to-slate-900/80 px-4 py-2.5 text-xs text-sky-100 shadow-card animate-pulse"
              >
                <div className="flex items-center gap-2.5">
                  <span className="grid h-6 w-6 place-items-center rounded-lg bg-sky-500/20 text-sky-300">
                    <Spinner size={14} />
                  </span>
                  <div>
                    <span className="font-extrabold uppercase tracking-wider text-sky-300 mr-2">
                      Live AI Process:
                    </span>
                    <span className="font-semibold text-white">
                      Generating {job.kind} <code className="rounded bg-sky-900/50 px-1.5 py-0.5 font-mono text-sky-200">{job.target}</code>
                    </span>
                    <span className="ml-2 text-slate-400">
                      via {job.model} · ${Number(job.price || 0).toFixed(3)}
                    </span>
                  </div>
                </div>
                <span className="flex items-center gap-1.5 rounded-full border border-sky-500/30 bg-sky-500/10 px-2.5 py-1 text-[0.68rem] font-bold uppercase tracking-wider text-sky-300">
                  <span className="h-1.5 w-1.5 rounded-full bg-sky-400 animate-ping" />
                  Generating Now
                </span>
              </div>
            ))}
          </div>
        )}

        <Suspense fallback={<div className="p-6 text-slate-400">Loading...</div>}>
          <Outlet context={ctx} />
        </Suspense>
      </Shell>
      {dialog}
      <BudgetDialog project={name} open={budgetOpen} onClose={() => setBudgetOpen(false)} onDone={load} />
    </VerifyProvider>
  );
}
export const useProject = () => useOutletContext<TabProps>();
