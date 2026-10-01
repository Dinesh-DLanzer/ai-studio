import type { ReactNode } from "react";
import { BRAND, TAGLINE } from "../brand";

/** The "A" mark: a pink-to-amber gradient tile with a dark counter. */
export function LogoMark({ size = 40 }: { size?: number }) {
  return <img src="/logo-mark.png" width={size} height={size} alt="" aria-hidden className="shrink-0 object-contain" />;
}

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark size={compact ? 32 : 38} />
      {!compact && (
        <div className="leading-none">
          <div className="text-lg font-extrabold tracking-tight">{BRAND}</div>
          <div className="mt-1 text-[9px] font-semibold tracking-[0.2em] text-slate-400">{TAGLINE}</div>
        </div>
      )}
    </div>
  );
}

export function ProgressBar({ value, max = 100, label, className = "" }: { value: number; max?: number; label?: string; className?: string }) {
  const pct = Math.max(0, Math.min(100, max ? (value / max) * 100 : 0));
  return (
    <div className={`progress ${className}`} role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <div className="progress-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Ring gauge: the track is a hairline, the value sweeps a pink→lime gradient. */
export function Donut({ value, max, size = 56, label }: { value: number; max: number; size?: number; label?: string }) {
  const pct = max ? Math.min(1, value / max) : 0;
  const r = 20; const c = 2 * Math.PI * r;
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" role="img" aria-label={label ?? `${Math.round(pct * 100)} percent`}>
      <defs>
        <linearGradient id="donut-fill" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#ff2d95" />
          <stop offset="1" stopColor="#d7ff3f" />
        </linearGradient>
      </defs>
      <circle cx="24" cy="24" r={r} fill="none" stroke="#23232f" strokeWidth="6" />
      {pct > 0 && (
        <circle cx="24" cy="24" r={r} fill="none" stroke="url(#donut-fill)" strokeWidth="6" strokeLinecap="round"
          strokeDasharray={`${c * pct} ${c}`} transform="rotate(-90 24 24)" />
      )}
    </svg>
  );
}

/** Big number + caption, used in the budget rail and the costs stat row. */
export function StatTile({ value, label, tone = "text-slate-100", sub }: { value: ReactNode; label: string; tone?: string; sub?: ReactNode }) {
  return (
    <div className="panel-quiet px-3 py-2.5 text-center">
      <div className={`text-lg font-extrabold tracking-tight ${tone}`}>{value}</div>
      <div className="mt-0.5 text-[0.68rem] font-medium text-slate-400">{label}</div>
      {sub && <div className="mt-1 text-[0.65rem] text-slate-400">{sub}</div>}
    </div>
  );
}

export function Chip({ children, active = false, onClick, tone = "lime" }: { children: ReactNode; active?: boolean; onClick?: () => void; tone?: "lime" | "pink" }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active}
      className={`pill ${tone === "lime" ? "pill-lime" : ""} ${active ? "" : "!bg-transparent"}`}>
      {children}
    </button>
  );
}

/** Pill tabs with counts (Characters 2, Backgrounds 8 ...): the active one is a glowing pink gradient. */
export function PillTabs<T extends string>({ items, value, onChange }: { items: { id: T; label: string; count?: number; icon?: ReactNode }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div role="tablist" className="flex flex-wrap gap-2">
      {items.map((t) => (
        <button key={t.id} type="button" role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)} className="pill">
          {t.icon}
          {t.label}
          {t.count !== undefined && (
            <span className={`rounded-full px-1.5 text-[0.68rem] ${value === t.id ? "bg-black/25" : "bg-white/7"}`}>{t.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

export const Skeleton = ({ className = "" }: { className?: string }) => <div className={`skeleton ${className}`} aria-hidden />;

export function EmptyState({ title, text, action, icon }: { title: string; text?: string; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-slate-700/80 bg-white/[.012] px-6 py-7 text-center">
      {icon && <div className="grid h-10 w-10 place-items-center rounded-xl border border-slate-800 bg-slate-300/10 text-slate-300">{icon}</div>}
      <div className="text-sm font-bold">{title}</div>
      {text && <p className="max-w-md text-xs leading-relaxed text-slate-400">{text}</p>}
      {action}
    </div>
  );
}

export function SectionHeader({ title, sub, right, count, sticky }: { sticky?: boolean; title: ReactNode; sub?: ReactNode; right?: ReactNode; count?: number | string }) {
  return (
    <div className={`mb-3 flex flex-wrap items-center justify-between gap-3 ${sticky ? "sticky-head" : ""}`}>
      <div className="min-w-0">
        <h2 className="flex items-center gap-2.5 text-lg font-extrabold tracking-tight">
          {title}
          {count !== undefined && <span className="tag">{count}</span>}
        </h2>
        {sub && <p className="mt-1 text-xs text-slate-400">{sub}</p>}
      </div>
      {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}

/** Titled block for the right-hand rail. */
export function RailCard({ title, sub, right, children, className = "" }: { title?: ReactNode; sub?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel panel-lit panel-pad ${className}`}>
      {(title || right) && (
        <div className="mb-3 flex items-start justify-between gap-2">
          <div className="min-w-0">
            {title && <h3 className="text-sm font-bold tracking-tight">{title}</h3>}
            {sub && <p className="mt-0.5 text-[0.68rem] text-slate-400">{sub}</p>}
          </div>
          {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

/** Tilted phone frame used in the hero collage and the page headers. */
export function Phone({ src, className = "" }: { src?: string; className?: string }) {
  return (
    <div className={`hero-frame ${className}`}>
      {src
        ? <img src={src} alt="" className="h-full w-full object-cover" loading="lazy" />
        : <div className="grid h-full w-full place-items-center bg-gradient-to-br from-pink/25 to-brand/10" />}
    </div>
  );
}

/** Page banner: big title and sentence on the left, a tilted collage of the project's own frames and a handwritten note on the right. */
export function PageBanner({ title, sub, note, pics }: { title: string; sub: ReactNode; note: ReactNode; pics: string[] }) {
  const collage = ["left-[30%] top-8 h-28 w-[4.5rem] -rotate-6", "left-[41%] top-4 h-36 w-[5.5rem] -rotate-3", "left-[54%] -top-1 z-10 h-48 w-28", "left-[70%] top-4 h-36 w-[5.5rem] rotate-3", "left-[84%] top-8 h-28 w-[4.5rem] rotate-6"];
  return (
    <header className="page-head">
      <div className="grid items-center gap-4 md:grid-cols-[1fr_minmax(0,28rem)]">
        <div className="min-w-0">
          <h1 className="page-title">{title}</h1>
          <p className="mt-2 max-w-xl text-sm text-slate-400">{sub}</p>
        </div>
        <div className="relative hidden h-52 md:block" aria-hidden>
          <span className="hand-note absolute left-0 top-9 z-20 -rotate-6 whitespace-nowrap text-[1.3rem]">
            {note}
            <svg viewBox="0 0 60 30" width="58" height="29" className="absolute -right-[3.2rem] -top-1 fill-none stroke-[#e6f542]" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6 C 22 0, 42 6, 54 22" /><path d="M43 21 L55 23 L52 11" /></svg>
          </span>
          {collage.map((c, i) => <Phone key={i} src={pics[i]} className={`absolute ${c}`} />)}
        </div>
      </div>
    </header>
  );
}
