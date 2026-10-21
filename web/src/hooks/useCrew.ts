import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { ACTIVE, type Autonomy, type CrewAgents, type CrewRun, type RunListItem, type RunPlan, type UndoResult } from "../types/crew";

const base = (p: string) => `/api/projects/${encodeURIComponent(p)}/crew`;
const qs = (stages: string, autonomy: Autonomy, checkpoints: Record<string, boolean>) =>
  `stages=${encodeURIComponent(stages)}&autonomy=${autonomy}&checkpoints=${encodeURIComponent(JSON.stringify(checkpoints))}`;

export const crewApi = {
  plan: (p: string, stages: string, autonomy: Autonomy, cps: Record<string, boolean>) => api<RunPlan>("GET", `${base(p)}/plan?${qs(stages, autonomy, cps)}`),
  // the plan_hash is the one the human just saw; the server refuses (409) when the plan changed since
  start: (p: string, stage: string, plan: RunPlan, cps: Record<string, boolean>) =>
    api<{ run: string }>("POST", `${base(p)}/stages/${stage}/run`, { plan_hash: plan.plan_hash, autonomy: plan.autonomy, checkpoints: cps }),
  cont: (p: string, rid: string, decision: string, note: string) => api("POST", `${base(p)}/runs/${rid}/continue`, { decision, note }),
  stop: (p: string, rid: string) => api("POST", `${base(p)}/runs/${rid}/stop`),
  undo: (p: string, rid: string) => api<UndoResult>("POST", `${base(p)}/runs/${rid}/undo`),
  agents: () => api<CrewAgents>("GET", "/api/crew/agents"),
  putAgent: (id: string, body: unknown) => api("PUT", `/api/crew/agents/${id}`, body),
};

/** The project's runs, refreshed every 3 s while any is active (the server runs them; the browser only reads). */
export function useRuns(project: string) {
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const load = useCallback(() => api<{ runs: RunListItem[] }>("GET", `${base(project)}/runs`).then((r) => setRuns(r.runs)).catch(() => {}), [project]);
  useEffect(() => { void load(); }, [load]);
  const active = runs.some((r) => ACTIVE.includes(r.status));
  useEffect(() => { if (!active) return; const t = setInterval(load, 3000); return () => clearInterval(t); }, [active, load]);
  return { runs, reload: load };
}

/** One run record, polled every 2 s while it is running. Stage runs also load their child agent runs. */
export function useRun(project: string, rid: string | null) {
  const [run, setRun] = useState<CrewRun | null>(null);
  const [children, setChildren] = useState<Record<string, CrewRun>>({});
  const [err, setErr] = useState("");
  const load = useCallback(async () => {
    if (!rid) return;
    try {
      const r = await api<CrewRun>("GET", `${base(project)}/runs/${rid}`);
      setRun(r); setErr("");
      if (r.kind === "stage_run") {
        const got = await Promise.all(r.results.flatMap((x) => x.runs).map((i) => api<CrewRun>("GET", `${base(project)}/runs/${i}`).catch(() => null)));
        setChildren(Object.fromEntries(got.filter((c): c is CrewRun => !!c).map((c) => [c.id, c])));
      }
    } catch (e: any) { setErr(e.message); }
  }, [project, rid]);
  useEffect(() => { setRun(null); setChildren({}); void load(); }, [load]);
  const active = !!run && ACTIVE.includes(run.status);
  useEffect(() => { if (!active) return; const t = setInterval(load, 2000); return () => clearInterval(t); }, [active, load]);
  return { run, children, err, reload: load };
}
