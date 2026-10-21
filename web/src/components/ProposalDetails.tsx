import { AlertTriangle } from "lucide-react";
import { money } from "../ui";
import type { ProposalSummary } from "../types";

/** The facts an approver should see next to the price: what the quote is made of, how old the price is, what the model can do and what was adjusted. Read-only. */
export default function ProposalDetails({ summary }: { summary?: ProposalSummary }) {
  if (!summary) return null;
  const b = summary.price_breakdown, p = summary.profile, warnings = summary.warnings || [];
  const stale = b?.age_days != null && b.age_days > 30;
  if (!b && !p && !warnings.length) return null;
  return (
    <div className="space-y-3" data-testid="proposal-details">
      {b && b.total != null && (
        <dl className="kv" aria-label="Price breakdown" data-testid="price-breakdown">
          <dt>{b.billed_seconds != null ? `Base (${b.billed_seconds}s billed)` : "Base"}</dt><dd>{money(b.base)}</dd>
          {b.minimum_applied && <><dt>Minimum applied</dt><dd>Yes, billed for {b.billed_seconds}s</dd></>}
          <dt>References</dt><dd>{b.refs ? money(b.refs) : "none charged"}</dd>
          <dt>Audio</dt><dd>{b.audio ? "included in the rate" : "off"}</dd>
          <dt>Total</dt><dd className="font-bold">{money(b.total)}</dd>
          <dt>Price as of</dt><dd>{b.retrieved_at ?? "an unknown date"}{b.age_days != null ? ` (${b.age_days} days old)` : ""}{b.source ? `, source: ${b.source}` : ""}</dd>
        </dl>
      )}
      {stale && <p role="note" className="flex items-start gap-2 text-xs text-amber-300" data-testid="price-age-warning"><AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden /><span><b>Old price:</b> this price is {b!.age_days} days old. Check it against the provider before approving.</span></p>}
      {p && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs" aria-label="Model capabilities" data-testid="profile-chips">
          <span className="tag">Capabilities from {p.source}</span>
          {p.durations.length > 0 && <span className="tag">Durations {p.durations.join(", ")}s</span>}
          <span className="tag">{p.frames.end ? "End frame supported" : "No end frame"}</span>
          <span className="tag">References max {p.references.max}</span>
          <span className="tag">Camera: {p.camera.mode}</span>
        </div>
      )}
      {warnings.length > 0 && (
        <ul className="space-y-1 text-xs text-amber-300" aria-label="Warnings" data-testid="proposal-warnings">
          {warnings.map((w, i) => <li key={i} className="flex items-start gap-2"><AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden /><span><b>Warning:</b> {w}</span></li>)}
        </ul>
      )}
    </div>
  );
}
