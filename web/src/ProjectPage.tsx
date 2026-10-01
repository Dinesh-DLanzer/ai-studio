import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Bold, Braces, Clock, Italic, Link2, List, ListOrdered, Maximize2, Minimize2, Play, Quote, Strikethrough, Users, FileCode2, FileText, Film, ListChecks,
  BarChart3, DollarSign, PieChart, Image as ImageIcon, RotateCcw, Tag, TrendingDown, Video as VideoIcon, Save, Trash2, Wallet,
} from "lucide-react";
import { api, fileUrl } from "./api";
import { Badge, Button, Card, IconTile, Input, Modal, PageHeader, Select, money, type TileTone } from "./ui";
import { Spinner, type Running } from "./Proposal";
import { useToast } from "./toast";
import { confirmDialog } from "./dialogs";
import { VerifyBar } from "./Verify";
import BriefForm, { voiceLanguages } from "./BriefForm";
import { PageBody } from "./app/Shell";
import { Link } from "react-router-dom";
import { EmptyState, PageBanner, RailCard, StatTile } from "./components/kit";
import type { Brief, FoundStill, ImageSpec, Overview, Review } from "./types";

export const stem = (f: string) => f.replace(/\.[^.]+$/, "");
const fmtDate = (v?: string) => {
  if (!v) return "";
  const d = new Date(v);
  return Number.isNaN(+d) ? v.slice(0, 16) : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
};

export function ReviewBadge({ r }: { r?: Review | null }) {
  if (!r) return null;
  return (
    <div className="mt-2 text-xs">
      <Badge tone={r.verdict === "pass" ? "green" : r.verdict === "warn" ? "amber" : "red"}>vision: {r.verdict}</Badge>
      <span className="ml-1 text-slate-400">{r.summary}</span>
      {r.findings.map((f, i) => <div key={i} className="mt-1 text-red-400">frame {f.frame}: {f.issue} ({f.severity})</div>)}
      <div className="mt-1 text-slate-400">Advisory only: you still check it and listen to the audio.</div>
    </div>
  );
}

export type TabProps = { o: Overview; name: string; load: () => void; start: (k: "image" | "clip" | "review", t: string) => void; running: Running; openBudget: () => void; todoNode: React.ReactNode; todosDone?: boolean };

/* ------------------------------------------------------------------ storyboard */

const DOCS = [
  { fn: "Story.md", sub: "Full script (markdown)", label: "Story", icon: FileCode2, hint: "The full script: scenes, voice lines and on-screen text." },
  { fn: "brief.md", sub: "Visual editor (required fields)", label: "Brief", icon: ListChecks, hint: "Required fields the verification checks." },
  { fn: "TODO.md", sub: "Task list (auto-generated)", label: "TODO", icon: FileText, hint: "The task list, generated from the story." },
] as const;

function DocEditor({ name, fn, onSaved, saveRef, onStatus, rev }: { name: string; fn: string; rev?: unknown; onSaved?: () => void | Promise<void>; saveRef: React.MutableRefObject<(() => Promise<void>) | null>; onStatus: (s: string) => void }) {
  const [t, setT] = useState(""); const [full, setFull] = useState(false);
  const ta = useRef<HTMLTextAreaElement>(null); const gutter = useRef<HTMLDivElement>(null);
  const loaded = useRef<string | null>(null);
  useEffect(() => {
    if (loaded.current !== null && t !== loaded.current) return;        // never overwrite unsaved typing
    api<{ text: string }>("GET", `/api/projects/${name}/docs/${fn}`).then((r) => { loaded.current = r.text; setT(r.text); }).catch(() => setT(""));
    /* eslint-disable-next-line */
  }, [name, fn, rev]);
  const save = async () => { loaded.current = t; await api("PUT", `/api/projects/${name}/docs/${fn}`, { text: t }); onStatus("Saved"); setTimeout(() => onStatus(""), 1500); await onSaved?.(); };
  saveRef.current = save;
  const words = t.trim() ? t.trim().split(/\s+/).length : 0;
  const lines = t ? t.split("\n").length : 1;
  /** Wrap the selection (or prefix its lines) with markdown. */
  const wrap = (before: string, after = before, linePrefix = false) => {
    const el = ta.current; if (!el) return;
    const { selectionStart: s0, selectionEnd: e0 } = el;
    let next: string;
    if (linePrefix) {
      const start = t.lastIndexOf("\n", s0 - 1) + 1;
      next = t.slice(0, start) + t.slice(start, e0).split("\n").map((l) => before + l).join("\n") + t.slice(e0);
    } else next = t.slice(0, s0) + before + t.slice(s0, e0) + after + t.slice(e0);
    setT(next);
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(s0 + before.length, e0 + before.length); });
  };
  const tools: { label: ReactNode; title: string; run: () => void }[] = [
    { label: <Bold size={15} />, title: "Bold", run: () => wrap("**") },
    { label: <Italic size={15} />, title: "Italic", run: () => wrap("*") },
    { label: <Strikethrough size={15} />, title: "Strikethrough", run: () => wrap("~~") },
    { label: "H1", title: "Heading 1", run: () => wrap("# ", "", true) },
    { label: "H2", title: "Heading 2", run: () => wrap("## ", "", true) },
    { label: "H3", title: "Heading 3", run: () => wrap("### ", "", true) },
    { label: <List size={15} />, title: "Bulleted list", run: () => wrap("- ", "", true) },
    { label: <ListOrdered size={15} />, title: "Numbered list", run: () => wrap("1. ", "", true) },
    { label: <Quote size={15} />, title: "Quote", run: () => wrap("> ", "", true) },
    { label: <Link2 size={15} />, title: "Link", run: () => wrap("[", "](https://)") },
  ];
  return (
    <div className={`flex min-h-[22rem] min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-slate-800 bg-[#08080e] ${full ? "fixed inset-3 z-50 shadow-pop" : ""}`}>
      <div className="flex flex-wrap items-center gap-1 border-b border-slate-800 px-3 py-2">
        <span className="mr-2 rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1 text-xs font-semibold text-slate-300">Markdown</span>
        {tools.map((x) => (
          <button key={x.title} type="button" title={x.title} aria-label={x.title} onClick={x.run}
            className="grid h-8 min-w-8 place-items-center rounded-lg px-1.5 text-xs font-bold text-slate-400 transition hover:bg-slate-300/10 hover:text-slate-100">{x.label}</button>
        ))}
        <span className="ml-auto text-xs text-slate-400">Word count: {words.toLocaleString()} · {lines} lines</span>
        <button type="button" aria-label={full ? "Exit full screen" : "Full screen"} title="Full screen" onClick={() => setFull(!full)}
          className="grid h-8 w-8 place-items-center rounded-lg border border-slate-800 text-slate-300 hover:bg-slate-300/10">{full ? <Minimize2 size={15} /> : <Maximize2 size={15} />}</button>
      </div>
      <div className="flex min-h-0 flex-1">
        <div ref={gutter} aria-hidden className="select-none overflow-hidden border-r border-slate-800/70 px-3 py-3.5 text-right font-mono text-[0.8rem] leading-[1.7] text-slate-600">
          {Array.from({ length: lines }, (_, i) => <div key={i}>{i + 1}</div>)}
        </div>
        <textarea ref={ta} className="min-w-0 flex-1 resize-none bg-transparent px-4 py-3.5 font-mono text-[0.8rem] leading-[1.7] text-[#cfd0e2] outline-none" aria-label={`${fn} contents`} value={t}
          onChange={(e) => setT(e.target.value)} onScroll={(e) => { if (gutter.current) gutter.current.scrollTop = e.currentTarget.scrollTop; }} spellCheck={false} wrap="off" />
      </div>
    </div>
  );
}

/** Parse the headings and the scene list out of Story.md for the preview rail. */
function parseStory(text: string) {
  const lines = text.split("\n");
  const meta = (re: RegExp) => (text.match(re)?.[1] || "").replace(/[*`]/g, "").trim();
  const scenes: { n: string; title: string; seconds: string; desc: string }[] = [];
  const descAfter = (i: number) => { for (let j = i + 1; j < Math.min(lines.length, i + 8); j++) { const l = lines[j].trim(); if (/^#{1,3}\s*(scene|shot)\b/i.test(l)) break; if (l && !l.startsWith("#") && l !== "---") return l.replace(/^[-*\s]+/, "").replace(/\*\*/g, "").replace(/^(visual|action|description)\s*:\s*/i, "").slice(0, 110); } return ""; };
  lines.forEach((l, i) => {
    // "## Scene 01 - Finds the app (5-15s)" | "## Shot 01 - 0:04-0:08" | "### Purpose: HOOK"
    const m = l.match(/^#{2,4}\s*(?:scene|shot)\s*(\d+)\s*[—–-]\s*(.+?)\s*$/i);
    if (m) {
      const rest = m[2].trim();
      const isRange = /^\d{1,2}:\d{2}/.test(rest);
      const secs = rest.match(/\(?(\d+(?:s)?\s*[—–-]\s*\d+s?)\)?\s*$/);
      scenes.push({
        n: String(m[1]).padStart(2, "0"),
        title: isRange ? (lines[i + 1]?.startsWith("###") ? (lines[i + 1].replace(/^#+\s*/, "").split(":").pop() || "Scene").trim() : "Scene") : rest.replace(/\s*\(?\d+s?\s*[—–-]\s*\d+s?\)?\s*$/, "").trim() || "Scene",
        seconds: secs ? secs[1] : isRange ? rest : "",
        desc: descAfter(i),
      });
    } else if (/^#{2,4}\s*scene\b/i.test(l) && lines[i + 1] && !/^#/.test(lines[i + 1])) {
      scenes.push({ n: String(scenes.length + 1).padStart(2, "0"), title: lines[i + 1].replace(/^[-*\s]+/, "").slice(0, 60), seconds: "", desc: "" });
    }
  });
  return {
    title: meta(/\*\*Title:\*\*\s*(.+)/i),
    format: meta(/\*\*Format:\*\*\s*(.+)/i),
    duration: meta(/\*\*Target Duration:\*\*\s*(.+)/i),
    brand: meta(/\*\*Brand:\*\*\s*(.+)/i),
    characters: (text.match(/^\s*-\s*(.+?)(?:\s*—.*)?$/gm) || []).length,
    scenes,
  };
}

export function StoryTab({ o, name, load, openBudget, todoNode }: TabProps) {
  const [msg, setMsg] = useState(""); const [doc, setDoc] = useState<string>("Story.md"); const [story, setStory] = useState("");
  const [tab, setTab] = useState<"preview" | "references" | "notes">("preview");
  const saveRef = useRef<(() => Promise<void>) | null>(null); const [status, setStatus] = useState("");
  const [view, setView] = useState<"visual" | "markdown">("visual"); const [brief, setBrief] = useState<Brief | null>(null);
  useEffect(() => { setView("visual"); }, [doc]);
  useEffect(() => { api<Brief>("GET", `/api/projects/${name}/brief`).then(setBrief).catch(() => {}); }, [name, o]);
  useEffect(() => { if (doc === "Story.md") api<{ text: string }>("GET", `/api/projects/${name}/docs/Story.md`).then((r) => setStory(r.text)).catch(() => {}); }, [name, doc]);
  /** Saving a document refreshes everything built from it; saving Story.md also rebuilds shots, assets and costs, then asks for the budget only if it changed. */
  const afterSave = async () => {
    try {
      if (doc === "Story.md") {
        const worked = o.shots.shots.some((x) => x.final_ok) || o.files.clips.length > 0;
        if (worked && !(await confirmDialog("Saving Story.md also rebuilds the shots and assets from it.\n\nShots you already generated or approved are reset in the list. Clip files stay on disk.", { title: "Save and rebuild shots?", ok: "Save & rebuild", danger: true }))) { load(); return; }
        const before = o.budget.estimate ?? 0;
        const r = await api<any>("POST", `/api/projects/${name}/story/convert`, {});
        setMsg(`Updated: ${r.shots.shots.length} shots, ${r.images.images.length} images.`);
        const est = await api<{ estimate: number }>("POST", `/api/projects/${name}/estimate`, { failure: 0.2 });
        load();
        if (!o.budget.approved || Math.abs(est.estimate - before) > 0.005) openBudget();
      } else load();
    } catch (e: any) { setMsg(e.message); }
  };
  const p = parseStory(story);
  const pics = [...o.images.images.filter((i) => i.kind === "frame"), ...o.images.images.filter((i) => i.kind !== "frame")]
    .map((i) => o.files.stills.find((f) => stem(f) === i.id)).filter((f): f is string => !!f).map((f) => fileUrl(name, `stills/${encodeURIComponent(f)}`));
  /** Latest clip of the shot that matches script scene i, if one has been generated. */
  const clipOf = (i: number) => { const id = o.shots.shots[i]?.id; const c = id ? o.files.clips.filter((f) => f.startsWith(`${id}_final_a`)) : []; return c.length ? fileUrl(name, `clips/${c[c.length - 1]}`) : undefined; };
  const sound = (e: React.SyntheticEvent<HTMLElement>, on: boolean) => { const v = e.currentTarget.querySelector("video"); if (v) { v.muted = !on; if (on) v.play().catch(() => { v.muted = true; }); } };
  return (
    <div className="animate-fade-up">
      <PageBanner title="Storyboard" sub="Turn your idea into a cinematic AI video. Write the story, define the brief and plan tasks. Add scenes, edit prompts, and generate the final video."
        note={<>From idea<br />to final video</>} pics={pics} />

      <PageBody rail={<>
        <RailCard className="!p-0 overflow-hidden">
          <div role="tablist" aria-label="Storyboard preview" className="flex border-b border-slate-800">
            {(["preview", "references", "notes"] as const).map((t) => (
              <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
                className={`flex-1 border-b-2 px-3 py-2.5 text-xs font-bold capitalize transition ${tab === t ? "border-pink text-pink" : "border-transparent text-slate-400 hover:text-slate-100"}`}>{t}</button>
            ))}
          </div>
          <div className="panel-pad">
            {tab === "preview" && (
              <>
                <div className="rounded-2xl border border-slate-800 p-3">
                  <div className="mb-3 flex items-center gap-2"><IconTile tone="pink"><FileText size={15} /></IconTile><span className="text-sm font-bold">Script Summary</span></div>
                  {p.title ? <p className="mb-3 text-xs italic text-slate-400">{p.title}</p> : null}
                  <div className="grid grid-cols-3 gap-2">
                    {[
                      { icon: <Clock size={18} />, value: p.duration ? (p.duration.match(/~?\s*\d+/)?.[0].replace(/\s/g, "") || "45") + "s" : "~45s", label: "Duration" },
                      { icon: <Film size={18} />, value: p.scenes.length, label: "Scenes" },
                      { icon: <Users size={18} />, value: (story.match(/\*\*Characters:\*\*\s*(.+)/i)?.[1] || "").split(",").filter((x) => x.trim()).length, label: "Characters" },
                    ].map((x) => (
                      <div key={x.label} className="panel-quiet flex items-center gap-2 px-2.5 py-2">
                        <span className="text-slate-300">{x.icon}</span>
                        <div className="min-w-0 leading-tight"><div className="text-sm font-extrabold">{x.value}</div><div className="text-[0.65rem] text-slate-400">{x.label}</div></div>
                      </div>
                    ))}
                  </div>
                </div>
                <h4 className="mb-2 mt-4 text-xs font-bold text-slate-300">Key Frames <span className="font-normal text-slate-400">(from script)</span></h4>
                <ul className="space-y-1.5">
                  {p.scenes.map((s, i) => (
                    <li key={s.n} onMouseEnter={(e) => sound(e, true)} onMouseLeave={(e) => sound(e, false)} className="row-hover flex items-stretch overflow-hidden rounded-xl border border-slate-800">
                      <div className="relative h-16 w-24 shrink-0 bg-slate-900">
                        {clipOf(i) ? <video src={clipOf(i)} poster={pics[i]} autoPlay loop muted playsInline preload="metadata" className="h-full w-full object-cover" /> : pics[i] && <img src={pics[i]} alt="" className="h-full w-full object-cover" loading="lazy" />}
                        <span className="absolute left-1.5 top-1.5 rounded-md bg-black/70 px-1.5 text-[0.65rem] font-bold">{s.n}</span>
                        {s.seconds && <span className="absolute right-1 top-1.5 rounded-md bg-black/70 px-1.5 text-[0.62rem] font-semibold">{s.seconds}</span>}
                      </div>
                      <div className="min-w-0 flex-1 px-2.5 py-1.5">
                        <div className="truncate text-xs font-semibold">{s.title}</div>
                        {s.desc && <div className="line-clamp-2 text-[0.68rem] leading-snug text-slate-400">{s.desc}</div>}
                      </div>
                    </li>
                  ))}
                  {!p.scenes.length && <li className="text-xs text-slate-400">No scenes found in the script yet.</li>}
                </ul>
                <Link to={`/p/${name}/shots`} className="btn btn-outline mt-3 w-full"><Play size={14} />Play Full Preview</Link>
              </>
            )}
            {tab === "references" && (
              <>
                <div className="mb-2 flex items-center gap-2"><IconTile tone="sky"><Braces size={15} /></IconTile><span className="text-sm font-bold">References</span></div>
                <dl className="kv">
                  <dt>Brand</dt><dd>{p.brand || "not set"}</dd>
                  <dt>Format</dt><dd>{p.format || "not set"}</dd>
                </dl>
                <dl className="kv mt-1"><dt>Voice</dt><dd>{brief ? voiceLanguages(brief.fields) || "not chosen" : "..."}</dd></dl>
                <p className="mt-1 text-[0.7rem] text-slate-400">Change the languages in brief.md (Visual editor).</p>
                <p className="mt-3 text-[0.7rem] leading-relaxed text-slate-400">Character sheets and backgrounds you add on the Assets tab become the reference images used when the clips are generated.</p>
              </>
            )}
            {tab === "notes" && (
              <>
                <div className="mb-2 flex items-center gap-2"><IconTile><FileText size={15} /></IconTile><span className="text-sm font-bold">Notes</span></div>
                <p className="text-xs leading-relaxed text-slate-400">Keep direction here: what the AI must not invent, which lines are spoken, and where the logo or the on-screen text goes.</p>
              </>
            )}
          </div>
        </RailCard>
        <RailCard title="Verification"><VerifyBar scope="story" label="Story" /></RailCard>
      </>} stickyMain>
        <div className="panel panel-lit panel-pad flex flex-col xl:h-full">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div role="tablist" aria-label="Project documents" className="flex flex-wrap gap-2">
              {DOCS.map((d) => {
                const Icon = d.icon;
                return (
                  <button key={d.fn} type="button" role="tab" aria-selected={doc === d.fn} onClick={() => setDoc(d.fn)} title={d.hint}
                    className={`pill !px-4 !py-2.5 ${doc === d.fn ? "" : "!bg-slate-900"}`}>
                    <Icon size={17} />
                    <span className="flex flex-col items-start leading-tight">
                      <span className="text-sm">{d.fn}</span>
                      <span className={`text-[0.65rem] font-medium ${doc === d.fn ? "text-white/70" : "text-slate-400"}`}>{d.sub}</span>
                    </span>
                  </button>
                );
              })}
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs text-emerald-400" role="status">{status}</span>
              <Button variant="pink" onClick={() => saveRef.current?.()}><Save size={15} />Save</Button>
            </div>
          </div>
          {msg && <p className="mb-3 text-sm text-brand">{msg}</p>}
          {doc !== "Story.md" && (
            <div role="tablist" aria-label="Editor type" className="mb-3 flex w-fit gap-1 rounded-xl border border-slate-800 bg-slate-900/60 p-1">
              {(["visual", "markdown"] as const).map((v) => (
                <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)}
                  className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${view === v ? "is-active" : "text-slate-400 hover:text-slate-100"}`}>{v === "visual" ? "Visual editor" : "Markdown"}</button>
              ))}
            </div>
          )}
          {doc === "brief.md" && view === "visual" ? (
            <div className="min-h-0 flex-1 overflow-auto pr-1"><BriefForm name={name} brief={brief} onSaved={afterSave} saveRef={saveRef} onStatus={setStatus} showSave={false} /></div>
          ) : doc === "TODO.md" && view === "visual" ? (
            <div className="min-h-0 flex-1 overflow-auto pr-1">{(saveRef.current = async () => { setStatus("Saved"); setTimeout(() => setStatus(""), 1500); load(); }, todoNode)}</div>
          ) : (
            <DocEditor key={doc} name={name} fn={doc} rev={o} onSaved={afterSave} saveRef={saveRef} onStatus={setStatus} />
          )}
        </div>
      </PageBody>
    </div>
  );
}


/* ---------------------------------------------------------------------- assets */

export const KINDS = [
  { kind: "character", title: "Characters", sub: "Main people and subjects in your story.", hint: "One sheet per person: full-body views and expressions. Faces in later scenes are built from these.", idHint: "ramesh_sheet", icon: "characters" },
  { kind: "background", title: "Backgrounds", sub: "Places, locations and environments.", hint: "Each place, empty (no people). Make a busy and an empty version if the story contrasts them.", idHint: "shop_empty" },
  { kind: "frame", title: "Scene Frames", sub: "Reference frames for consistent visuals.", hint: "One per shot: a character in a background, vertical 9:16. Pick the character and background as references.", idHint: "s01" },
  { kind: "other", title: "Uploads", sub: "Files you keep with the project.", hint: "Files such as the logo for the editor. They are not used to generate video.", idHint: "logo" },
] as const;

export function ImportStills({ project, found, reload }: { project: string; found: FoundStill[]; reload: () => void }) {
  const toast = useToast();
  const [rows, setRows] = useState(() => found.map((f) => ({ ...f, id: f.suggested_id, kind: f.suggested_kind, on: true })));
  useEffect(() => { setRows(found.map((f) => ({ ...f, id: f.suggested_id, kind: f.suggested_kind, on: true }))); }, [found]);
  const [busy, setBusy] = useState(false);
  const chosen = rows.filter((r) => r.on);
  const go = async () => {
    if (!(await confirmDialog(`Add ${chosen.length} image(s) to the asset list?\n\nEach file is renamed to its asset id (for example "Ramesh Shop.png" becomes "ramesh_shop.png") so the id and the file match. Nothing is deleted, and shots that use a renamed file are updated.`, { title: "Add images", ok: "Add" }))) return;
    setBusy(true);
    try { await api("POST", `/api/projects/${project}/stills/import`, { items: chosen.map((r) => ({ file: r.file, id: r.id.trim(), kind: r.kind })) }); toast("ok", `Added ${chosen.length} image(s) to the asset list.`); reload(); }
    catch (e: any) { toast("error", e.message); } finally { setBusy(false); }
  };
  return (
    <Card title={`Found ${found.length} image${found.length > 1 ? "s" : ""} in this project's stills folder that are not in the asset list`} className="!border-amber-400/60"
      right={<Button size="sm" onClick={go} disabled={busy || !chosen.length}>{busy ? <Spinner size={13} /> : null} Add {chosen.length} to the list</Button>}>
      <p className="mb-3 text-xs text-slate-400">These files exist on disk but the Assets list does not know about them. Check the suggested id and category, then add them.</p>
      <div className="mb-2 flex gap-3 text-xs">
        <button type="button" className="text-brand hover:underline" onClick={() => setRows(rows.map((r) => ({ ...r, on: true })))}>Select all</button>
        <button type="button" className="text-brand hover:underline" onClick={() => setRows(rows.map((r) => ({ ...r, on: false })))}>Select none</button>
      </div>
      <ul className="grid gap-2 md:grid-cols-2">
        {rows.map((r, i) => (
          <li key={r.file} className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-950/40 p-2">
            <input type="checkbox" checked={r.on} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, on: e.target.checked } : x))} aria-label={`Add ${r.file}`} />
            <img src={fileUrl(project, `stills/${encodeURIComponent(r.file)}`)} className="h-16 w-12 shrink-0 rounded object-cover" alt="" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs text-slate-400" title={r.file}>{r.file}{r.used_by_shots ? " · used by a shot" : ""}</div>
              <div className="mt-1 flex gap-1">
                <Input className="min-w-0 flex-1 !py-1 font-mono text-xs" value={r.id} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, id: e.target.value } : x))} aria-label={`Asset id for ${r.file}`} />
                <Select className="!w-auto !py-1 text-xs" value={r.kind} aria-label={`Category for ${r.file}`}
                  onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, kind: e.target.value as ImageSpec["kind"] } : x))}>
                  <option value="character">character</option><option value="background">background</option><option value="frame">scene frame</option><option value="other">other</option>
                </Select>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export const ID_OK = /^[a-z0-9][a-z0-9_-]{0,40}$/;

/* ----------------------------------------------------------------------- shots */

/* ----------------------------------------------------------------------- costs */

export function CostsTab({ o, name, load }: TabProps) {
  const [f, setF] = useState("0.2"); const [rows, setRows] = useState<any[]>([]); const [msg, setMsg] = useState("");
  const [tab, setTab] = useState<"generations" | "models">("generations");
  useEffect(() => { api<any>("GET", `/api/projects/${name}/costs`).then((r) => setRows(r.rows)).catch(() => {}); }, [name, o.costs.total]);
  const est = async () => { try { await api("POST", `/api/projects/${name}/estimate`, { failure: Number(f) }); setMsg("Estimated. Approve it below to allow spending."); load(); } catch (e: any) { setMsg(e.message); } };
  const appr = async () => { if (!(await confirmDialog(`Approve a budget of ${money(o.budget.estimate)} (stop-loss ${money(o.budget.stop_loss)})?`, { title: "Approve budget", ok: "Approve" }))) return; await api("POST", `/api/projects/${name}/budget/approve`); load(); };

  // Spending by day, for the trend chart.
  const byDay = new Map<string, number>();
  rows.forEach((r) => { const d = String(r.timestamp || "").slice(5, 10); if (d) byDay.set(d, (byDay.get(d) || 0) + Number(r.cost || 0)); });
  const days = [...byDay.entries()].sort((a, b) => a[0].localeCompare(b[0])).slice(-14);
  const peak = Math.max(0.0001, ...days.map(([, v]) => v));

  return (
    <div className="animate-fade-up">
      <PageHeader title="Costs" sub="Track your token usage, video generation costs, and manage your budget." icon={<Wallet size={24} />} art="/costs-banner.png" />

      <PageBody rail={<>
        <RailCard title={<span className="flex items-center gap-2"><IconTile tone="lime"><Wallet size={14} /></IconTile> Budget &amp; Limits</span>} right={<Badge tone={o.budget.approved ? "green" : "amber"}>{o.budget.approved ? "approved" : "not approved"}</Badge>}>
          <p className="text-xs text-slate-400">Monthly budget</p>
          <div className="mt-1 flex items-baseline gap-1">
            <span className="text-2xl font-extrabold">{money(o.budget.estimate)}</span>
            <span className="text-xs text-slate-400">stop-loss {money(o.budget.stop_loss)}</span>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <StatTile value={money(o.costs.used)} label="Used" tone="text-pink" />
            <StatTile value={money(o.costs.total - o.costs.used)} label="Remaining" tone="text-brand" />
            <StatTile value={money(o.budget.estimate)} label="Limit" tone="text-sky" />
          </div>
          <div className="mt-3 flex items-center gap-2">
            <Input className="!w-24" aria-label="Retry allowance" value={f} onChange={(e) => setF(e.target.value)} />
            <Button variant="outline" size="sm" className="flex-1" onClick={est}>Estimate</Button>
          </div>
          {!!o.budget.estimate && !o.budget.approved && <Button size="sm" className="mt-2 w-full" onClick={appr}>Approve budget</Button>}
        </RailCard>
        <RailCard title={<span className="flex items-center gap-2"><IconTile tone="pink"><Wallet size={14} /></IconTile> Recent transactions</span>} right={<Badge>{rows.length}</Badge>}>
          <ul className="space-y-2">
            {[...rows].slice(0, 6).map((r, i) => (
              <li key={i} className="flex items-center justify-between gap-2 text-xs">
                <IconTile tone={modelTone(r.model)}>{r.stage === "image" ? <ImageIcon size={14} /> : <VideoIcon size={14} />}</IconTile>
                <div className="min-w-0 flex-1">
                  <div className="truncate font-semibold text-slate-200">{r.shot || r.stage}</div>
                  <div className="truncate text-slate-400">{String(r.model || "").split("/").pop()} · {r.result}</div>
                </div>
                <span className="shrink-0 font-bold">{money(Number(r.cost || 0))}</span>
              </li>
            ))}
            {!rows.length && <li className="text-xs text-slate-400">Nothing spent yet.</li>}
          </ul>
        </RailCard>
      </>}>
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              { tile: "pink" as TileTone, icon: <DollarSign size={20} />, label: "Total Spend", value: money(o.costs.total), sub: `of ${money(o.budget.estimate)}`, tone: "" },
              { tile: "violet" as TileTone, icon: <VideoIcon size={20} />, label: "Videos Generated", value: o.files.clips.length, sub: `of ${o.shots.shots.length} planned`, tone: "" },
              { tile: "sky" as TileTone, icon: <Tag size={20} />, label: "Avg. Cost per Video", value: money(o.files.clips.length ? o.costs.total / o.files.clips.length : 0), sub: "per clip", tone: "text-sky" },
              { tile: "amber" as TileTone, icon: <TrendingDown size={20} />, label: "Discarded", value: money(o.costs.discarded), sub: "wasted spend", tone: "text-amber-400" },
            ].map((c) => (
              <Card key={c.label}>
                <div className="flex items-center gap-3">
                  <IconTile tone={c.tile} size="lg">{c.icon}</IconTile>
                  <div className="min-w-0">
                    <div className="text-xs font-semibold text-slate-300">{c.label}</div>
                    <div className={`text-2xl font-extrabold leading-tight tracking-tight ${c.tone}`}>{c.value}</div>
                    <div className="text-[0.7rem] text-slate-400">{c.sub}</div>
                  </div>
                </div>
              </Card>
            ))}
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <Card title={<span className="flex items-center gap-2.5"><IconTile tone="violet" size="lg"><BarChart3 size={20} /></IconTile>Spending Trend</span>} sub="Daily usage and cost breakdown">
              {days.length ? (
                <div className="flex h-44 items-stretch gap-2 pt-4">
                  {days.map(([d, v], bi) => (
                    <div key={d} className="flex h-full min-w-0 flex-1 flex-col justify-end gap-1.5">
                      <span className="text-center text-[0.6rem] text-slate-400">{money(v)}</span>
                      <div className={`w-full rounded-t-md bg-gradient-to-t ${["from-pink to-orange","from-violet to-pink","from-sky to-violet"][bi % 3]}`} style={{ height: `${Math.max(4, (v / peak) * 100)}%` }} />
                      <span className="truncate text-center text-[0.6rem] text-slate-400">{dayLabel(d)}</span>
                    </div>
                  ))}
                </div>
              ) : <p className="py-10 text-center text-sm text-slate-400">Nothing spent yet.</p>}
            </Card>

            <Card title={<span className="flex items-center gap-2.5"><IconTile tone="lime" size="lg"><PieChart size={20} /></IconTile>Spend: used vs discarded</span>}>
              <div className="flex items-center gap-4 py-4">
                <DonutChart used={o.costs.used} discarded={o.costs.discarded} />
                <ul className="min-w-0 flex-1 space-y-2 text-xs">
                  <li className="flex items-center justify-between gap-2"><span className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-brand" />Used</span><b>{money(o.costs.used)}</b></li>
                  <li className="flex items-center justify-between gap-2"><span className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-pink" />Discarded</span><b>{money(o.costs.discarded)}</b></li>
                  <li className="divider !my-2" />
                  <li className="flex items-center justify-between gap-2 font-bold"><span>Total</span><span>{money(o.costs.total)}</span></li>
                </ul>
              </div>
            </Card>
          </div>

          <section className="panel panel-lit panel-pad" aria-label="Cost log">
            <div role="tablist" aria-label="Cost breakdown" className="mb-4 flex flex-wrap gap-2">
              {(["generations", "models"] as const).map((t) => (
                <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
                  className={`pill capitalize ${tab === t ? "" : "!bg-slate-900"}`}>{t === "models" ? "Model Usage" : "Generations"}</button>
              ))}
            </div>

            {tab !== "generations" ? (
              <UsageBreakdown rows={rows} />
            ) : (
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead><tr><th>#</th><th>Preview</th><th>Scene / Prompt</th><th>Model</th><th>Duration</th><th className="text-right">Cost</th><th>Result</th><th>Date</th></tr></thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={i}>
                        <td className="font-mono text-slate-400">{String(i + 1).padStart(2, "0")}</td>
                        <td><CostPreview project={name} r={r} /></td>
                        <td className="max-w-[16rem] truncate font-semibold">{r.shot || r.stage}</td>
                        <td><span className={`tag ${modelTag(r.model)}`}>{String(r.model || "").split("/").pop()}</span></td>
                        <td className="text-slate-400">{r.seconds ? `${r.seconds}.0s` : "—"}</td>
                        <td className="text-right font-bold">{money(Number(r.cost || 0))}</td>
                        <td><Badge tone={r.result === "completed" || r.result === "done" || r.result === "ok" ? "green" : r.result === "error" || r.result === "failed" ? "red" : "amber"}>{r.result}</Badge></td>
                        <td className="whitespace-nowrap text-slate-400">{fmtDate(r.timestamp)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!rows.length && <p className="py-6 text-center text-sm text-slate-400">Nothing spent yet.</p>}
              </div>
            )}
            {msg && <p className="mt-3 text-xs text-brand">{msg}</p>}
            <p className="mt-3 text-[0.7rem] text-slate-400">Nothing can be generated until the budget is approved. Changing shots or images means estimating and approving again.</p>
          </section>
        </div>
      </PageBody>
    </div>
  );
}

const MODEL_TONES: TileTone[] = ["pink", "violet", "sky", "amber", "lime"];
const MODEL_TAGS = ["tag-grad", "tag-violet", "tag-sky", "tag-amber", "tag-lime"];
const modelIdx = (m?: string) => { const k = String(m || ""); let h = 0; for (const c of k) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h % MODEL_TONES.length; };
const modelTone = (m?: string) => MODEL_TONES[modelIdx(m)];
const modelTag = (m?: string) => MODEL_TAGS[modelIdx(m)];
const dayLabel = (d: string) => { const [m, day] = d.split("-"); return `${day} ${["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][Number(m) - 1] || m}`; };

/** Thumbnail of what a log row produced: first frame of the clip, or the still. Falls back to an icon. */
function CostPreview({ project, r }: { project: string; r: any }) {
  const [bad, setBad] = useState(false);
  const isImg = r.stage === "image"; const isClip = r.stage === "final";
  const icon = isImg ? <ImageIcon size={16} /> : <VideoIcon size={16} />;
  if (bad || (!isImg && !isClip)) return <div className="thumb grid h-10 w-16 place-items-center text-slate-500">{icon}</div>;
  return (
    <div className="thumb h-10 w-16">
      {isImg
        ? <img src={fileUrl(project, `stills/${r.shot}.png`)} alt="" loading="lazy" onError={() => setBad(true)} />
        : <video src={`${fileUrl(project, `clips/${r.shot}_final_a${r.attempt}.mp4`)}#t=0.5`} preload="metadata" muted playsInline onError={() => setBad(true)} />}
    </div>
  );
}

/** A two-slice ring: used vs discarded. */
function DonutChart({ used, discarded }: { used: number; discarded: number }) {
  const total = used + discarded; const pct = total ? discarded / total : 0;
  const r = 20; const c = 2 * Math.PI * r;
  return (
    <svg width="86" height="86" viewBox="0 0 48 48" role="img" aria-label={`Used ${money(used)}, discarded ${money(discarded)}`} className="shrink-0">
      <circle cx="24" cy="24" r={r} fill="none" stroke="#d7ff3f" strokeWidth="7" strokeDasharray={`${c * (1 - pct)} ${c}`} transform="rotate(-90 24 24)" />
      <circle cx="24" cy="24" r={r} fill="none" stroke="#ff2d95" strokeWidth="7" strokeDasharray={`${c * pct} ${c}`} strokeDashoffset={-c * (1 - pct)} transform="rotate(-90 24 24)" />
      <text x="24" y="26" textAnchor="middle" className="fill-white" style={{ fontSize: "9px", fontWeight: "700" }}>{money(total)}</text>
    </svg>
  );
}

/** "Model Usage": group the log rows by model and show a share bar per key. */
function UsageBreakdown({ rows }: { rows: any[] }) {
  const groups = new Map<string, number>();
  rows.forEach((r) => {
    const k = (r.provider ? `${r.provider} · ` : "") + String(r.model || "unknown").split("/").pop()!;
    groups.set(k, (groups.get(k) || 0) + Number(r.cost || 0));
  });
  const list = [...groups.entries()].sort((a, b) => b[1] - a[1]);
  const total = list.reduce((n, [, v]) => n + v, 0) || 1;
  if (!list.length) return <p className="py-8 text-center text-sm text-slate-400">Nothing spent yet.</p>;
  return (
    <ul className="space-y-2.5">
      {list.map(([k, v]) => (
        <li key={k}>
          <div className="mb-1 flex items-center justify-between gap-2 text-xs">
            <span className="truncate font-semibold">{k}</span>
            <span className="shrink-0 text-slate-400">{money(v)} · {Math.round((v / total) * 100)}%</span>
          </div>
          <div className="progress"><div className="progress-fill" style={{ width: `${(v / total) * 100}%` }} /></div>
        </li>
      ))}
    </ul>
  );
}

/* ------------------------------------------------------------------ discarded */

export function DiscardedTab({ o, name, load }: TabProps) {
  const [msg, setMsg] = useState("");
  const [kind, setKind] = useState<"all" | "clips" | "stills" | "other">("all");
  const [sort, setSort] = useState<"new" | "old" | "cost">("new");
  const [picked, setPicked] = useState<Set<string>>(new Set()); const [playing, setPlaying] = useState<string | null>(null);
  const restore = async (rel: string) => { try { await api("POST", `/api/projects/${name}/restore`, { rel }); load(); } catch (e: any) { setMsg(e.message); } };
  const restoreMany = async () => {
    for (const rel of picked) { try { await api("POST", `/api/projects/${name}/restore`, { rel }); } catch (e: any) { setMsg(e.message); } }
    setPicked(new Set()); load();
  };
  const kindOf = (d: typeof o.discarded[number]) => (d.file.startsWith("clips/") ? "clips" : d.file.startsWith("stills/") ? "stills" : "other");
  const shown = o.discarded.filter((d) => kind === "all" || kindOf(d) === kind)
    .sort((a, b) => (sort === "cost" ? b.cost - a.cost : sort === "old" ? String(a.when).localeCompare(String(b.when)) : String(b.when).localeCompare(String(a.when))));
  const toggle = (rel: string) => setPicked((s) => { const n = new Set(s); n.has(rel) ? n.delete(rel) : n.add(rel); return n; });
  const reasonTag = (r: string) => { let h = 0; for (const c of r) h = (h * 31 + c.charCodeAt(0)) >>> 0; return ["tag-red", "tag-amber", "tag-violet", "tag-sky", "tag-emerald"][h % 5]; };
  const tabs = [
    { id: "all", label: "All", icon: <Trash2 size={15} /> }, { id: "clips", label: "Videos", icon: <VideoIcon size={15} /> },
    { id: "stills", label: "Images", icon: <ImageIcon size={15} /> }, { id: "other", label: "Prompts & assets", icon: <FileText size={15} /> },
  ] as const;

  return (
    <div className="animate-fade-up">
      <PageHeader title="Discarded" sub="Items you removed or didn't use. You can restore them anytime." icon={<Trash2 size={24} />} art="/discarded-banner.png" />

      <div className="space-y-4">
        <div className="panel flex flex-wrap items-center gap-2 p-3">
          <div role="tablist" aria-label="Filter discarded files" className="flex flex-wrap gap-2">
            {tabs.map((t) => {
              const on = kind === t.id; const n = t.id === "all" ? o.discarded.length : o.discarded.filter((d) => kindOf(d) === t.id).length;
              return (
                <button key={t.id} type="button" role="tab" aria-selected={on} onClick={() => setKind(t.id)}
                  className={`pill !px-4 !py-2.5 ${on ? "!border-pink/70 !bg-pink/10 !text-white !bg-none shadow-glow-pink" : "!bg-slate-900"}`}>
                  {t.icon}{t.label}<span className={`rounded-lg px-1.5 text-[0.72rem] ${on ? "bg-pink/30" : "bg-white/10"}`}>{n}</span>
                </button>
              );
            })}
          </div>
          <span className="flex-1" />
          {picked.size > 0 && <Button variant="outline" size="sm" onClick={restoreMany}><RotateCcw size={13} />Restore {picked.size} selected</Button>}
          <Select aria-label="Sort discarded files" className="!w-40 !py-2" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
            <option value="new">Newest first</option><option value="old">Oldest first</option><option value="cost">Highest cost</option>
          </Select>
        </div>

        {msg && <p className="text-sm text-red-400" role="alert">{msg}</p>}

        <div className="panel panel-lit overflow-hidden">
          {shown.map((d) => {
            const k = kindOf(d); const fileName = d.file.split("/").pop() || d.file;
            return (
              <div key={d.file} className="row-hover grid grid-cols-[auto_auto_minmax(0,1fr)] items-center gap-x-4 gap-y-2 border-b border-slate-800 px-4 py-3 last:border-0 lg:grid-cols-[auto_auto_minmax(0,1.3fr)_minmax(0,1fr)_9rem_auto]">
                <input type="checkbox" aria-label={`Select ${fileName}`} checked={picked.has(d.file)} onChange={() => toggle(d.file)} className="h-4 w-4 accent-pink" />
                <div className="thumb h-[4.5rem] w-32 shrink-0">
                  {k === "stills" ? <img src={fileUrl(name, d.file)} alt="" loading="lazy" />
                    : k === "clips" ? <>
                        <video src={`${fileUrl(name, d.file)}#t=0.5`} preload="metadata" muted playsInline />
                        <button type="button" aria-label={`Play ${fileName}`} onClick={() => setPlaying(d.file)}
                          className="absolute inset-0 grid place-items-center bg-black/20 transition hover:bg-black/40">
                          <span className="grid h-9 w-9 place-items-center rounded-full border border-white/40 bg-black/60 text-white"><Play size={16} fill="currentColor" /></span>
                        </button>
                      </>
                    : <div className="grid h-full place-items-center text-violet"><FileText size={22} /></div>}
                </div>
                <div className="min-w-0">
                  <div className="truncate text-sm font-bold">{d.original || fileName}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-slate-400">
                    {k === "clips" ? <VideoIcon size={13} /> : k === "stills" ? <ImageIcon size={13} /> : <FileText size={13} />}
                    <span>{k === "clips" ? "Video" : k === "stills" ? "Image" : "File"}</span><span aria-hidden>•</span><span>{money(d.cost)}</span>
                  </div>
                </div>
                <div className="col-span-3 min-w-0 lg:col-span-1">
                  <p className="mb-1 text-xs text-slate-400">Discarded reason</p>
                  <span className={`tag ${reasonTag(d.reason || "")} !max-w-full`}>{d.reason || "no reason given"}</span>
                </div>
                <div className="text-xs text-slate-400">{fmtDate(d.when)}</div>
                <Button variant="outline" size="sm" onClick={() => restore(d.file)}><RotateCcw size={13} />Restore</Button>
              </div>
            );
          })}
          {!shown.length && <EmptyState title="Nothing discarded" text="Replaced or unwanted files will appear here, with their reason and cost." icon={<RotateCcw size={20} />} />}
        </div>

        <Modal open={!!playing} onClose={() => setPlaying(null)} title={playing?.split("/").pop() || ""}>
          {playing && <video key={playing} src={fileUrl(name, playing)} controls autoPlay className="mx-auto max-h-[70vh] w-full rounded-lg bg-black" />}
        </Modal>

        <p className="text-[0.7rem] text-slate-400">Nothing is ever deleted: {money(o.discarded.reduce((n, d) => n + d.cost, 0))} of spend sits in {o.discarded.length} discarded files. Replaced or bad files keep their reason and cost and can be restored at any time.</p>
      </div>
    </div>
  );
}
