import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BookOpen, FlaskConical } from "lucide-react";
import { api } from "../api";
import { Badge, Button, Card, Field, Input, Label, PageHeader, Select } from "../ui";
import { PageBody } from "../app/Shell";
import { useBatchPipeline, type Plan } from "../hooks/useBatchPipeline";
import BatchPlanModal from "../components/BatchPlanModal";
import type { TabProps } from "../ProjectPage";

type RecipeInput = { id?: string; name?: string; label?: string; type?: string; required?: boolean; options?: (string | { value: string; label?: string })[]; choices?: string[]; default?: unknown; description?: string };
type Recipe = { id: string; label: string; description?: string; category?: string; available: boolean; reasons?: string[]; skipped?: string[]; inputs?: RecipeInput[] };
const title = (i: RecipeInput) => i.label || i.name || i.id || "Input";

export default function RecipesPage({ name, running, load, openBudget }: Pick<TabProps, "name" | "running" | "load" | "openBudget">) {
  const [recipes, setRecipes] = useState<Recipe[]>([]); const [selected, setSelected] = useState<Recipe | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({}); const [stills, setStills] = useState<string[]>([]);
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false); const [progress, setProgress] = useState("");
  const pipe = useBatchPipeline({ project: name, running, reloadAll: load, load: async () => { await load(); } });
  const refresh = async () => { const r = await api<{ recipes: Recipe[] }>("GET", `/api/recipes?project=${encodeURIComponent(name)}`); setRecipes(r.recipes || []); };
  useEffect(() => { refresh().catch((e) => setError(e.message)); api<any>("GET", `/api/projects/${name}`).then((o) => setStills(o.files?.stills || [])).catch(() => {}); }, [name]);
  const choose = (r: Recipe) => { setSelected(r); setValues(Object.fromEntries((r.inputs || []).map((i) => [i.id || i.name || "", i.default ?? ""]))); setError(""); };
  const plan = async () => {
    if (!selected) return; setBusy(true); setError(""); setProgress("");
    try {
      const created = await api<any>("POST", `/api/projects/${name}/recipes/${encodeURIComponent(selected.id)}/plan`, { inputs: values });
      const batch = created.batch || created;
      if (batch.recipe?.budget_ready === false || created.recipe?.budget_ready === false) { setError("Re-estimate and approve the budget first."); return; }
      pipe.setPlan(batch as Plan); setProgress(`Batch ${batch.id || "created"} is awaiting your review. Nothing has been approved or run.`);
    } catch (e: any) {
      const data = e.data; const ready = data?.recipe?.budget_ready ?? data?.detail?.recipe?.budget_ready;
      if (ready === false) setError("Re-estimate and approve the budget first."); else setError(e.message);
    } finally { setBusy(false); }
  };
  return <PageBody><div className="space-y-4">
    <PageHeader title="Recipe" accent="Library" icon={<BookOpen size={24} />} sub="Run a guided workflow. Every paid step is priced into a batch that waits for your approval." />
    {error && <p role="alert" className="rounded-xl border border-amber-400/30 bg-amber-400/5 p-3 text-sm text-amber-200">{error} {error.includes("budget") && <><button className="ml-1 underline" onClick={openBudget}>Open budget</button> to re-estimate and approve it.</>}</p>}
    {progress && <p role="status" className="text-sm text-slate-300">{progress}</p>}
    <div className="grid gap-3 xl:grid-cols-2">{recipes.map((r) => <Card key={r.id} title={r.label} sub={r.description || r.category} right={<Badge tone={r.available ? "green" : "amber"}>{r.available ? "Available" : "Unavailable"}</Badge>}>
      {!r.available && <ul className="mb-3 list-disc pl-5 text-sm text-amber-200">{(r.reasons || []).map((x) => <li key={x}>{x}</li>)}</ul>}
      {!!r.skipped?.length && <p className="mb-3 text-xs text-slate-400">Skipped steps: {r.skipped.join(", ")}</p>}
      <Button variant="outline" disabled={!r.available} onClick={() => choose(r)}>Configure recipe</Button>
    </Card>)}</div>
    {selected && <Card title={`Configure ${selected.label}`} sub="Inputs are sent to the local planner; no work starts here.">
      <div className="grid gap-3 md:grid-cols-2">{(selected.inputs || []).map((i) => { const key = i.id || i.name || ""; const label = `${title(i)}${i.required ? " (required)" : ""}`; const choices = i.options || i.choices;
        return <div key={key}><Label>{label}</Label>{/image|still|asset/i.test(i.type || "") ? <Select aria-label={label} value={String(values[key] || "")} onChange={(e) => setValues({ ...values, [key]: e.target.value })}><option value="">Choose a project still</option>{stills.map((s) => <option key={s} value={s}>{s}</option>)}</Select>
          : choices ? <Select aria-label={label} value={String(values[key] || "")} onChange={(e) => setValues({ ...values, [key]: e.target.value })}><option value="">Choose...</option>{choices.map((c) => { const v = typeof c === "string" ? c : c.value; return <option key={v} value={v}>{typeof c === "string" ? c : c.label || v}</option>; })}</Select>
          : /number/i.test(i.type || "") ? <Input type="number" aria-label={label} value={String(values[key] ?? "")} onChange={(e) => setValues({ ...values, [key]: Number(e.target.value) })} />
          : <Field aria-label={label} rows={2} value={String(values[key] || "")} onChange={(e) => setValues({ ...values, [key]: e.target.value })} />}{i.description && <p className="mt-1 text-xs text-slate-400">{i.description}</p>}</div>; })}</div>
      <div className="mt-4 flex gap-2"><Button variant="pink" disabled={busy} onClick={plan}>{busy ? "Planning…" : "Create approval batch"}</Button><Button variant="outline" onClick={() => setSelected(null)}>Cancel</Button></div>
    </Card>}
    <p className="text-xs text-slate-500"><FlaskConical className="mr-1 inline" size={13} />A plan only creates an awaiting-approval batch. A person must review and approve it in the shared batch dialog.</p>
    <BatchPlanModal plan={pipe.plan} mode="real" onClose={() => pipe.setPlan(null)} onApprove={pipe.runAll} title="Review recipe batch" />
  </div></PageBody>;
}
