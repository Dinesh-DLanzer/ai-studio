import { useEffect, useState } from "react";
import { Pencil } from "lucide-react";
import { Button, Input, Modal } from "./ui";

const ID_OK = /^[A-Za-z0-9_-]{1,64}$/;

export type RenameProps = { kind: string; current: string; explain: string; onRename: (next: string) => Promise<void> };

/** The rename dialog on its own, for places that trigger renaming from something other than a pencil (a dropdown item, say). */
export function RenameDialog({ open, onClose, ...p }: RenameProps & { open: boolean; onClose: () => void }) {
  const [v, setV] = useState(p.current); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setV(p.current); setErr(""); } }, [open, p.current]);
  const submit = async () => {
    const n = v.trim();
    if (!ID_OK.test(n)) return setErr("Use letters, numbers, - or _ only (up to 64 characters).");
    if (n === p.current) return onClose();
    setBusy(true); setErr("");
    try { await p.onRename(n); onClose(); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title={`Rename ${p.kind}`}>
      <div className="space-y-3 text-sm">
        <p className="text-slate-500">{p.explain}</p>
        <Input className="w-full" autoFocus value={v} onChange={(e) => setV(e.target.value)} aria-label={`New ${p.kind} name`} onKeyDown={(e) => e.key === "Enter" && submit()} />
        {err && <p className="text-red-400">{err}</p>}
        <div className="flex justify-end gap-2"><Button variant="outline" onClick={onClose}>Cancel</Button><Button onClick={submit} disabled={busy || !v.trim() || v.trim() === p.current}>Rename</Button></div>
      </div>
    </Modal>
  );
}

/** A small pencil that opens a dialog to rename something (project, asset id, shot id). `explain` says what else changes. */
export function RenameButton({ kind, current, explain, onRename, label }: RenameProps & { label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="icon-btn !h-9 !w-9 !border-transparent hover:!border-slate-800" title={`Rename ${kind}`} aria-label={label || `Rename ${kind} ${current}`}
        onClick={(e) => { e.stopPropagation(); setOpen(true); }}><Pencil size={13} /></button>
      <RenameDialog open={open} onClose={() => setOpen(false)} kind={kind} current={current} explain={explain} onRename={onRename} />
    </>
  );
}