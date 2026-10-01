import { useState } from "react";
import { Check, Copy } from "lucide-react";

/** A code or command block with a Copy button (works without the clipboard API too). */
export default function CodeBlock({ code, label, lang }: { code: string; label: string; lang?: string }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(code); }
    catch { const t = document.createElement("textarea"); t.value = code; document.body.appendChild(t); t.select(); try { document.execCommand("copy"); } catch { /* nothing else to try */ } t.remove(); }
    setDone(true); setTimeout(() => setDone(false), 1800);
  };
  return (
    <div className="group relative">
      <pre role="region" tabIndex={0} aria-label={`${label} (code)`} className="overflow-x-auto rounded-xl border border-slate-800 bg-black/40 p-3 pr-20 text-[0.78rem] leading-relaxed text-slate-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand" data-lang={lang}><code>{code}</code></pre>
      <button type="button" onClick={copy} aria-label={`Copy ${label}`} className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-900/90 px-2 py-1 text-[0.7rem] font-semibold text-slate-200 transition hover:bg-slate-800">
        {done ? <Check size={12} className="text-emerald-300" /> : <Copy size={12} />}{done ? "Copied" : "Copy"}
      </button>
    </div>
  );
}
