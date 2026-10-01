import { useEffect, useState } from "react";
import { api } from "./api";
import { Button, Input, Modal, money } from "./ui";
import { Spinner } from "./Proposal";
import { useToast } from "./toast";
import type { BudgetEst, Brief } from "./types";

/** Opens after a storyboard is applied or converted: shows the automatic estimate and asks the human to approve the budget. */
export default function BudgetDialog({ project, open, onClose, onDone }: { project: string; open: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [b, setB] = useState<BudgetEst | null>(null); const [f, setF] = useState("0.2"); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false); const [cap, setCap] = useState<number | null>(null);
  const estimate = async (failure: string) => {
    setBusy(true); setErr("");
    try { setB(await api<BudgetEst>("POST", `/api/projects/${project}/estimate`, { failure: Number(failure) })); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  useEffect(() => {
    if (!open) return;
    setB(null); estimate(f);
    api<Brief>("GET", `/api/projects/${project}/brief`).then((br) => { const v = parseFloat((br.fields.find((x) => x.key === "budget_cap")?.value || "").replace(/[^0-9.]/g, "")); setCap(Number.isFinite(v) && v > 0 ? v : null); }).catch(() => setCap(null));
    /* eslint-disable-next-line */
  }, [open]);
  const approve = async () => {
    setBusy(true);
    try { await api("POST", `/api/projects/${project}/budget/approve`); toast("ok", `Budget approved: ${money(b?.estimate)} (stop-loss ${money(b?.stop_loss)})`); onDone(); onClose(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Set the budget">
      <div className="space-y-4 text-sm">
        {!b && !err && <p className="flex items-center gap-2 text-slate-400"><Spinner /> Calculating the cost from your storyboard...</p>}
        {err && <p className="text-red-400">{err}</p>}
        {b && <>
          <div className="panel-quiet p-4">
            <div className="text-3xl font-extrabold tracking-tight">{money(b.estimate)}</div>
            <div className="mt-1 text-xs text-slate-400">estimated total · stop-loss {money(b.stop_loss)} (generation stops there) · {b.footage_seconds}s of footage</div>
          </div>
          {cap !== null && (
            <p className={`rounded-lg border p-3 text-sm ${b.stop_loss > cap ? "border-red-400/50 bg-red-400/10 text-red-300" : "border-emerald-400/50 bg-emerald-400/10 text-emerald-300"}`}>
              Your budget cap from the brief: <b>{money(cap)}</b>.{" "}
              {b.estimate > cap ? "The estimate is OVER your cap: shorten the video or remove shots before approving."
                : b.stop_loss > cap ? "The estimate fits, but the stop-loss is above your cap."
                  : "The estimate and the stop-loss are within your cap."}
            </p>
          )}
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead><tr><th>shot</th><th>seconds</th><th className="text-right">cost</th></tr></thead>
              <tbody>
                {b.per_shot.map((s) => <tr key={s.id}><td className="font-mono">{s.id}</td><td>{s.seconds}</td><td className="text-right">{money(s.cost)}</td></tr>)}
                <tr><td className="text-slate-400" colSpan={2}>images still to make</td><td className="text-right">{money(b.stills)}</td></tr>
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-xs text-slate-400">retry allowance</label>
            <Input className="!w-16" value={f} onChange={(e) => setF(e.target.value)} aria-label="Retry allowance" />
            <Button variant="outline" size="sm" disabled={busy} onClick={() => estimate(f)}>Recalculate</Button>
            <span className="text-xs text-slate-400">0.2 means plan for 20% of shots to need a retry.</span>
          </div>
          <p className="text-xs text-slate-400">Approving only sets a ceiling. Nothing is generated until you approve each action, and each action shows its exact price first.</p>
        </>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Decide later</Button>
          <Button variant="pink" onClick={approve} disabled={!b || busy}>Approve budget {b ? money(b.estimate) : ""}</Button>
        </div>
      </div>
    </Modal>
  );
}
