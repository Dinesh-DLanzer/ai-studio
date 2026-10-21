import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, ScanFace, Users } from "lucide-react";
import { api, fileUrl } from "../api";
import { Button, Input, Label, Select } from "../ui";
import { useToast } from "../toast";
import { confirmDialog } from "../dialogs";
import { RailCard } from "./kit";
import type { Plan } from "../hooks/useBatchPipeline";
import type { ImageSpec, Proposal } from "../types";

const VIEWS = ["front", "three-quarter", "profile", "full-body", "expression"];
const THRESHOLD = 0.6;     // the server flags identity scores below this (character_check.DRIFT_THRESHOLD)
interface Consent { subject: string; statement: string; date: string; kind: string }
interface Drift { scores?: Record<string, number>; summary?: string; when?: string }

/** Cast: identity sheet, versions, drift and consent for one character. Everything that costs money only creates a batch or proposal for the human to approve. */
export default function CastPanel({ project, spec, stills, hasMaster, onBatch, openProposal, reload }: {
  project: string; spec: ImageSpec; stills: string[]; hasMaster: boolean; onBatch: (b: Plan) => void; openProposal?: (p: Proposal) => void; reload: () => void;
}) {
  const toast = useToast();
  const [consent, setConsent] = useState<Consent[]>([]); const [drift, setDrift] = useState<Drift | null>(null);
  const [subject, setSubject] = useState(""); const [statement, setStatement] = useState(""); const [kind, setKind] = useState("real_person");
  const [sha, setSha] = useState("");
  const [count, setCount] = useState("2"); const [busy, setBusy] = useState(false);
  const [unitPrice, setUnitPrice] = useState<number | null>(null);
  const base = `/api/projects/${encodeURIComponent(project)}`;
  useEffect(() => {
    api<{ price?: number }>("GET", `${base}/spec/image/${encodeURIComponent(spec.id)}`)
      .then((r) => { if (typeof r.price === "number") setUnitPrice(r.price); })
      .catch(() => {});
  }, [base, spec.id]);
  const loadConsent = useCallback(() => api<{ consent: Consent[] }>("GET", `${base}/consent`).then((r) => setConsent(r.consent)).catch(() => {}), [base]);
  useEffect(() => { void loadConsent(); }, [loadConsent]);
  useEffect(() => {
    setDrift(null);
    fetch(fileUrl(project, `checks/${spec.id}.json`)).then((r) => (r.ok ? r.json() : null)).then(setDrift).catch(() => {});
  }, [project, spec.id, stills.length]);

  const views = VIEWS.map((v) => { const e = (spec.views || []).find((x) => x.view === v); const made = !!e && stills.includes(e.file.replace("stills/", "")); return { v, e, made }; });
  const missing = views.filter((x) => !x.made);
  const versions = stills.map((f) => f.match(new RegExp(`^${spec.id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\.v(\\d+)\\.[A-Za-z0-9]+$`))).filter((m): m is RegExpMatchArray => !!m)
    .map((m) => ({ n: Number(m[1]), file: m[0] })).sort((a, b) => a.n - b.n);
  const own = consent.filter((c) => c.subject.trim().toLowerCase() === (spec.subject || spec.id).trim().toLowerCase());
  const score = drift?.scores?.[spec.id];

  const run = async (fn: () => Promise<void>) => { setBusy(true); try { await fn(); } catch (e) { toast("error", (e as Error).message); } finally { setBusy(false); } };
  const sheet = () => run(async () => { onBatch(await api<Plan>("POST", `${base}/characters/${encodeURIComponent(spec.id)}/identity-sheet`, {})); });
  const variants = () => run(async () => { onBatch(await api<Plan>("POST", `${base}/variants`, { kind: "image", target: spec.id, count: Number(count) })); });
  const check = () => run(async () => {
    const p = await api<Proposal>("POST", `${base}/drift-check`, { target: spec.id });
    if (openProposal) openProposal(p); else toast("info", "Drift check proposed; approve it from the proposals list.");
  });
  const select = (n: number) => run(async () => {
    if (!(await confirmDialog(`Use version ${n} of ${spec.id}? The other versions move to Discarded with their cost (nothing is deleted, and you can restore them).`, { title: "Select this version?", ok: `Use version ${n}` }))) return;
    await api("POST", `${base}/variants/select`, { kind: "image", target: spec.id, version: n });
    toast("ok", `Using version ${n} of ${spec.id}.`); reload();
  });
  const record = () => run(async () => {
    await api("POST", `${base}/consent`, { subject: subject.trim(), statement: statement.trim(), kind, ...(sha ? { asset_id: spec.id } : {}) });
    toast("ok", `Consent recorded for ${subject.trim()}.`); setSubject(""); setStatement(""); await loadConsent();
  });

  return (
    <RailCard title={<span className="flex items-center gap-2"><Users size={15} aria-hidden />Cast: {spec.id}</span>} sub="Identity sheet, versions, drift and consent">
      <div className="space-y-4 text-sm" data-testid="cast-panel">
        <section aria-label="Identity sheet">
          <h4 className="mb-1.5 text-xs font-semibold text-slate-300">Identity sheet</h4>
          <ul className="grid grid-cols-5 gap-1.5">
            {views.map(({ v, e, made }) => (
              <li key={v} className="min-w-0 text-center">
                <div className="thumb aspect-square">{made && e ? <img src={fileUrl(project, e.file)} alt={`${spec.id} ${v} view`} /> : <div className="grid h-full place-items-center text-[0.6rem] text-slate-500">none</div>}</div>
                <span className="mt-0.5 block truncate text-[0.62rem] text-slate-400" title={v}>{v}{made ? "" : " (missing)"}</span>
              </li>
            ))}
          </ul>
          <Button variant="outline" size="sm" className="mt-2 w-full" disabled={busy || !hasMaster || !missing.length} onClick={() => void sheet()}
            title={!hasMaster ? "Make or upload the master image first" : ""}>
            <ScanFace size={14} />{missing.length ? `Build identity sheet (${missing.length} view${missing.length === 1 ? "" : "s"})${unitPrice != null ? ` · $${(missing.length * unitPrice).toFixed(3)}` : ""}` : "Identity sheet complete"}
          </Button>
          <p className="mt-1 text-[0.68rem] text-slate-400">Creates a batch with an exact total. Nothing is spent until you approve it.</p>
        </section>

        <section aria-label="Versions">
          <h4 className="mb-1.5 text-xs font-semibold text-slate-300">Versions</h4>
          {versions.length > 0 ? (
            <ul className="flex flex-wrap gap-2" data-testid="variants-strip">
              {versions.map((x) => {
                const on = spec.selected_version === x.n;
                return (
                  <li key={x.n} className="w-20 text-center">
                    <div className={`thumb aspect-square ${on ? "!border-pink" : ""}`}><img src={fileUrl(project, `stills/${x.file}`)} alt={`${spec.id} version ${x.n}`} /></div>
                    {on ? <span className="mt-1 block text-[0.65rem] font-bold text-pink">Selected</span>
                      : <button type="button" className="btn btn-outline btn-sm mt-1 w-full !px-1 !text-[0.65rem]" disabled={busy} onClick={() => void select(x.n)} aria-label={`Select version ${x.n} of ${spec.id}`}>Select version {x.n}</button>}
                  </li>
                );
              })}
            </ul>
          ) : <p className="text-xs text-slate-400">No other versions yet.</p>}
          <div className="mt-2 flex items-end gap-2">
            <div><Label>Candidates</Label><Select aria-label="Number of candidates" value={count} onChange={(e) => setCount(e.target.value)}>{[2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}</Select></div>
            <Button variant="outline" size="sm" disabled={busy || !hasMaster} onClick={() => void variants()}>{unitPrice != null ? `Generate ${count} variants · ${count} × $${unitPrice.toFixed(3)} ($${(Number(count) * unitPrice).toFixed(3)})` : `Generate ${count} variants`}</Button>
          </div>
          <p className="mt-1 text-[0.68rem] text-slate-400">N candidates cost N times the price, shown before you approve.</p>
        </section>

        <section aria-label="Identity drift">
          <h4 className="mb-1.5 text-xs font-semibold text-slate-300">Identity drift</h4>
          {score === undefined ? <p className="text-xs text-slate-400" data-testid="drift-none">No drift check yet.</p> : score < THRESHOLD
            ? <p className="flex items-start gap-1.5 text-xs text-amber-300" data-testid="drift-badge"><AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden /><span><b>Drift:</b> identity score {score.toFixed(2)}, below {THRESHOLD}. {drift?.summary}</span></p>
            : <p className="flex items-start gap-1.5 text-xs text-emerald-300" data-testid="drift-badge"><CheckCircle2 size={14} className="mt-0.5 shrink-0" aria-hidden /><span><b>Identity match:</b> score {score.toFixed(2)} (needs {THRESHOLD} or more). {drift?.summary}</span></p>}
          <Button variant="outline" size="sm" className="mt-2" disabled={busy || !hasMaster} onClick={() => void check()}>Check drift (paid, you approve the price)</Button>
        </section>

        <section aria-label="Consent">
          <h4 className="mb-1.5 text-xs font-semibold text-slate-300">Consent {spec.real_person ? <span className="tag tag-amber ml-1">real person</span> : null}</h4>
          {spec.real_person && !own.length && <p role="note" className="mb-2 text-xs text-amber-300"><b>Needed:</b> this character is marked as a real person, and generation is refused until consent is recorded for {spec.subject || spec.id}.</p>}
          <ul className="mb-2 space-y-1 text-xs">
            {consent.map((c, i) => <li key={i} className="rounded-lg border border-slate-800 px-2 py-1"><b>{c.subject}</b> ({c.kind.replace("_", " ")}, {c.date}): {c.statement}</li>)}
            {!consent.length && <li className="text-slate-400">No consent recorded in this project.</li>}
          </ul>
          <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); void record(); }}>
            <Input aria-label="Consent subject" placeholder={`Who (${spec.subject || spec.id})`} value={subject} onChange={(e) => setSubject(e.target.value)} />
            <Input aria-label="Consent statement" placeholder="Their statement, e.g. I agree to be shown in this video" value={statement} onChange={(e) => setStatement(e.target.value)} />
            <div className="flex items-center gap-2">
              <Select aria-label="Consent kind" value={kind} onChange={(e) => setKind(e.target.value)}><option value="real_person">real person</option><option value="voice">voice</option></Select>
              <Button type="submit" size="sm" variant="outline" disabled={busy || !subject.trim() || !statement.trim()}>Record consent</Button>
            </div>
          </form>
          <div className="mt-2 rounded-lg border border-slate-700 p-2">
            <p className="text-xs text-slate-400">Bind the record to this asset’s current file before using consent-gated tools.</p>
            <Button type="button" size="sm" variant="outline" className="mt-2" disabled={busy || !hasMaster} onClick={() => void run(async () => { const r = await api<{ sha: string }>("POST", `${base}/consent/mark`, { asset_id: spec.id }); setSha(r.sha); toast("ok", `Current asset bytes marked (${r.sha.slice(0, 12)}…).`); })}>{sha ? `File marked · ${sha.slice(0, 12)}…` : "Mark current file as a real person"}</Button>
          </div>
          <p className="mt-1 text-[0.68rem] text-slate-400">Only you can record consent here. Agents and the crew cannot.</p>
        </section>
      </div>
    </RailCard>
  );
}
