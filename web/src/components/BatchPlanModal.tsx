import { Badge, Button, Modal } from "../ui";
import type { Plan } from "../hooks/useBatchPipeline";

const usd = (n: number) => `$${n < 1 ? n.toFixed(3) : n.toFixed(2)}`;

/** The human approve dialog for a frozen batch (shared by Chat's Generate all and the Crew page). Approving is only ever done here. */
export default function BatchPlanModal({ plan, mode, onClose, onApprove, title = "Generate everything that is left?" }: { plan: Plan | null; mode: string; onClose: () => void; onApprove: () => void; title?: string }) {
  return (
    <Modal open={!!plan} onClose={onClose} title={title}>
      {plan && (
        <div className="space-y-3 text-sm" data-testid="plan">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={mode === "real" ? "red" : "green"}>{mode === "real" ? "REAL PROJECT: spends money" : "TEST PROJECT: no real money"}</Badge>
            <span className="text-slate-400">{plan.items.length} items, one after the other</span>
          </div>
          <div className="panel-quiet p-3">
            <div className="text-2xl font-extrabold tracking-tight" data-testid="plan-total">{usd(plan.total)}</div>
            <div className="mt-1 text-xs text-slate-400">The exact price of each item is below. Approving starts them in order; the run stops at the first problem, and the usual budget and stop-loss limits still apply to every item.</div>
            {plan.budget.estimate != null && <div className="mt-1 text-xs text-slate-400">Budget {usd(plan.budget.estimate)} · spent so far {usd(plan.budget.spent)}</div>}
            {plan.budget.stop_loss != null && plan.budget.spent + plan.total > plan.budget.stop_loss && <p role="alert" className="mt-2 text-xs text-amber-300">This is more than the stop-loss ({usd(plan.budget.stop_loss)}). The run will stop when the limit is reached.</p>}
          </div>
          <ul className="max-h-60 divide-y divide-slate-800 overflow-auto rounded-xl border border-slate-800">
            {plan.items.map((it) => <li key={`${it.kind}:${it.target}`} className="flex items-center gap-3 px-3 py-2"><span className="min-w-0 flex-1 truncate">{it.label}</span><span className="text-xs text-slate-400">{it.model}</span><span className="font-mono text-xs">{usd(it.price)}</span></li>)}
          </ul>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button variant="pink" onClick={onApprove} data-testid="approve-all">Approve and run all {usd(plan.total)}</Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
