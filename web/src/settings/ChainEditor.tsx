import { useState } from "react";
import { AlertTriangle, ArrowDown, ArrowUp, GripVertical, Plus, X } from "lucide-react";
import { Button, IconButton } from "../ui";
import type { ChainEntry, Role } from "./types";

const ordinal = (i: number) => (i === 0 ? "Primary" : `Fallback ${i + 1}`);

export default function ChainEditor({ role, chain, hasProviders, disabled, onReorder, onRemove, onAdd, onSetPrice }: {
  role: Role; chain: ChainEntry[]; hasProviders: boolean; disabled?: boolean;
  onReorder: (from: number, to: number) => void; onRemove: (i: number) => void; onAdd: () => void; onSetPrice: (e: ChainEntry) => void;
}) {
  const [drag, setDrag] = useState<number | null>(null); const [over, setOver] = useState<number | null>(null);

  if (chain.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-700 p-4 text-center text-sm text-slate-400">
        {hasProviders ? (
          <>
            <p className="mb-3">No model yet. Add one to use this process</p>
            <Button variant="pink" onClick={onAdd} disabled={disabled}><Plus size={14} aria-hidden /> Add model</Button>
          </>
        ) : (
          <p>
            <button type="button" className="font-semibold text-pink underline underline-offset-2 hover:text-white"
              onClick={() => document.getElementById("set-providers")?.scrollIntoView({ behavior: "smooth", block: "start" })}>Connect a provider first</button>
          </p>
        )}
      </div>
    );
  }

  return (
    <div>
      <ol className="space-y-2" aria-label={`${role} model chain, in order of use`}>
        {chain.map((e, i) => (
          <li key={`${e.provider}\u0000${e.model}`} draggable={!disabled}
            onDragStart={(ev) => { setDrag(i); ev.dataTransfer.effectAllowed = "move"; ev.dataTransfer.setData("text/plain", String(i)); }}
            onDragOver={(ev) => { if (drag !== null) { ev.preventDefault(); setOver(i); } }}
            onDrop={(ev) => { ev.preventDefault(); if (drag !== null && drag !== i) onReorder(drag, i); setDrag(null); setOver(null); }}
            onDragEnd={() => { setDrag(null); setOver(null); }}
            className={`panel-quiet p-2.5 ${drag === i ? "opacity-50" : ""} ${over === i && drag !== null && drag !== i ? "!border-pink/60" : ""}`}>
            <div className="flex items-center gap-2">
              <span aria-hidden title="Drag to reorder" className="cursor-grab text-slate-500"><GripVertical size={16} /></span>
              <span className={`tag ${i === 0 ? "tag-grad" : ""}`}>{ordinal(i)}</span>
              <span aria-hidden className="grid h-6 w-6 shrink-0 place-items-center rounded-md border border-slate-700 bg-white/5 text-xs font-bold text-slate-200">{(e.provider_label || e.provider).charAt(0).toUpperCase()}</span>
              <div className="min-w-0 flex-1">
                <div className="truncate font-mono text-sm text-slate-100" title={`${e.provider_label} • ${e.model}`}>
                  <span className="text-slate-300">{e.provider_label}</span> <span aria-hidden className="mx-0.5 text-slate-500">&bull;</span> {e.model}
                </div>
              </div>
              <div className="flex shrink-0 items-center">
                <IconButton aria-label={`Move ${e.model} up`} disabled={disabled || i === 0} onClick={() => onReorder(i, i - 1)} className="!h-7 !w-7"><ArrowUp size={14} /></IconButton>
                <IconButton aria-label={`Move ${e.model} down`} disabled={disabled || i === chain.length - 1} onClick={() => onReorder(i, i + 1)} className="!h-7 !w-7"><ArrowDown size={14} /></IconButton>
                <IconButton aria-label={`Remove ${e.model} from ${role} chain`} disabled={disabled} onClick={() => onRemove(i)} className="!h-7 !w-7"><X size={14} /></IconButton>
              </div>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5 pl-6">
              {e.free ? <span className="tag tag-emerald">free</span>
                : e.priced && e.price ? <span className="tag">{e.price}</span>
                : <button type="button" className="tag tag-amber cursor-pointer hover:brightness-125" onClick={() => onSetPrice(e)} aria-label={`Set price for ${e.model}`}>Set price</button>}
              {e.problem && <span className="tag tag-red"><AlertTriangle size={11} aria-hidden /> {e.problem}</span>}
              {e.unhealthy && <span className="tag tag-amber" title={e.unhealthy}><AlertTriangle size={11} aria-hidden /> Provider unhealthy</span>}
              {e.dearer && i > 0 && <span className="tag tag-amber"><AlertTriangle size={11} aria-hidden /> Costs more: needs new approval</span>}
            </div>
          </li>
        ))}
      </ol>
      <Button variant="outline" size="sm" className="mt-3" onClick={onAdd} disabled={disabled}><Plus size={14} aria-hidden /> Add fallback</Button>
    </div>
  );
}
