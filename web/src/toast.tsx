import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { DialogHost } from "./dialogs";
import { CheckCircle2, XCircle, X } from "lucide-react";

export interface Toast { id: number; kind: "ok" | "error" | "info"; text: string; }
const Ctx = createContext<(kind: Toast["kind"], text: string) => void>(() => {});
export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x.slice(-3), { id, kind, text }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "error" ? 15000 : 7000);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <DialogHost />
      <div className="fixed bottom-4 right-4 z-50 flex w-[min(380px,92vw)] flex-col gap-2" aria-live="polite">
        {items.map((t) => (
          <div key={t.id}
            className={`panel panel-lit flex items-start gap-2.5 p-3.5 text-sm shadow-pop ${t.kind === "error" ? "!border-red-400/60 text-red-100" : "text-slate-100"}`}>
            {t.kind === "error" ? <XCircle className="mt-0.5 shrink-0 text-red-400" size={16} /> : <CheckCircle2 className="mt-0.5 shrink-0 text-emerald-400" size={16} />}
            <span className="flex-1 leading-snug">{t.text}</span>
            <button type="button" onClick={() => setItems((x) => x.filter((y) => y.id !== t.id))} aria-label="Dismiss" className="shrink-0 text-slate-400 transition hover:text-white"><X size={14} /></button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
