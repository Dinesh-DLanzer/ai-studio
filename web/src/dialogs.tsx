import { useEffect, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { AlertTriangle, HelpCircle } from "lucide-react";
import { Button } from "./ui";

/** App-styled replacements for window.confirm / window.prompt. Await them like the native ones. */
type Req =
  | { kind: "confirm"; text: string; title?: string; ok?: string; danger?: boolean; done: (v: boolean) => void }
  | { kind: "prompt"; text: string; title?: string; ok?: string; done: (v: string | null) => void };

let show: (r: Req) => void = () => {};

export const confirmDialog = (text: string, o: { title?: string; ok?: string; danger?: boolean } = {}) =>
  new Promise<boolean>((done) => show({ kind: "confirm", text, ...o, done }));
export const promptDialog = (text: string, o: { title?: string; ok?: string } = {}) =>
  new Promise<string | null>((done) => show({ kind: "prompt", text, ...o, done }));

export function DialogHost() {
  const [req, setReq] = useState<Req | null>(null); const [val, setVal] = useState("");
  const queue = useRef<Req[]>([]);
  useEffect(() => {
    show = (r) => setReq((cur) => { if (cur) { queue.current.push(r); return cur; } setVal(""); return r; });
    return () => { show = () => {}; };
  }, []);
  const close = (ok: boolean) => {
    if (!req) return;
    if (req.kind === "confirm") req.done(ok); else req.done(ok ? val : null);
    const next = queue.current.shift() || null; setVal(""); setReq(next);
  };
  const [first, ...paras] = (req?.text || "").split("\n\n");
  return (
    <Dialog.Root open={!!req} onOpenChange={(o) => !o && close(false)}>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim" />
        <Dialog.Content aria-describedby={undefined}
          className="fixed left-1/2 top-1/2 z-[70] w-[min(440px,92vw)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-pop">
          <div className="flex items-start gap-3">
            <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl border ${req?.kind === "confirm" && req.danger ? "border-red-400/40 bg-red-400/10 text-red-300" : "border-pink/30 bg-pink/10 text-pink"}`}>
              {req?.kind === "confirm" && req.danger ? <AlertTriangle size={18} /> : <HelpCircle size={18} />}
            </span>
            <div className="min-w-0 flex-1">
              <Dialog.Title className="text-base font-bold tracking-tight">{req?.title || (req?.kind === "prompt" ? "Add a note" : "Please confirm")}</Dialog.Title>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-300">{first}</p>
              {paras.map((x, i) => <p key={i} className="mt-2 text-xs leading-relaxed text-slate-400">{x}</p>)}
              {req?.kind === "prompt" && (
                <input autoFocus className="field mt-3" value={val} onChange={(e) => setVal(e.target.value)} aria-label={first}
                  onKeyDown={(e) => { if (e.key === "Enter") close(true); }} />
              )}
            </div>
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="outline" onClick={() => close(false)}>Cancel</Button>
            <Button variant={req?.kind === "confirm" && req.danger ? "danger" : "pink"} onClick={() => close(true)}>{req?.ok || "Continue"}</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
