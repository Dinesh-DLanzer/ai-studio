import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import { api } from "./api";
import { Button, Field } from "./ui";
import { ExtraLanguages, LanguageSelect } from "./Languages";
import { useToast } from "./toast";
import type { Brief } from "./types";

/** The voice language: exactly one. */
export const voiceLanguages = (fields: { key: string; value: string }[]) => fields.find((f) => f.key === "language")?.value || "";

/** Visual editor for brief.md: one box per brief question. Saving writes brief.json and brief.md together, so every screen shows the same answers. */
export default function BriefForm({ name, brief, onSaved, saveRef, onStatus, compact = false, showSave = true }: {
  name: string; brief: Brief | null; onSaved: () => void | Promise<void>;
  saveRef?: React.MutableRefObject<(() => Promise<void>) | null>; onStatus?: (s: string) => void; compact?: boolean; showSave?: boolean;
}) {
  const toast = useToast();
  const [draft, setDraft] = useState<Record<string, string>>({}); const [dirty, setDirty] = useState(false); const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!brief || dirty) return;
    setDraft({ ...Object.fromEntries(brief.fields.map((f) => [f.key, f.value])), language: voiceLanguages(brief.fields) });
  }, [brief, dirty]);
  const save = async () => {
    if (/[,;&\/]| and /i.test(draft.language || "")) { toast("error", "Choose one voice language only."); return; }
    setBusy(true);
    try {
      await api("PUT", `/api/projects/${name}/brief`, { ...draft, _clear: true });
      setDirty(false); onStatus?.("Saved"); setTimeout(() => onStatus?.(""), 1500); await onSaved();
    } catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  if (saveRef) saveRef.current = save;
  if (!brief) return <p className="text-sm text-slate-400">Loading...</p>;
  const set = (k: string, v: string) => { setDraft((d) => ({ ...d, [k]: v })); setDirty(true); };
  return (
    <div className={compact ? "space-y-3" : "grid gap-4 md:grid-cols-2 xl:grid-cols-3"}>
      {brief.fields.filter((f) => f.key !== "extra_languages").map((f) => (
        <div key={f.key}>
          <label htmlFor={`brief-${f.key}`} className="mb-1 block text-xs font-semibold text-slate-300">
            {f.label}{f.required && <span className="text-pink"> *</span>}
          </label>
          {f.key === "language" ? (
            <>
              <LanguageSelect value={draft.language || ""} label="Brief voice language" onChange={(v) => set("language", v)} />
              <p className="mt-1 text-[0.68rem] text-slate-400">One language only.</p>
              <span className="mb-1 mt-3 block text-xs font-semibold text-slate-300">Other languages</span>
              <ExtraLanguages value={draft.extra_languages || ""} primary={draft.language || ""} onChange={(v) => set("extra_languages", v)} />
            </>
          ) : (
            <Field id={`brief-${f.key}`} className="!h-24 !resize-none" value={draft[f.key] || ""} placeholder={f.question} onChange={(e) => set(f.key, e.target.value)} />
          )}
        </div>
      ))}
      {showSave && (
        <div className={compact ? "" : "col-span-full"}>
          <Button variant="pink" disabled={busy || !dirty} onClick={save}><Save size={15} />Save summary</Button>
        </div>
      )}
    </div>
  );
}
