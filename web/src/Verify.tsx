import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, XCircle } from "lucide-react";
import { api } from "./api";
import { notifyDone, notifyStart } from "./notify";
import { Badge, Button } from "./ui";
import { useToast } from "./toast";
import type { VerifyMap } from "./types";

type Scope = keyof VerifyMap;
interface Ctx { v: VerifyMap | null; refresh: () => void; recheck: (s: Scope) => void; }
const VerifyCtx = createContext<Ctx>({ v: null, refresh: () => {}, recheck: () => {} });

export function VerifyProvider({ project, children, tick }: { project: string; children: ReactNode; tick: unknown }) {
  const [v, setV] = useState<VerifyMap | null>(null); const toast = useToast();
  const refresh = useCallback(() => { api<VerifyMap>("GET", `/api/projects/${project}/verify`).then(setV).catch(() => {}); }, [project]);
  useEffect(() => { refresh(); }, [refresh, tick]);
  const anyRunning = v ? Object.values(v).some((s) => s.running) : false;
  useEffect(() => { const t = setInterval(refresh, anyRunning ? 2000 : 6000); return () => clearInterval(t); }, [refresh, anyRunning]);
  const recheck = async (s: Scope) => { const nid = notifyStart(`Checking ${s}`, "Rule checks and AI review", { project }); try { await api("POST", `/api/projects/${project}/verify`, { scope: s }); notifyDone(nid, "ok", "Check finished."); refresh(); } catch (e: any) { toast("error", e.message); notifyDone(nid, "error", e.message); } };
  return <VerifyCtx.Provider value={{ v, refresh, recheck }}>{children}</VerifyCtx.Provider>;
}
export const useVerify = () => useContext(VerifyCtx);

const icon = {
  ok: <CheckCircle2 size={16} className="text-emerald-400" />,
  warn: <AlertTriangle size={16} className="text-amber-400" />,
  fail: <XCircle size={16} className="text-red-400" />,
};
const sevTone = { high: "red", medium: "amber", low: "slate" } as const;

/** Verification of one artifact: instant rule checks + AI review, with the findings and how to fix them. */
export function VerifyBar({ scope, label }: { scope: Scope; label: string }) {
  const { v, recheck } = useVerify(); const [open, setOpen] = useState(false);
  if (!v) return null;
  const s = v[scope]; const n = s.findings.length;
  const aiText = s.running ? "AI is reviewing..." : s.ai ? (s.ai.error ? "AI review unavailable" : `AI reviewed${s.ai.model ? ` (${s.ai.model.split("/").pop()})` : ""}`) : s.ai_stale ? "AI review out of date" : "AI review pending";
  return (
    <div className="panel-quiet p-3 text-sm" data-verify={scope} data-status={s.status}>
      <div className="flex flex-wrap items-center gap-2">
        {icon[s.status]}
        <button type="button" className="font-bold hover:underline" onClick={() => setOpen(!open)} aria-expanded={open}>
          {label}: {s.status === "ok" ? "no problems found" : `${n} ${n === 1 ? "finding" : "findings"}`}
        </button>
        <span className="flex items-center gap-1 text-xs text-slate-400">
          {s.running && <Loader2 size={12} className="spin" />}{aiText}
        </span>
        <Button variant="ghost" size="sm" className="ml-auto" disabled={s.running} onClick={() => recheck(scope)} aria-label={`Re-check ${label} with AI`}>
          <RefreshCw size={12} /> Re-check
        </Button>
      </div>
      {open && (
        <ul className="mt-3 space-y-2">
          {s.findings.map((f, i) => (
            <li key={i} className="rounded-lg border border-slate-800 bg-slate-950/60 p-2.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone={sevTone[f.severity]}>{f.severity}</Badge>
                <span className="font-mono text-xs">{f.where}</span>
                <Badge>{f.source === "ai" ? "AI" : "rule"}</Badge>
              </div>
              <div className="mt-1.5 text-slate-200">{f.issue}</div>
              {f.fix && <div className="mt-1 text-xs text-slate-400">Fix: {f.fix}</div>}
            </li>
          ))}
          {!n && <li className="text-slate-400">Nothing to fix. {s.ai?.summary}</li>}
          {s.ai?.error && <li className="text-xs text-amber-300">{s.ai.error}</li>}
        </ul>
      )}
    </div>
  );
}

export function VerifySummary() {
  const { v } = useVerify();
  if (!v) return null;
  const all = Object.values(v); const fails = all.filter((s) => s.status === "fail").length; const warns = all.filter((s) => s.status === "warn").length;
  return <Badge tone={fails ? "red" : warns ? "amber" : "green"}>{fails ? `${fails} area${fails > 1 ? "s" : ""} with problems` : warns ? `${warns} area${warns > 1 ? "s" : ""} to review` : "all checks pass"}</Badge>;
}
