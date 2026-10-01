import { useEffect, useState } from "react";
import { api } from "./api";
import { Badge, Select } from "./ui";
import type { LanguageInfo } from "./types";

let cache: LanguageInfo[] | null = null;
export function useLanguages() {
  const [list, setList] = useState<LanguageInfo[]>(cache || []);
  useEffect(() => { if (!cache) api<{ languages: LanguageInfo[] }>("GET", "/api/languages").then((r) => { cache = r.languages; setList(r.languages); }).catch(() => {}); }, []);
  return list;
}

export function LanguageNote({ name, list }: { name: string; list: LanguageInfo[] }) {
  if (!name) return null;
  const inf = list.find((l) => l.name.toLowerCase() === name.toLowerCase());
  if (!inf) return <p className="mt-1.5 text-xs text-amber-400">"{name}" is not in the list. You can keep it, but test one clip first.</p>;
  return inf.tested
    ? <p className="mt-1.5 text-xs text-emerald-400">Tested with the video model{inf.script ? `; write the voice lines in ${inf.name} script, with the English meaning.` : "."}</p>
    : <p className="mt-1.5 text-xs text-amber-400">Not tested yet with the video model. Make one cheap test clip and have a native speaker listen before making the rest.</p>;
}

/** Voice language dropdown (plus a custom entry). `onChange` saves. */
export function LanguageSelect({ value, onChange, label = "Voice language" }: { value: string; onChange: (v: string) => void; label?: string }) {
  const list = useLanguages();
  const known = list.some((l) => l.name.toLowerCase() === value.toLowerCase());
  const [custom, setCustom] = useState(false);
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <Select aria-label={label} value={custom || (value && !known) ? "__other" : (list.find((l) => l.name.toLowerCase() === value.toLowerCase())?.name ?? "")}
          onChange={(e) => { if (e.target.value === "__other") setCustom(true); else { setCustom(false); onChange(e.target.value); } }}>
          <option value="">Choose a language...</option>
          {list.map((l) => <option key={l.name} value={l.name}>{l.name}{l.tested ? " (tested)" : ""}</option>)}
          <option value="__other">Other...</option>
        </Select>
        {(custom || (value && !known)) && (
          <input aria-label={`${label} (custom)`} defaultValue={known ? "" : value} placeholder="type a language" className="field !w-48 !py-1.5 text-sm"
            onBlur={(e) => e.target.value.trim() && onChange(e.target.value.trim())} onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()} />
        )}
        {value && known && <Badge tone={list.find((l) => l.name.toLowerCase() === value.toLowerCase())?.tested ? "green" : "amber"}>{list.find((l) => l.name.toLowerCase() === value.toLowerCase())?.tested ? "tested" : "untested"}</Badge>}
      </div>
      <LanguageNote name={value} list={list} />
    </div>
  );
}

/** Toggle chips for additional languages (comma list). */
export function ExtraLanguages({ value, primary, onChange }: { value: string; primary: string; onChange: (v: string) => void }) {
  const list = useLanguages();
  const chosen = value.split(",").map((x) => x.trim()).filter(Boolean);
  const toggle = (n: string) => onChange((chosen.includes(n) ? chosen.filter((x) => x !== n) : [...chosen, n]).join(", "));
  return (
    <div className="flex flex-wrap gap-1.5">
      {list.filter((l) => l.name !== primary).slice(0, 14).map((l) => (
        <button key={l.name} type="button" onClick={() => toggle(l.name)} aria-pressed={chosen.includes(l.name)}
          className={`rounded-xl border px-2.5 py-1 text-[0.7rem] font-semibold transition ${chosen.includes(l.name) ? "border-brand bg-brand text-black" : "border-slate-700 text-slate-400 hover:border-slate-500 hover:text-slate-100"}`}>{l.name}</button>
      ))}
    </div>
  );
}
