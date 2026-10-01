import { useState } from "react";
import { Check, Circle, Plus, X } from "lucide-react";
import { api } from "./api";
import { Badge, Button, Input } from "./ui";
import type { Todos } from "./types";
import { VerifyBar } from "./Verify";
import { ProgressBar, RailCard } from "./components/kit";

export default function TodoList({ project, todos, reload, go }: { project: string; todos: Todos | null; reload: () => void; go: (tab: string) => void }) {
  const [title, setTitle] = useState("");
  if (!todos) return null;
  const call = async (m: string, path: string, body?: unknown) => { await api(m, `/api/projects/${project}/todos${path}`, body); reload(); };
  const total = todos.auto.length + todos.manual.length;
  const done = todos.auto.filter((t) => t.done).length + todos.manual.filter((t) => t.done).length;
  const pct = total ? Math.round((done / total) * 100) : 0;
  return (
    <RailCard title={<span className="flex items-center gap-2"><span className="grid h-6 w-6 place-items-center rounded-lg bg-slate-300/10 text-slate-300"><Check size={13} /></span>TODO</span>}
      sub="Project task list"
      right={<Badge tone={done === total ? "green" : "slate"}>{done}/{total}</Badge>}>
      <ProgressBar value={pct} label="TODO completion" />
      <div className="mt-3"><VerifyBar scope="todos" label="TODO" /></div>
      <ul className="mt-3 space-y-2 text-sm">
        {todos.auto.map((t) => (
          <li key={t.id} className="flex items-start gap-2">
            {t.done ? <Check size={15} className="mt-0.5 shrink-0 text-emerald-400" /> : <Circle size={15} className="mt-0.5 shrink-0 text-slate-400" />}
            <button type="button" className={`min-w-0 flex-1 text-left leading-snug transition hover:underline ${t.done ? "text-slate-400 line-through" : "text-slate-200"}`} onClick={() => go(t.tab)}>{t.title}</button>
            {t.progress && <span className="shrink-0 text-[0.68rem] text-slate-400">{t.progress}</span>}
          </li>
        ))}
        {!!todos.manual.length && <li className="divider !my-2.5" />}
        {todos.manual.map((t) => (
          <li key={t.id} className="flex items-center gap-2">
            <input type="checkbox" checked={t.done} onChange={() => call("POST", `/${t.id}/toggle`)} className="shrink-0" aria-label={t.title} />
            <span className={`min-w-0 flex-1 leading-snug ${t.done ? "text-slate-400 line-through" : "text-slate-200"}`}>{t.title}</span>
            <button type="button" onClick={() => call("DELETE", `/${t.id}`)} aria-label="Remove task" className="shrink-0 text-slate-400 transition hover:text-red-400"><X size={14} /></button>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex gap-2">
        <Input className="min-w-0 flex-1" placeholder="Add a task" value={title} onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && title.trim()) { call("POST", "", { title }); setTitle(""); } }} />
        <Button variant="outline" size="sm" disabled={!title.trim()} onClick={() => { call("POST", "", { title }); setTitle(""); }} aria-label="Add task"><Plus size={14} /></Button>
      </div>
    </RailCard>
  );
}
