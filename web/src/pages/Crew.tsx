import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Users } from "lucide-react";
import { api } from "../api";
import { Badge, Button, Card, Field, Label, Modal, PageHeader, Select } from "../ui";
import { PageBody } from "../app/Shell";
import { Spinner } from "../Proposal";
import { useToast } from "../toast";
import { confirmDialog } from "../dialogs";
import BatchPlanModal from "../components/BatchPlanModal";
import { useBatchPipeline, type Plan } from "../hooks/useBatchPipeline";
import { crewApi, useRun, useRuns } from "../hooks/useCrew";
import { ACTIVE, STAGE_BUTTONS, isStageRun, type AgentRun, type Autonomy, type CheckpointCard, type CrewRun, type RunPlan, type StageRun } from "../types/crew";
import type { TabProps } from "../ProjectPage";

const usd = (n?: number | null) => (n == null ? "-" : `$${n < 1 ? n.toFixed(3) : n.toFixed(2)}`);
const tone = (s: string) => (s === "done" ? "green" : s === "error" || s === "failed" ? "red" : s === "running" || s === "queued" ? "sky" : s === "awaiting_checkpoint" || s === "blocked" ? "amber" : "slate");
const StatusBadge = ({ s }: { s: string }) => <Badge tone={tone(s)}>{s.replace(/_/g, " ")}</Badge>;   // the words carry the status, colour is only extra

/** A small unified-diff renderer: + / - prefixes stay visible, so the meaning never depends on colour. */
export function DiffView({ diff, label }: { diff: string; label: string }) {
  if (!diff) return <p className="text-xs text-slate-400">No text diff for this change.</p>;
  return (
    <pre tabIndex={0} aria-label={label} className="max-h-64 overflow-auto rounded-xl border border-slate-800 bg-slate-950/60 p-2 font-mono text-xs leading-5">
      {diff.split("\n").map((l, i) => (
        <div key={i} className={l.startsWith("+") && !l.startsWith("+++") ? "bg-emerald-400/10 text-emerald-300" : l.startsWith("-") && !l.startsWith("---") ? "bg-red-400/10 text-red-300" : l.startsWith("@@") ? "text-sky" : "text-slate-400"}>{l || " "}</div>
      ))}
    </pre>
  );
}

function PlanDialog({ project, stages, label, onClose, onStarted }: { project: string; stages: string; label: string; onClose: () => void; onStarted: (rid: string) => void }) {
  const toast = useToast();
  const [autonomy, setAutonomy] = useState<Autonomy>("copilot");
  const [cps, setCps] = useState<Record<string, boolean>>({});
  const [plan, setPlan] = useState<RunPlan | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    setErr("");
    crewApi.plan(project, stages, autonomy, cps).then((p) => live && setPlan(p)).catch((e) => live && setErr(e.message));
    return () => { live = false; };
  }, [project, stages, autonomy, cps]);
  const first = plan?.stages[0];
  const blocked = !!first?.prerequisites_missing.length;
  const start = async () => {
    if (!plan || blocked) return;
    setBusy(true);
    try { const r = await crewApi.start(project, stages, plan, cps); toast("ok", "Run started. Nothing is spent; paid work only becomes a proposal for your approval."); onStarted(r.run); }
    catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  return (
    <Modal open onClose={onClose} title={`Run plan: ${label}`} wide>
      {err && <p role="alert" className="text-sm text-red-400">{err}</p>}
      {!plan && !err && <p className="text-sm text-slate-400">Building the plan...</p>}
      {plan && (
        <div className="space-y-4 text-sm" data-testid="run-plan">
          <div className="flex flex-wrap items-end gap-4">
            <label className="block text-sm">
              <span className="mb-1 block font-semibold">Autonomy</span>
              <Select value={autonomy} onChange={(e) => setAutonomy(e.target.value as Autonomy)} aria-label="Autonomy" data-testid="autonomy">
                <option value="copilot">Copilot: agents apply free changes (undoable); paid work is a batch you approve</option>
                <option value="assist">Assist: agents only suggest changes; paid work is proposals only</option>
              </Select>
            </label>
            <div className="panel-quiet p-3" data-testid="plan-paid">
              <div className="text-xs text-slate-400">Paid items so far (a lower bound until the storyboard exists)</div>
              <div className="text-xl font-extrabold" data-testid="plan-paid-total">{usd(plan.paid_total)} so far</div>
            </div>
            <div className="panel-quiet p-3">
              <div className="text-xs text-slate-400">AI text usage cap for this run</div>
              <div className="text-xl font-extrabold" data-testid="plan-llm">up to {usd(plan.llm.max_usd)}</div>
              <div className="text-xs text-slate-400">Project AI spending cap {usd(plan.llm.ai_cap_usd)}</div>
            </div>
          </div>
          <ol className="space-y-3">
            {plan.stages.map((s) => (
              <li key={s.stage} className="rounded-xl border border-slate-800 p-3" data-testid={`plan-stage-${s.stage}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <b>{s.label}</b>
                  <Badge tone={s.free ? "green" : "amber"}>{s.free ? "free" : "paid items proposed"}</Badge>
                  <span className="text-xs text-slate-400">Agents: {s.agents.map((a) => a.id).join(", ")}</span>
                  <label className="ml-auto inline-flex items-center gap-2 text-xs">
                    <input type="checkbox" checked={s.checkpoint} onChange={(e) => setCps({ ...cps, [s.stage]: e.target.checked })} aria-label={`Review checkpoint after ${s.label}`} />
                    Pause for my review after this stage
                  </label>
                </div>
                {s.prerequisites_missing.length > 0 && (
                  <ul className="mt-2 list-disc pl-5 text-xs text-amber-300" role="alert" data-testid={`missing-${s.stage}`}>
                    {s.prerequisites_missing.map((m) => <li key={m}>Missing: {m}</li>)}
                  </ul>
                )}
                {s.paid_items.length > 0 && (
                  <ul className="mt-2 max-h-40 divide-y divide-slate-800 overflow-auto rounded-lg border border-slate-800">
                    {s.paid_items.map((it) => (
                      <li key={`${it.kind}:${it.target}`} className="flex items-center gap-3 px-3 py-1.5">
                        <span className="min-w-0 flex-1 truncate">{it.label}</span><span className="text-xs text-slate-400">{it.model}</span>
                        <span className="font-mono text-xs">{it.price == null ? `no price: ${it.error || ""}` : usd(it.price)}</span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-2 text-xs text-slate-400">Stage total {usd(s.paid_total)}{s.unpriced ? `, ${s.unpriced} item(s) without a price` : ""} · AI text up to {usd(s.llm_max_usd)}</p>
              </li>
            ))}
          </ol>
          <p className="text-xs text-slate-400">{plan.note}</p>
          <p className="text-xs text-slate-500">Plan <code data-testid="plan-hash">{plan.plan_hash}</code> (the run starts only if the plan is still exactly this one).</p>
          {blocked && <p role="alert" className="text-sm text-amber-300" data-testid="start-blocked">Cannot start yet: {first!.prerequisites_missing.join("; ")}.</p>}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button variant="pink" disabled={blocked || busy} onClick={start} data-testid="start-run">{busy ? "Starting..." : "Start"}</Button>
          </div>
        </div>
      )}
    </Modal>
  );
}

function StepLog({ run, project, onChanged }: { run: AgentRun; project: string; onChanged: () => void }) {
  const toast = useToast();
  const [skipped, setSkipped] = useState<string[]>([]);
  const undo = async () => {
    if (!(await confirmDialog(`Undo ${run.agent?.id} run? Documents it changed go back to their earlier version (a new version is written; nothing is lost).`, { title: "Undo this run?", ok: "Undo run" }))) return;
    try {
      const r = await crewApi.undo(project, run.id);
      setSkipped(r.skipped_edited_since);
      toast(r.ok ? "ok" : "error", r.ok ? `Restored ${r.restored.join(", ") || "nothing to restore"}.` : `Restored ${r.restored.join(", ") || "nothing"}; skipped ${r.skipped_edited_since.join(", ")} because they were edited since.`);
      onChanged();
    } catch (e: any) { toast("error", e.message); }
  };
  const canUndo = !ACTIVE.includes(run.status) && !run.undone && !!run.changes?.length;
  return (
    <div className="space-y-3" data-testid={`run-${run.id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <b>{run.agent?.id || "agent"}</b><StatusBadge s={run.status} />
        {run.undone ? <Badge tone="slate">undone</Badge> : null}
        <span className="text-xs text-slate-400">AI text cost {usd(run.llm_usd)}</span>
        {canUndo && <Button size="sm" variant="outline" onClick={undo} aria-label={`Undo run of ${run.agent?.id}`} data-testid="undo-run">Undo run</Button>}
      </div>
      {run.task && <p className="text-xs text-slate-400">Task: {run.task}</p>}
      {run.error && <p role="alert" className="text-sm text-red-400">{run.error}</p>}
      {skipped.length > 0 && <p role="status" className="text-sm text-amber-300" data-testid="skipped-edited">Not restored because you edited them after the run: {skipped.join(", ")}</p>}
      {run.steps.length > 0 && (
        <ol className="divide-y divide-slate-800 rounded-xl border border-slate-800" aria-label={`Steps of ${run.agent?.id || "run"}`}>
          {run.steps.map((s) => (
            <li key={s.n} className="px-3 py-2 text-xs" data-testid="step">
              <div className="flex flex-wrap items-center gap-2"><span className="text-slate-400">#{s.n}</span><code>{s.tool || "(finish)"}</code><StatusBadge s={s.status || "pending"} /></div>
              {s.why && <p className="mt-1 text-slate-300">Why: {s.why}</p>}
              {s.result && <p className="mt-1 break-words text-slate-400">{s.result.length > 300 ? s.result.slice(0, 300) + "..." : s.result}</p>}
            </li>
          ))}
        </ol>
      )}
      {run.summary && <p className="text-sm">{run.summary}</p>}
      {(run.changes || []).map((c) => <div key={c.doc}><div className="mb-1 text-xs font-semibold">Changed {c.doc}</div><DiffView diff={c.diff} label={`Diff of ${c.doc}`} /></div>)}
      {(run.suggested_changes || []).length > 0 && (
        <div><div className="mb-1 text-xs font-semibold">Suggested changes (Assist mode, not applied)</div>
          {run.suggested_changes!.map((c, i) => <div key={i} className="mb-2"><p className="text-xs text-slate-400"><code>{c.tool}</code> {c.why}</p><DiffView diff={c.diff} label={`Suggested change ${i + 1}`} /></div>)}
        </div>
      )}
      {(run.proposals || []).length > 0 && (
        <ul className="divide-y divide-slate-800 rounded-xl border border-slate-800" aria-label="Proposals">
          {run.proposals!.map((p) => <li key={p.id} className="flex items-center gap-3 px-3 py-1.5 text-xs"><span className="flex-1">{p.kind} {p.shot}</span><span className="text-slate-400">{p.model}</span><span className="font-mono">{usd(p.price)}</span><StatusBadge s={p.status} /></li>)}
        </ul>
      )}
    </div>
  );
}

function Checkpoint({ card, onDecide }: { card: CheckpointCard; onDecide: (d: string, note: string) => Promise<void> }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const decide = async (d: string) => { setBusy(true); try { await onDecide(d, note); } finally { setBusy(false); } };
  return (
    <section className="rounded-2xl border border-amber-400/40 bg-amber-400/5 p-4" aria-label="Checkpoint" data-testid="checkpoint">
      <h3 className="text-base font-bold">Checkpoint: {card.title}</h3>
      <ul className="mt-2 space-y-1 text-sm">{card.summary.map((s, i) => <li key={i}><b>{s.agent}</b> <StatusBadge s={s.status} /> {s.summary}</li>)}</ul>
      {card.changes.map((c) => <div key={c.doc} className="mt-2"><div className="mb-1 text-xs font-semibold">Changed {c.doc}</div><DiffView diff={c.diff} label={`Checkpoint diff of ${c.doc}`} /></div>)}
      <p className="mt-3 text-sm">Proposed paid work: <b data-testid="checkpoint-total">{usd(card.proposed_total)}</b> in {card.proposals.length} proposal(s). Nothing is spent until you approve the batch.</p>
      <div className="mt-3"><Label>Note for the next step (optional)</Label><Field rows={2} value={note} onChange={(e) => setNote(e.target.value)} aria-label="Note for the next step" /></div>
      <div className="mt-3 flex flex-wrap gap-2">
        {card.options.map((o) => <Button key={o.id} variant={o.id === "approve_continue" ? "pink" : o.id === "stop" ? "danger" : "outline"} disabled={busy} onClick={() => decide(o.id)} data-testid={`decide-${o.id}`}>{o.label}</Button>)}
      </div>
    </section>
  );
}

function RunView({ project, rid, name, mode, running, reloadAll }: { project: string; rid: string; name: string; mode: string; running: TabProps["running"]; reloadAll: () => void }) {
  const toast = useToast();
  const { run, children, err, reload } = useRun(project, rid);
  const pipe = useBatchPipeline({ project, running, reloadAll, load: async () => { await reload(); } });
  if (err && !run) return <p role="alert" className="text-sm text-red-400">{err}</p>;
  if (!run) return <p className="text-sm text-slate-400">Loading run...</p>;
  const active = ACTIVE.includes(run.status);
  const stop = async () => { try { await crewApi.stop(project, rid); toast("ok", "Stopping."); void reload(); } catch (e: any) { toast("error", e.message); } };
  const decide = async (d: string, note: string) => {
    try { await crewApi.cont(project, rid, d, note); toast("ok", d === "stop" ? "Run stopped." : "Continuing."); await reload(); } catch (e: any) { toast("error", e.message); }
  };
  // the batch is only opened in the existing human approve dialog; approving happens there, by the person
  const openBatch = async (id: string) => { try { pipe.setPlan(await api<Plan>("GET", `/api/projects/${project}/batches/${id}`)); } catch (e: any) { toast("error", e.message); } };
  const batches = (isStageRun(run) ? run.results.flatMap((r) => r.runs).map((i) => children[i]).filter(Boolean) : [run]).map((r) => (r as AgentRun).batch).filter((b) => b?.id && b.status === "awaiting_approval");
  const last = batches[batches.length - 1];
  const stageRun = isStageRun(run) ? (run as StageRun) : null;
  const card = stageRun?.status === "awaiting_checkpoint" ? stageRun.results[stageRun.results.length - 1]?.card : undefined;
  return (
    <div className="space-y-4" data-testid="run-view">
      <div className="flex flex-wrap items-center gap-2" aria-live="polite">
        <h3 className="text-base font-bold">{stageRun ? `Stages: ${stageRun.stages.join(", ")}` : `Run ${run.id}`}</h3>
        <StatusBadge s={run.status} />{active && <Spinner size={14} />}
        <span className="text-xs text-slate-400">AI text cost {usd((run as CrewRun & { llm_usd?: number }).llm_usd)}</span>
        {active && <Button size="sm" variant="danger" className="ml-auto" onClick={stop} data-testid="stop-run">Stop</Button>}
      </div>
      {run.error && <p role="alert" className="text-sm text-red-400">{run.error}</p>}
      {stageRun?.results.map((r) => r.status === "blocked" && <p key={r.stage} role="alert" className="text-sm text-amber-300">{r.stage} is blocked: {r.blocked_by?.join("; ")}</p>)}
      {card && <Checkpoint card={card} onDecide={decide} />}
      {last && (
        <div className="panel-quiet flex flex-wrap items-center gap-3 p-3" data-testid="batch-card">
          <div className="text-sm">Batch ready for your approval: <b data-testid="batch-total">{usd(last.total)}</b> at exact prices. <span className="text-slate-400">The crew cannot approve it.</span></div>
          <Button variant="pink" size="sm" className="ml-auto" onClick={() => openBatch(last.id!)} data-testid="open-batch">Review and approve batch</Button>
        </div>
      )}
      {stageRun ? stageRun.results.map((r) => (
        <div key={r.stage} className="space-y-3 rounded-xl border border-slate-800 p-3">
          <div className="flex items-center gap-2"><b>{r.stage.replace(/_/g, " ")}</b><StatusBadge s={r.status} /></div>
          {r.runs.map((i) => children[i] ? <StepLog key={i} run={children[i] as AgentRun} project={project} onChanged={reload} /> : null)}
        </div>
      )) : <StepLog run={run as AgentRun} project={project} onChanged={reload} />}
      <BatchPlanModal plan={pipe.plan} mode={mode} onClose={() => pipe.setPlan(null)} onApprove={pipe.runAll} />
      <span className="sr-only">{name}</span>
    </div>
  );
}

export function CrewTab({ name, o, running, load }: TabProps) {
  const [sp, setSp] = useSearchParams();
  const { runs, reload } = useRuns(name);
  const [dlg, setDlg] = useState<{ stages: string; label: string } | null>(null);
  const rid = sp.get("run") || runs[0]?.id || null;
  const select = (id: string) => setSp({ run: id }, { replace: true });
  return (
    <PageBody>
      <PageHeader title="Crew" sub="Agents write, design and prepare each stage. Free changes are undoable; paid work is only ever proposed, and you approve it at exact prices." icon={<Users size={24} />} />
      <Card title="Stages" sub="Each stage shows you a run plan with exact prices before anything starts.">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Crew stages">
          {STAGE_BUTTONS.map((b) => <Button key={b.stage} variant="outline" onClick={() => setDlg({ stages: b.stage, label: b.label })} data-testid={`stage-${b.stage}`}>{b.label}</Button>)}
          <Button variant="pink" onClick={() => setDlg({ stages: "make_video", label: "Make this video" })} data-testid="make-video">Make this video</Button>
        </div>
      </Card>
      <Card title="Runs" className="mt-5">
        {runs.length === 0 ? <p className="text-sm text-slate-400">No crew runs yet. Pick a stage above, or chat with <code>@writer</code>.</p> : (
          <div className="mb-4 max-w-xl">
            <Label>Show run</Label>
            <Select value={rid || ""} onChange={(e) => select(e.target.value)} aria-label="Select a run" data-testid="run-select">
              {runs.map((r) => <option key={r.id} value={r.id}>{(r.stages ? r.stages.join(", ") : `${r.agent?.id || "agent"}: ${r.task || ""}`).slice(0, 70)} ({r.status.replace(/_/g, " ")})</option>)}
            </Select>
          </div>
        )}
        {rid && <RunView key={rid} project={name} rid={rid} name={name} mode={o.mode} running={running} reloadAll={() => { load(); void reload(); }} />}
      </Card>
      {dlg && <PlanDialog project={name} stages={dlg.stages} label={dlg.label} onClose={() => setDlg(null)} onStarted={(id) => { setDlg(null); select(id); void reload(); }} />}
    </PageBody>
  );
}
export default CrewTab;
