import React from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

export const money = (n?: number | null) => (n === undefined || n === null ? "-" : `$${n.toFixed(n < 1 ? 3 : 2)}`);

type Variant = "primary" | "pink" | "ghost" | "danger" | "outline" | "soft";

const variants: Record<Variant, string> = {
  primary: "btn-lime",
  pink: "btn-grad",
  outline: "btn-outline",
  ghost: "btn-ghost",
  danger: "btn-danger",
  soft: "border border-transparent bg-white/5 text-slate-100 hover:bg-white/10",
};

export function Button({ variant = "primary", size, className = "", ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "lg" }) {
  return <button type="button" className={`btn ${variants[variant]} ${size ? `btn-${size}` : ""} ${className}`} {...p} />;
}

/** Square icon-only button (the "..." menus, view toggles, arrows). */
export const IconButton = ({ className = "", active = false, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) =>
  <button type="button" aria-pressed={p["aria-pressed"] ?? active} data-active={active || undefined} className={`icon-btn ${className}`} {...p} />;

/**
 * The standard raised surface. `title` renders the panel header (icon + title on
 * the left, actions on the right). `sub` is the muted line under the title.
 */
export function Card({ title, sub, right, children, className = "", bodyClass = "" }: {
  title?: React.ReactNode; sub?: React.ReactNode; right?: React.ReactNode;
  children: React.ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={`panel panel-lit panel-pad ${className}`}>
      {(title || right) && (
        <div className="panel-head">
          <div className="min-w-0">
            {title && <h3 className="panel-title">{title}</h3>}
            {sub && <p className="panel-sub">{sub}</p>}
          </div>
          {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
        </div>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

const tones: Record<string, string> = {
  green: "tag-emerald", amber: "tag-amber", red: "tag-red", pink: "tag-grad",
  lime: "tag-lime", sky: "tag-sky", slate: "tag",
};
export const Badge = ({ tone = "slate", children, className = "" }: { tone?: keyof typeof tones; children: React.ReactNode; className?: string }) =>
  <span className={`tag ${tones[tone]} ${className}`}>{children}</span>;

export const Field = (p: React.TextareaHTMLAttributes<HTMLTextAreaElement>) =>
  <textarea {...p} className={`field ${p.className || ""}`} />;
export const Input = (p: React.InputHTMLAttributes<HTMLInputElement>) =>
  <input {...p} className={`field ${p.className || ""}`} />;
export const Select = (p: React.SelectHTMLAttributes<HTMLSelectElement>) =>
  <select {...p} className={`select ${p.className || ""}`} />;

/** Small label above a form control. */
export const Label = ({ children, hint }: { children: React.ReactNode; hint?: React.ReactNode }) =>
  <div className="mb-1.5 flex items-baseline justify-between gap-2">
    <span className="text-xs font-semibold text-slate-300">{children}</span>
    {hint && <span className="text-xs text-slate-400">{hint}</span>}
  </div>;

/** Page banner: eyebrow, big title with a gradient accent, and a subtitle. */
export function PageHeader({ title, accent, sub, icon, right, art }: {
  title: string; accent?: string; sub?: React.ReactNode; icon?: React.ReactNode; right?: React.ReactNode; art?: string;
}) {
  return (
    <header className={`page-head ${art ? "md:min-h-[9rem]" : ""}`}>
      {art && <img src={art} alt="" aria-hidden className="pointer-events-none absolute bottom-0 right-4 hidden h-[8.5rem] w-auto select-none md:block" style={{ position: "absolute" }} />}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          {icon && <div className="hidden h-14 w-14 shrink-0 place-items-center rounded-2xl border border-pink/30 bg-gradient-to-br from-pink/20 to-violet/10 text-pink sm:grid">{icon}</div>}
          <div className="min-w-0">
            <h1 className="page-title">{title}{accent && <> <span className="grad-text">{accent}</span></>}</h1>
            {sub && <p className="mt-2 max-w-2xl text-sm text-slate-400">{sub}</p>}
          </div>
        </div>
        {right && <div className="flex shrink-0 flex-wrap items-center gap-2">{right}</div>}
      </div>
    </header>
  );
}

/** Icon tile used in the rails and section headers. */
const tileTones = {
  muted: "text-slate-300 border-slate-800 bg-slate-300/10",
  lime: "text-brand border-brand/30 bg-brand/12",
  pink: "text-pink border-pink/35 bg-pink/14",
  sky: "text-sky border-sky/35 bg-sky/14",
  violet: "text-violet border-violet/35 bg-violet/14",
  amber: "text-amber-400 border-amber-400/35 bg-amber-400/14",
  emerald: "text-emerald-400 border-emerald-400/35 bg-emerald-400/14",
};
export type TileTone = keyof typeof tileTones;
export const IconTile = ({ children, tone = "muted", size = "sm" }: { children: React.ReactNode; tone?: TileTone; size?: "sm" | "lg" }) => (
  <span className={`grid shrink-0 place-items-center border ${size === "lg" ? "h-12 w-12 rounded-2xl" : "h-7 w-7 rounded-lg"} ${tileTones[tone]}`}>{children}</span>
);

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim" />
        <Dialog.Content aria-describedby={undefined}
          className={`fixed left-1/2 top-1/2 z-50 max-h-[90vh] ${wide ? "w-[min(1100px,96vw)]" : "w-[min(680px,94vw)]"} -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-pop`}>
          <div className="mb-4 flex items-center justify-between gap-3">
            <Dialog.Title className="text-lg font-bold tracking-tight">{title}</Dialog.Title>
            <Dialog.Close className="icon-btn !h-8 !w-8" aria-label="Close"><X size={16} /></Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** Modal for destructive or irreversible actions: a red-tinged title bar and a confirm row. */
export function ConfirmBody({ text, confirm, onConfirm, onClose, busy, tone = "primary" }: {
  text: React.ReactNode; confirm: string; onConfirm: () => void; onClose: () => void; busy?: boolean; tone?: "primary" | "danger";
}) {
  return (
    <div className="space-y-4 text-sm text-slate-300">
      <div>{text}</div>
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onClose}>Cancel</Button>
        <Button variant={tone === "danger" ? "danger" : "primary"} onClick={onConfirm} disabled={busy}>{confirm}</Button>
      </div>
    </div>
  );
}
