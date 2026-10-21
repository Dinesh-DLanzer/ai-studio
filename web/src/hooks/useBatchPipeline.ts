import { useState } from "react";
import { api } from "../api";
import { useToast } from "../toast";
import type { Running } from "../Proposal";

export interface PlanItem {
  kind: "image" | "clip";
  target: string;
  label: string;
  price: number;
  model: string;
  status?: string;
  error?: string;
  changes?: string[];
}

/** A batch frozen by the server. The human approves exactly this list and total (batch_hash); the server runs it. */
export interface Plan {
  id: string;
  batch_hash: string;
  status: string;
  items: PlanItem[];
  total: number;
  budget: {
    estimate: number | null;
    stop_loss: number | null;
    spent: number;
  };
}

export interface UseBatchPipelineProps {
  project: string;
  running: Running;
  reloadAll: () => void;
  load: () => Promise<void>;
}

export function useBatchPipeline({ project, running, reloadAll, load }: UseBatchPipelineProps) {
  const toast = useToast();
  const [plan, setPlan] = useState<Plan | null>(null);
  const [clicking, setClicking] = useState(false);
  const [batch, setBatch] = useState<{ i: number; total: number; label: string } | null>(null);

  const working = clicking || !!batch || Object.keys(running).length > 0;
  const base = `/api/projects/${project}/batches`;

  const openPlan = async () => {
    if (working) return;
    setClicking(true);
    try {
      setPlan(await api<Plan>("POST", base));
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setClicking(false);
    }
  };

  /** The approve button: the human approves the batch, the server runs it, the browser only polls. */
  const runAll = async () => {
    if (!plan) return;
    const { id, batch_hash } = plan;
    setPlan(null);
    let last: Plan | null = null;
    try {
      await api(`POST`, `${base}/${id}/approve`, { batch_hash });
      await api("POST", `${base}/${id}/run`);
      for (;;) {
        await new Promise((r) => setTimeout(r, 1500));
        last = await api<Plan>("GET", `${base}/${id}`);
        const done = last.items.filter((x) => x.status === "done").length;
        const cur = last.items.find((x) => x.status === "running");
        setBatch({ i: Math.min(done + 1, last.items.length), total: last.items.length, label: cur?.label || "" });
        reloadAll();
        if (last.status !== "approved" && last.status !== "running") break;
      }
      const done = last.items.filter((x) => x.status === "done").length;
      const stopped = last.items.find((x) => x.status === "needs_reapproval" || x.status === "error");
      if (last.status === "done") toast("ok", `Generated ${done} item${done === 1 ? "" : "s"}.`);
      else if (stopped) toast("error", `Stopped after ${done} of ${last.items.length}: ${stopped.label} ${stopped.status === "needs_reapproval" ? `changed (${(stopped.changes || []).join(", ")}); review and approve a new batch` : `failed: ${stopped.error || ""}`}`);
      else toast("error", `Batch ${last.status}.`);
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBatch(null);
      reloadAll();
      await load().catch(() => {});
    }
  };

  return {
    plan,
    setPlan,
    clicking,
    setClicking,
    batch,
    working,
    openPlan,
    runAll,
  };
}
