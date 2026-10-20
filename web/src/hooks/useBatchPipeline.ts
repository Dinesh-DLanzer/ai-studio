import { useState } from "react";
import { api } from "../api";
import { execAndWait, type Running } from "../Proposal";
import { useToast } from "../toast";
import type { Proposal } from "../types";

export interface PlanItem {
  kind: "image" | "clip";
  target: string;
  label: string;
  price: number;
  model: string;
}

export interface Plan {
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

  const openPlan = async () => {
    if (working) return;
    setClicking(true);
    try {
      setPlan(await api<Plan>("GET", `/api/projects/${project}/generate-all`));
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setClicking(false);
    }
  };

  /** One human approval for the whole list (exact prices shown first); runs each item through propose / approve / execute. */
  const runAll = async () => {
    const items = plan?.items || [];
    setPlan(null);
    let done = 0;
    const errors: string[] = [];
    try {
      for (const [i, it] of items.entries()) {
        setBatch({ i: i + 1, total: items.length, label: it.label });
        try {
          const prop = await api<Proposal>("POST", `/api/projects/${project}/proposals`, { kind: it.kind, target: it.target });
          await api("POST", `/api/projects/${project}/proposals/${prop.id}/approve`, { code: prop.code });
          const msg = await execAndWait(project, prop.id, false);
          if (msg.startsWith("Provider error")) {
            errors.push(`${it.label}: ${msg}`);
            continue;
          }
          done++;
          try {
            reloadAll();
          } catch {
            /* ignore */
          }
          await load().catch(() => {});
        } catch (itemErr: any) {
          errors.push(`${it.label}: ${itemErr.message}`);
          console.warn(`[runAll] ${it.label} error:`, itemErr);
        }
      }
      if (errors.length === 0) {
        toast("ok", `Generated ${done} item${done === 1 ? "" : "s"}.`);
      } else {
        toast(done > 0 ? "ok" : "error", `Generated ${done} of ${items.length} item${items.length === 1 ? "" : "s"}${errors.length ? ` (${errors.length} failed)` : ""}.`);
      }
    } catch (e: any) {
      toast("error", `Stopped after ${done} of ${items.length}: ${e.message}`);
    } finally {
      setBatch(null);
      try {
        reloadAll();
      } catch {
        /* ignore */
      }
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
