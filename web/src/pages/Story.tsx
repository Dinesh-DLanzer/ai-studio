import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Bold,
  Braces,
  Clock,
  Eye,
  FileCode2,
  FileText,
  Film,
  Italic,
  Link2,
  List,
  ListChecks,
  ListOrdered,
  Maximize2,
  Minimize2,
  Play,
  Quote,
  Save,
  Strikethrough,
  Users,
} from "lucide-react";
import { api, fileUrl } from "../api";
import { Button, IconTile } from "../ui";
import { confirmDialog } from "../dialogs";
import { VerifyBar } from "../Verify";
import BriefForm, { voiceLanguages } from "../BriefForm";
import { PageBody } from "../app/Shell";
import { PageBanner, RailCard } from "../components/kit";
import { stem, type TabProps } from "../ProjectPage";
import type { Brief } from "../types";
import {
  StoryDocumentView,
  parseStoryDocument,
  exportStoryToPdf,
} from "./StoryDocumentView";

const DOCS = [
  { fn: "Story.md", sub: "Screenplay document & scenes", label: "Story", icon: FileCode2, hint: "The full script: scenes, voice lines and on-screen text." },
  { fn: "brief.md", sub: "Visual editor (required fields)", label: "Brief", icon: ListChecks, hint: "Required fields the verification checks." },
  { fn: "TODO.md", sub: "Task list (auto-generated)", label: "TODO", icon: FileText, hint: "The task list, generated from the story." },
] as const;

export function DocEditor({
  name,
  fn,
  initialText,
  onChange,
  onSaved,
  saveRef,
  onStatus,
  rev,
}: {
  name: string;
  fn: string;
  initialText?: string;
  onChange?: (val: string) => void;
  rev?: unknown;
  onSaved?: () => void | Promise<void>;
  saveRef: React.MutableRefObject<(() => Promise<void>) | null>;
  onStatus: (s: string) => void;
}) {
  const [t, setT] = useState(initialText ?? "");
  const [full, setFull] = useState(false);
  const ta = useRef<HTMLTextAreaElement>(null);
  const gutter = useRef<HTMLDivElement>(null);
  const loaded = useRef<string | null>(initialText ?? null);

  useEffect(() => {
    if (initialText !== undefined && loaded.current !== null && t === initialText) return;
    if (loaded.current !== null && t !== loaded.current) return;
    api<{ text: string }>("GET", `/api/projects/${name}/docs/${fn}`)
      .then((r) => {
        loaded.current = r.text;
        setT(r.text);
        onChange?.(r.text);
      })
      .catch(() => setT(""));
    /* eslint-disable-next-line */
  }, [name, fn, rev]);

  const updateText = (next: string) => {
    setT(next);
    onChange?.(next);
  };

  const save = async () => {
    loaded.current = t;
    await api("PUT", `/api/projects/${name}/docs/${fn}`, { text: t });
    onStatus("Saved");
    setTimeout(() => onStatus(""), 1500);
    await onSaved?.();
  };
  saveRef.current = save;
  const words = t.trim() ? t.trim().split(/\s+/).length : 0;
  const lines = t ? t.split("\n").length : 1;

  const wrap = (before: string, after = before, linePrefix = false) => {
    const el = ta.current;
    if (!el) return;
    const { selectionStart: s0, selectionEnd: e0 } = el;
    let next: string;
    if (linePrefix) {
      const start = t.lastIndexOf("\n", s0 - 1) + 1;
      next = t.slice(0, start) + t.slice(start, e0).split("\n").map((l) => before + l).join("\n") + t.slice(e0);
    } else next = t.slice(0, s0) + before + t.slice(s0, e0) + after + t.slice(e0);
    updateText(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(s0 + before.length, e0 + before.length);
    });
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
          <button
            key={x.title}
            type="button"
            title={x.title}
            aria-label={x.title}
            onClick={x.run}
            className="grid h-8 min-w-8 place-items-center rounded-lg px-1.5 text-xs font-bold text-slate-400 transition hover:bg-slate-300/10 hover:text-slate-100"
          >
            {x.label}
          </button>
        ))}
        <span className="ml-auto text-xs text-slate-400">
          Word count: {words.toLocaleString()} · {lines} lines
        </span>
        <button
          type="button"
          aria-label={full ? "Exit full screen" : "Full screen"}
          title="Full screen"
          onClick={() => setFull(!full)}
          className="grid h-8 w-8 place-items-center rounded-lg border border-slate-800 text-slate-300 hover:bg-slate-300/10"
        >
          {full ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
        </button>
      </div>
      <div className="flex min-h-0 flex-1">
        <div ref={gutter} aria-hidden className="select-none overflow-hidden border-r border-slate-800/70 px-3 py-3.5 text-right font-mono text-[0.8rem] leading-[1.7] text-slate-600">
          {Array.from({ length: lines }, (_, i) => (
            <div key={i}>{i + 1}</div>
          ))}
        </div>
        <textarea
          ref={ta}
          className="min-w-0 flex-1 resize-none bg-transparent px-4 py-3.5 font-mono text-[0.8rem] leading-[1.7] text-[#cfd0e2] outline-none"
          aria-label={`${fn} contents`}
          value={t}
          onChange={(e) => updateText(e.target.value)}
          onScroll={(e) => {
            if (gutter.current) gutter.current.scrollTop = e.currentTarget.scrollTop;
          }}
          spellCheck={false}
          wrap="off"
        />
      </div>
    </div>
  );
}

export function parseStory(text: string) {
  const lines = text.split("\n");
  const meta = (re: RegExp) => (text.match(re)?.[1] || "").replace(/[*`]/g, "").trim();
  const scenes: { n: string; title: string; seconds: string; desc: string }[] = [];
  const descAfter = (i: number) => {
    for (let j = i + 1; j < Math.min(lines.length, i + 8); j++) {
      const l = lines[j].trim();
      if (/^#{1,3}\s*(scene|shot)\b/i.test(l)) break;
      if (l && !l.startsWith("#") && l !== "---")
        return l
          .replace(/^[-*\s]+/, "")
          .replace(/\*\*/g, "")
          .replace(/^(visual|action|description)\s*:\s*/i, "")
          .slice(0, 110);
    }
    return "";
  };
  lines.forEach((l, i) => {
    const m = l.match(/^#{2,4}\s*(?:scene|shot)\s*(\d+)\s*[—–-]\s*(.+?)\s*$/i);
    if (m) {
      const rest = m[2].trim();
      const isRange = /^\d{1,2}:\d{2}/.test(rest);
      const secs = rest.match(/\(?(\d+(?:s)?\s*[—–-]\s*\d+s?)\)?\s*$/);
      scenes.push({
        n: String(m[1]).padStart(2, "0"),
        title: isRange
          ? (lines[i + 1]?.startsWith("###") ? (lines[i + 1].replace(/^#+\s*/, "").split(":").pop() || "Scene").trim() : "Scene")
          : rest.replace(/\s*\(?\d+s?\s*[—–-]\s*\d+s?\)?\s*$/, "").trim() || "Scene",
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
  const [msg, setMsg] = useState("");
  const [doc, setDoc] = useState<string>("Story.md");
  const [story, setStory] = useState("");
  const [tab, setTab] = useState<"preview" | "references" | "notes">("preview");
  const saveRef = useRef<(() => Promise<void>) | null>(null);
  const [status, setStatus] = useState("");
  const [view, setView] = useState<"visual" | "markdown">("visual");
  const [brief, setBrief] = useState<Brief | null>(null);

  useEffect(() => {
    setView("visual");
  }, [doc]);

  useEffect(() => {
    api<Brief>("GET", `/api/projects/${name}/brief`).then(setBrief).catch(() => {});
  }, [name, o]);

  useEffect(() => {
    if (doc === "Story.md") {
      api<{ text: string }>("GET", `/api/projects/${name}/docs/Story.md`)
        .then((r) => setStory(r.text))
        .catch(() => {});
    }
  }, [name, doc]);

  const afterSave = async () => {
    try {
      if (doc === "Story.md") {
        const worked = o.shots.shots.some((x) => x.final_ok) || o.files.clips.length > 0;
        if (
          worked &&
          !(await confirmDialog(
            "Saving Story.md also rebuilds the shots and assets from it.\n\nShots you already generated or approved are reset in the list. Clip files stay on disk.",
            { title: "Save and rebuild shots?", ok: "Save & rebuild", danger: true }
          ))
        ) {
          load();
          return;
        }
        const before = o.budget.estimate ?? 0;
        const r = await api<any>("POST", `/api/projects/${name}/story/convert`, {});
        setMsg(`Updated: ${r.shots.shots.length} shots, ${r.images.images.length} images.`);
        const est = await api<{ estimate: number }>("POST", `/api/projects/${name}/estimate`, { failure: 0.2 });
        load();
        if (!o.budget.approved || Math.abs(est.estimate - before) > 0.005) openBudget();
      } else load();
    } catch (e: any) {
      setMsg(e.message);
    }
  };

  const p = parseStory(story);
  const pics = [...o.images.images.filter((i) => i.kind === "frame"), ...o.images.images.filter((i) => i.kind !== "frame")]
    .map((i) => o.files.stills.find((f) => stem(f) === i.id))
    .filter((f): f is string => !!f)
    .map((f) => fileUrl(name, `stills/${encodeURIComponent(f)}`));

  const clipOf = (i: number) => {
    const id = o.shots.shots[i]?.id;
    const c = id ? o.files.clips.filter((f) => f.startsWith(`${id}_final_a`)) : [];
    return c.length ? fileUrl(name, `clips/${c[c.length - 1]}`) : undefined;
  };

  const sound = (e: React.SyntheticEvent<HTMLElement>, on: boolean) => {
    const v = e.currentTarget.querySelector("video");
    if (v) {
      v.muted = !on;
      if (on)
        v.play().catch(() => {
          v.muted = true;
        });
    }
  };

  return (
    <div className="animate-fade-up">
      <PageBanner
        title="Storyboard"
        sub="Turn your idea into a cinematic AI video. Write the story, define the brief and plan tasks. Add scenes, edit prompts, and generate the final video."
        note={
          <>
            From idea
            <br />
            to final video
          </>
        }
        pics={pics}
      />

      <PageBody
        rail={
          <>
            <RailCard className="!p-0 overflow-hidden">
              <div role="tablist" aria-label="Storyboard preview" className="flex border-b border-slate-800">
                {(["preview", "references", "notes"] as const).map((t) => (
                  <button
                    key={t}
                    type="button"
                    role="tab"
                    aria-selected={tab === t}
                    onClick={() => setTab(t)}
                    className={`flex-1 border-b-2 px-3 py-2.5 text-xs font-bold capitalize transition ${
                      tab === t ? "border-pink text-pink" : "border-transparent text-slate-400 hover:text-slate-100"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
              <div className="panel-pad">
                {tab === "preview" && (
                  <>
                    <div className="rounded-2xl border border-slate-800 p-3">
                      <div className="mb-3 flex items-center gap-2">
                        <IconTile tone="pink">
                          <FileText size={15} />
                        </IconTile>
                        <span className="text-sm font-bold">Script Summary</span>
                      </div>
                      {p.title ? <p className="mb-3 text-xs italic text-slate-400">{p.title}</p> : null}
                      <div className="grid grid-cols-3 gap-2">
                        {[
                          { icon: <Clock size={18} />, value: p.duration ? (p.duration.match(/~?\s*\d+/)?.[0].replace(/\s/g, "") || "45") + "s" : "~45s", label: "Duration" },
                          { icon: <Film size={18} />, value: p.scenes.length, label: "Scenes" },
                          { icon: <Users size={18} />, value: (story.match(/\*\*Characters:\*\*\s*(.+)/i)?.[1] || "").split(",").filter((x) => x.trim()).length, label: "Characters" },
                        ].map((x) => (
                          <div key={x.label} className="panel-quiet flex items-center gap-2 px-2.5 py-2">
                            <span className="text-slate-300">{x.icon}</span>
                            <div className="min-w-0 leading-tight">
                              <div className="text-sm font-extrabold">{x.value}</div>
                              <div className="text-[0.65rem] text-slate-400">{x.label}</div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                    <h4 className="mb-2 mt-4 text-xs font-bold text-slate-300">
                      Key Frames <span className="font-normal text-slate-400">(from script)</span>
                    </h4>
                    <ul className="space-y-1.5">
                      {p.scenes.map((s, i) => (
                        <li
                          key={s.n}
                          onMouseEnter={(e) => sound(e, true)}
                          onMouseLeave={(e) => sound(e, false)}
                          className="row-hover flex items-stretch overflow-hidden rounded-xl border border-slate-800"
                        >
                          <div className="relative h-16 w-24 shrink-0 bg-slate-900">
                            {clipOf(i) ? (
                              <video src={clipOf(i)} poster={pics[i]} autoPlay loop muted playsInline preload="metadata" className="h-full w-full object-cover" />
                            ) : (
                              pics[i] && <img src={pics[i]} alt="" className="h-full w-full object-cover" loading="lazy" />
                            )}
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
                    <Link to={`/p/${name}/shots`} className="btn btn-outline mt-3 w-full">
                      <Play size={14} />Play Full Preview
                    </Link>
                  </>
                )}
                {tab === "references" && (
                  <>
                    <div className="mb-2 flex items-center gap-2">
                      <IconTile tone="sky">
                        <Braces size={15} />
                      </IconTile>
                      <span className="text-sm font-bold">References</span>
                    </div>
                    <dl className="kv">
                      <dt>Brand</dt>
                      <dd>{p.brand || "not set"}</dd>
                      <dt>Format</dt>
                      <dd>{p.format || "not set"}</dd>
                    </dl>
                    <dl className="kv mt-1">
                      <dt>Voice</dt>
                      <dd>{brief ? voiceLanguages(brief.fields) || "not chosen" : "..."}</dd>
                    </dl>
                    <p className="mt-1 text-[0.7rem] text-slate-400">Change the languages in brief.md (Visual editor).</p>
                    <p className="mt-3 text-[0.7rem] leading-relaxed text-slate-400">
                      Character sheets and backgrounds you add on the Assets tab become the reference images used when the clips are generated.
                    </p>
                  </>
                )}
                {tab === "notes" && (
                  <>
                    <div className="mb-2 flex items-center gap-2">
                      <IconTile>
                        <FileText size={15} />
                      </IconTile>
                      <span className="text-sm font-bold">Notes</span>
                    </div>
                    <p className="text-xs leading-relaxed text-slate-400">
                      Keep direction here: what the AI must not invent, which lines are spoken, and where the logo or the on-screen text goes.
                    </p>
                  </>
                )}
              </div>
            </RailCard>
            <RailCard title="Verification">
              <VerifyBar scope="story" label="Story" />
            </RailCard>
          </>
        }
        stickyMain
      >
        <div className="panel panel-lit panel-pad flex flex-col xl:h-full">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div role="tablist" aria-label="Project documents" className="flex flex-wrap gap-2">
              {DOCS.map((d) => {
                const Icon = d.icon;
                return (
                  <button
                    key={d.fn}
                    type="button"
                    role="tab"
                    aria-selected={doc === d.fn}
                    onClick={() => setDoc(d.fn)}
                    title={d.hint}
                    className={`pill !px-4 !py-2.5 ${doc === d.fn ? "" : "!bg-slate-900"}`}
                  >
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
              <span className="text-xs text-emerald-400" role="status">
                {status}
              </span>
              <Button variant="pink" onClick={() => saveRef.current?.()}>
                <Save size={15} />Save
              </Button>
            </div>
          </div>
          {msg && <p className="mb-3 text-sm text-brand">{msg}</p>}
          <div role="tablist" aria-label="Editor type" className="mb-3 flex w-fit gap-1 rounded-xl border border-slate-800 bg-slate-900/60 p-1">
            {(["visual", "markdown"] as const).map((v) => (
              <button
                key={v}
                type="button"
                role="tab"
                aria-selected={view === v}
                onClick={() => setView(v)}
                className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-bold transition ${view === v ? "is-active" : "text-slate-400 hover:text-slate-100"}`}
              >
                {doc === "Story.md" ? (
                  v === "visual" ? (
                    <>
                      <Eye size={13} />
                      <span>Show preview (Document view)</span>
                    </>
                  ) : (
                    <>
                      <FileCode2 size={13} />
                      <span>Markdown editor</span>
                    </>
                  )
                ) : (
                  v === "visual" ? "Visual editor" : "Markdown"
                )}
              </button>
            ))}
          </div>
          {doc === "Story.md" && view === "visual" ? (
            <div className="min-h-0 flex-1 overflow-auto pr-1">
              {((saveRef.current = async () => {
                await api("PUT", `/api/projects/${name}/docs/Story.md`, { text: story });
                setStatus("Saved");
                setTimeout(() => setStatus(""), 1500);
                await afterSave();
              }),
              (
                <StoryDocumentView
                  text={story}
                  name={name}
                  stills={o.files.stills}
                  onSwitchToMarkdown={() => setView("markdown")}
                  onExportPdf={() => {
                    const parsed = parseStoryDocument(story);
                    exportStoryToPdf(name, parsed, o.files.stills);
                  }}
                />
              ))}
            </div>
          ) : doc === "brief.md" && view === "visual" ? (
            <div className="min-h-0 flex-1 overflow-auto pr-1">
              <BriefForm name={name} brief={brief} onSaved={afterSave} saveRef={saveRef} onStatus={setStatus} showSave={false} />
            </div>
          ) : doc === "TODO.md" && view === "visual" ? (
            <div className="min-h-0 flex-1 overflow-auto pr-1">
              {((saveRef.current = async () => {
                setStatus("Saved");
                setTimeout(() => setStatus(""), 1500);
                load();
              }),
              todoNode)}
            </div>
          ) : (
            <DocEditor
              key={doc}
              name={name}
              fn={doc}
              initialText={doc === "Story.md" ? story : undefined}
              onChange={doc === "Story.md" ? (val) => setStory(val) : undefined}
              rev={o}
              onSaved={afterSave}
              saveRef={saveRef}
              onStatus={setStatus}
            />
          )}
        </div>
      </PageBody>
    </div>
  );
}
