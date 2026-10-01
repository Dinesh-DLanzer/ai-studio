import { useState, useCallback } from "react";
import { Loader2 } from "lucide-react";
import { api } from "./api";
import { Button, Modal, Badge, money } from "./ui";
import { useToast } from "./toast";
import { notifyDone, notifyStart } from "./notify";
import type { Proposal } from "./types";

export const Spinner = ({ size = 14 }: { size?: number }) => <Loader2 size={size} className="animate-spin" aria-hidden />;

/** Run an already-approved proposal and wait for the job; returns a short message. */
export async function execAndWait(project: string, pid: string, override = false): Promise<string> {
  const { job } = await api<{ job: string }>("POST", `/api/projects/${project}/proposals/${pid}/execute`, { override });
  for (;;) {
    await new Promise((r) => setTimeout(r, 1500));
    const j = await api<any>("GET", `/api/jobs/${job}`);
    if (j.status === "running") continue;
    if (j.status === "error") throw new Error(j.error);
    return j.result?.error ? `Provider error: ${j.result.error}` : j.result?.pending ? "Still generating; use Sync later." : j.result?.review ? `Vision review: ${j.result.review.verdict}` : j.result?.file ? `Done: ${j.result.file} ($${Number(j.result.cost ?? 0).toFixed(3)})` : "Done.";
  }
}

export type Running = Record<string, string>;   // "kind:target" -> kind
export const runKey = (kind: string, target: string) => `${kind}:${target}`;

/** Every paid action: propose (free) -> human sees the exact price -> approve. After approval the dialog CLOSES and the
 *  item shows a loading state; a toast reports the result. */
export function useProposal(project: string, mode: string, onDone: () => void) {
  const toast = useToast();
  const [prop, setProp] = useState<Proposal | null>(null);
  const [msg, setMsg] = useState("");
  const [override, setOverride] = useState(false);
  const [running, setRunning] = useState<Running>({});

  const start = useCallback(async (kind: "image" | "clip" | "review", target: string) => {
    setMsg(""); setOverride(false);
    try { setProp(await api<Proposal>("POST", `/api/projects/${project}/proposals`, { kind, target })); }
    catch (e: any) { toast("error", e.message); }
  }, [project, toast]);

  const close = async () => {
    if (prop) await api("POST", `/api/projects/${project}/proposals/${prop.id}/reject`).catch(() => {});
    setProp(null);
  };

  const go = async () => {
    if (!prop) return;
    const p = prop, key = runKey(p.kind, p.shot);
    try {
      await api("POST", `/api/projects/${project}/proposals/${p.id}/approve`, { code: p.code });
    } catch (e: any) { setMsg(e.message); return; }
    setProp(null);                                        // close the popup right away
    setRunning((r) => ({ ...r, [key]: p.kind }));
    toast("info", `Started ${p.kind} ${p.shot} (${money(p.price)})...`);
    const label = { image: "Generating image", clip: "Generating video clip", review: "Reviewing clip" }[p.kind] || `Running ${p.kind}`;
    const nid = notifyStart(`${label} ${p.shot}`, `${p.model} · ${money(p.price)}`, { project, to: `/p/${project}/${p.kind === "image" ? "assets" : "shots"}` });
    execAndWait(project, p.id, override)
      .then((m) => { const bad = m.startsWith("Provider error"); toast(bad ? "error" : "ok", `${p.kind} ${p.shot}: ${m}`); notifyDone(nid, bad ? "error" : "ok", m); })
      .catch((e: any) => { toast("error", `${p.kind} ${p.shot} failed: ${e.message}`); notifyDone(nid, "error", e.message); })
      .finally(() => { setRunning((r) => { const n = { ...r }; delete n[key]; return n; }); onDone(); });
  };

  const dialog = (
    <Modal open={!!prop} onClose={close} title="Approve this paid action?">
      {prop && (
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={mode === "real" ? "red" : "green"}>{mode === "real" ? "REAL PROJECT: spends money" : "TEST PROJECT: no real money"}</Badge>
            <Badge>{prop.kind}</Badge><span className="font-mono">{prop.shot}</span><span className="text-slate-400">{prop.summary?.provider ? `${prop.summary.provider} · ` : ""}{prop.model}</span>
          </div>
          <div className="panel-quiet p-3">
            <div className="text-2xl font-extrabold tracking-tight">{money(prop.price)}</div>
            <div className="mt-1 text-xs text-slate-400">This exact request, price and prompt. If anything changes after you approve, the approval is void.</div>
          </div>
          {msg && <p className="text-red-600">{msg}</p>}
          <div className="flex items-center justify-end gap-2">
            <label className="mr-auto flex items-center gap-1.5 text-xs text-slate-400"><input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} /> override stop-loss / attempt limit</label>
            <Button variant="outline" onClick={close}>Cancel</Button>
            <Button onClick={go}>Approve and run {money(prop.price)}</Button>
          </div>
        </div>
      )}
    </Modal>
  );
  return { start, dialog, running };
}
