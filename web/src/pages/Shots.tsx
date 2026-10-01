import { useEffect, useMemo, useRef, useState } from "react";
import * as Menu from "@radix-ui/react-dropdown-menu";
import {
  ArrowRight, Calendar, CheckCheck, ChevronDown, Clapperboard, Clock, Eye, Film, ImageIcon, MoreHorizontal, Pencil, Play, Plus,
  RefreshCw, Search, Settings2, SlidersHorizontal, Trash2, Wand2,
} from "lucide-react";
import { Link } from "react-router-dom";
import { api, fileUrl } from "../api";
import { Badge, Button, Select } from "../ui";
import { Spinner, runKey } from "../Proposal";
import { useToast } from "../toast";
import { promptDialog } from "../dialogs";
import { RenameButton } from "../Rename";
import { VerifyBar } from "../Verify";
import { EmptyState, RailCard } from "../components/kit";
import { ReviewBadge, stem, type TabProps } from "../ProjectPage";
import type { Shot } from "../types";

const mmss = (s: number) => `0:${String(Math.round(s)).padStart(2, "0")}`;
const money = (n?: number) => (n === undefined || n === null ? "-" : `$${n.toFixed(3)}`);
type Filter = "all" | "videos" | "audio"; type Tab = "prompt" | "reference" | "history";

/** Shots: pick a shot on the left, watch and check its clip in the middle, set the video options on the right. Shots only make video; images are made on the Assets page. */
export function ShotsTab({ o, name, load, start, running }: TabProps) {
  const toast = useToast();
  const [shots, setShots] = useState<Shot[]>(o.shots.shots); const [dirty, setDirty] = useState(false);
  const [sel, setSel] = useState<string>(o.shots.shots[0]?.id || ""); const [tab, setTab] = useState<Tab>("prompt");
  const [filter, setFilter] = useState<Filter>("all"); const [q, setQ] = useState(""); const [sort, setSort] = useState<"order" | "cost" | "approved">("order");
  const [rows, setRows] = useState<any[]>([]); const [adv, setAdv] = useState(false);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { if (!dirty) setShots(o.shots.shots); }, [o.shots, dirty]);
  useEffect(() => { api<any>("GET", `/api/projects/${name}/costs`).then((r) => setRows(r.rows)).catch(() => {}); }, [name, o.costs.total]);

  const changed = (id: string) => { const a = shots.find((x) => x.id === id); const b = o.shots.shots.find((x) => x.id === id); return !!a && JSON.stringify(a) !== JSON.stringify(b); };
  const clipsOf = (id: string) => o.files.clips.filter((c) => c.startsWith(`${id}_final_a`));
  const costOf = (id: string) => o.budget.per_shot?.find((p) => p.id === id)?.cost;
  /** Price of this shot as it is right now (unsaved edits included), with the retry allowance the budget was estimated with. */
  const priceOf = (s: Shot) => {
    try {
      const def = o.rates?.models?.[s.model]?.[s.resolution || (o.shots as any).final_resolution || "720p"];
      if (def === undefined) return costOf(s.id);
      const rate = typeof def === "number" ? def : Array.isArray(def) ? (def.find((t: any) => t.up_to === undefined || s.seconds <= t.up_to) || {}).rate : def[(s.audio ?? (o.shots as any).audio) ? "audio" : "no_audio"];
      return rate === undefined ? costOf(s.id) : (rate * s.seconds) / (1 - (o.budget.failure_rate || 0));
    } catch { return costOf(s.id); }
  };
  const frame = (s: Shot) => (s.first_frame && o.files.stills.includes(s.first_frame.replace("stills/", "")) ? fileUrl(name, s.first_frame) : undefined);
  const upd = (id: string, patch: Partial<Shot>) => { setShots((a) => a.map((s) => (s.id === id ? { ...s, ...patch } : s))); setDirty(true); };
  const save = async () => { try { await api("PUT", `/api/projects/${name}/shots`, { ...o.shots, shots }); setDirty(false); toast("ok", "Shots saved."); load(); } catch (e: any) { toast("error", e.message); } };
  const approve = async (id: string) => { try { await api("POST", `/api/projects/${name}/shots/${id}/approve`); load(); } catch (e: any) { toast("error", e.message); } };
  const discard = async (rel: string) => { const reason = await promptDialog("Why discard this clip?", { title: "Discard clip", ok: "Discard" }); if (reason === null) return; await api("POST", `/api/projects/${name}/discard`, { rel, reason }); load(); };
  const generate = async (id: string) => { if (dirty) await save(); start("clip", id); };

  const list = useMemo(() => {
    let a = shots.filter((s) => (filter === "videos" ? clipsOf(s.id).length > 0 : filter === "audio" ? !!s.audio : true));
    const t = q.trim().toLowerCase();
    if (t) a = a.filter((s) => `${s.id} ${s.note || ""} ${s.prompt}`.toLowerCase().includes(t));
    if (sort === "cost") a = [...a].sort((x, y) => (costOf(y.id) || 0) - (costOf(x.id) || 0));
    if (sort === "approved") a = [...a].sort((x, y) => Number(!!y.final_ok) - Number(!!x.final_ok));
    return a;
    /* eslint-disable-next-line */
  }, [shots, filter, q, sort, o.files.clips, o.budget]);
  const cur = shots.find((s) => s.id === sel) || shots[0];
  const counts = { all: shots.length, videos: shots.filter((s) => clipsOf(s.id).length).length, audio: shots.filter((s) => s.audio).length };
  const title = (s: Shot) => (s.note || s.id).replace(/\s*Still:.*$/i, "").trim() || s.id;

  const chips = (s: Shot) => (
    <div className="mt-1.5 flex flex-wrap gap-1 [&>.tag]:whitespace-nowrap [&>.tag]:!px-1.5 [&>.tag]:!py-0.5 [&>.tag]:!text-[0.65rem]">
      <span className={`tag ${s.final_ok ? "tag-emerald" : clipsOf(s.id).length ? "tag-lime" : ""}`}>{s.final_ok ? "Approved" : clipsOf(s.id).length ? "Clip ready" : "Needs clip"}</span>
      {s.audio && <span className="tag tag-sky">Audio</span>}
    </div>
  );

  const item = (s: Shot, idx: number) => {
    const on = cur?.id === s.id; const clips = clipsOf(s.id); const img = frame(s);
    return (
      <li key={s.id}>
        <div role="button" tabIndex={0} aria-label={`Open shot ${s.id}`} onClick={() => setSel(s.id)} onKeyDown={(e) => e.key === "Enter" && setSel(s.id)}
          className={`panel flex cursor-pointer items-start gap-2 p-2.5 transition ${on ? "!border-pink shadow-glow-pink" : "hover:border-slate-700"}`}>
          <span className="mt-1 grid h-6 w-6 shrink-0 place-items-center rounded-lg border border-slate-700 text-xs font-bold text-slate-300">{idx + 1}</span>
          <div className={`thumb shrink-0 h-[4.5rem] w-20`}>
            {img ? <img src={img} alt="" loading="lazy" />
              : clips.length ? <video src={`${fileUrl(name, `clips/${clips[clips.length - 1]}`)}#t=0.5`} preload="metadata" muted playsInline aria-hidden />
              : <div className="grid h-full place-items-center text-slate-600"><Film size={18} /></div>}
            <span className="thumb-badge bottom-1 right-1">{mmss(s.seconds)}</span>
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-bold">{title(s)}</div>
            <div className="mt-0.5 flex items-center gap-1.5 text-[0.7rem] text-slate-400"><Film size={11} />Video <span aria-hidden>•</span> {s.seconds}s{clips.length > 1 ? ` • ${clips.length} versions` : ""}</div>
            {chips(s)}
          </div>
          <Menu.Root>
            <Menu.Trigger aria-label={`More for shot ${s.id}`} onClick={(e) => e.stopPropagation()} className="icon-btn !h-8 !w-8 !border-0 !bg-transparent"><MoreHorizontal size={16} /></Menu.Trigger>
            <Menu.Portal>
              <Menu.Content align="end" sideOffset={6} className="menu-surface">
                <Menu.Item className="menu-item" onSelect={() => generate(s.id)} disabled={!!running[runKey("clip", s.id)]}><RefreshCw size={14} />Generate clip</Menu.Item>
                {clips.length > 0 && <Menu.Item className="menu-item" onSelect={() => start("review", s.id)}><Eye size={14} />Vision review</Menu.Item>}
                {clips.length > 0 && !s.final_ok && <Menu.Item className="menu-item" onSelect={() => approve(s.id)}><CheckCheck size={14} />Approve</Menu.Item>}
              </Menu.Content>
            </Menu.Portal>
          </Menu.Root>
        </div>
      </li>
    );
  };

  const filters: { id: Filter; label: string }[] = [{ id: "all", label: "All Shots" }, { id: "videos", label: "Videos" }, { id: "audio", label: "Audio" }];

  const clips = cur ? clipsOf(cur.id) : []; const latest = clips[clips.length - 1];
  const busy = !!(cur && running[runKey("clip", cur.id)]);
  const history = cur ? rows.filter((r) => r.shot === cur.id) : [];

  return (
    <div className="animate-fade-up">
      <header className="page-head md:min-h-[9rem]">
        <img src="/shots-banner.png" alt="" aria-hidden className="pointer-events-none absolute bottom-0 right-4 hidden h-[8.5rem] w-auto select-none md:block" style={{ position: "absolute" }} />
        <div className="flex items-center gap-4">
          <div className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl border border-slate-700 bg-slate-900 text-white"><Play size={24} fill="currentColor" /></div>
          <div className="min-w-0">
            <h1 className="page-title grad-text">Shots</h1>
            <p className="mt-1 text-sm text-slate-400">Manage and organize your video shots. Use shots to build scenes in your storyboard.</p>
          </div>
        </div>
      </header>

      <div className="panel mb-4 flex flex-wrap items-center gap-2 p-3">
        <div role="tablist" aria-label="Shot types" className="flex flex-wrap gap-2">
          {filters.map((f) => {
            const on = filter === f.id;
            return (
              <button key={f.id} type="button" role="tab" aria-selected={on} onClick={() => setFilter(f.id)}
                className={`pill !px-4 !py-2.5 ${on ? "!border-pink/70 !bg-pink/10 !text-white !bg-none shadow-glow-pink" : "!bg-slate-900"}`}>
                {f.label}<span className={`rounded-lg px-1.5 text-[0.72rem] ${on ? "bg-pink/30" : "bg-white/10"}`}>{counts[f.id]}</span>
              </button>
            );
          })}
        </div>
        <span className="flex-1" />
        <div className="relative">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input className="field !w-52 !py-2 !pl-9" placeholder="Search shots..." aria-label="Search shots" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <Menu.Root>
          <Menu.Trigger className="btn btn-outline"><SlidersHorizontal size={15} />{{ order: "Shot order", cost: "Highest cost", approved: "Approved first" }[sort]}<ChevronDown size={14} /></Menu.Trigger>
          <Menu.Portal><Menu.Content align="end" sideOffset={6} className="menu-surface">
            {([["order", "Shot order"], ["cost", "Highest cost"], ["approved", "Approved first"]] as const).map(([v, l]) => <Menu.Item key={v} className="menu-item" onSelect={() => setSort(v)}>{l}</Menu.Item>)}
          </Menu.Content></Menu.Portal>
        </Menu.Root>
        <Link to={`/p/${name}/storyboard`} className="btn btn-grad"><Plus size={15} />Add Shot</Link>
      </div>

      {!shots.length ? (
        <EmptyState title="No shots yet" text="Save the story on the Storyboard page to create the shot list." icon={<Clapperboard size={20} />} />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(19rem,22rem)_minmax(0,1fr)_minmax(18rem,21rem)] xl:items-start">
          {/* shot list */}
          <ul className={`space-y-2.5 xl:sticky xl:top-[4.75rem] xl:max-h-[calc(100vh-5.75rem)] xl:overflow-y-auto xl:pr-1`}>
            {list.map((s) => item(s, shots.findIndex((x) => x.id === s.id)))}
            {!list.length && <li className="text-sm text-slate-400">No shots match.</li>}
          </ul>

          {/* detail */}
          {cur && (
            <section className="panel panel-lit panel-pad min-w-0" aria-label={`Shot ${cur.id}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-sm text-slate-300">Shot {cur.id}{cur.final_ok ? <Badge tone="green">approved</Badge> : latest ? <Badge tone="amber">needs approval</Badge> : <Badge>no clip</Badge>}</div>
                  <h2 className="mt-1 flex items-center gap-2 text-2xl font-extrabold tracking-tight">{title(cur)}
                    <RenameButton kind="shot" current={cur.id} label={`Rename shot ${cur.id}`}
                      explain="The shot id, its clip files (including discarded ones), its cost log rows and its discard history are all updated. Its image keeps its own name."
                      onRename={async (n) => { await api("POST", `/api/projects/${name}/shots/${cur.id}/rename`, { new: n }); toast("ok", `Renamed ${cur.id} to ${n}.`); setSel(n); load(); }} />
                  </h2>
                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400">
                    <span className="inline-flex items-center gap-1.5"><Film size={13} />Video</span>
                    <span className="inline-flex items-center gap-1.5"><Clock size={13} />{cur.seconds}s</span>
                    <span className="inline-flex items-center gap-1.5"><Wand2 size={13} />{cur.model.split("/").pop()}</span>
                    <span className="inline-flex items-center gap-1.5"><Calendar size={13} />{money(costOf(cur.id))}</span>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="outline" size="sm" disabled={!latest || !!running[runKey("review", cur.id)]} onClick={() => start("review", cur.id)}>
                    {running[runKey("review", cur.id)] ? <Spinner size={13} /> : <RefreshCw size={14} />}Re-check
                  </Button>
                  <Button variant="danger" size="sm" disabled={!latest} onClick={() => latest && discard(`clips/${latest}`)}><Trash2 size={13} />Discard</Button>
                  <Button variant="pink" size="sm" onClick={save} disabled={!changed(cur.id)}>Save</Button>
                </div>
              </div>

              <div className="mt-4 overflow-hidden rounded-2xl border border-slate-800 bg-black">
                {latest ? <video key={latest} controls className="mx-auto max-h-[28rem] w-full" src={fileUrl(name, `clips/${latest}`)} poster={frame(cur)} />
                  : (
                    <div className="relative grid min-h-[16rem] place-items-center">
                      {frame(cur) && <img src={frame(cur)} alt="" className="absolute inset-0 h-full w-full object-cover opacity-30" />}
                      <div className="relative text-center">
                        <p className="text-sm text-slate-300">No video yet for this shot.</p>
                        <Button variant="pink" className="mt-3" disabled={busy} onClick={() => generate(cur.id)}>{busy ? <><Spinner size={14} />Generating clip...</> : <><Play size={15} />Generate clip</>}</Button>
                      </div>
                    </div>
                  )}
              </div>
              {latest && !cur.final_ok && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Button variant="pink" size="sm" onClick={() => approve(cur.id)}><CheckCheck size={14} />Approve this clip</Button>
                  <span className="text-xs text-slate-400">Watch and listen first, then approve, or generate a new version.</span>
                </div>
              )}
              {latest && <ReviewBadge r={o.reviews[stem(latest)]} />}

              <div role="tablist" aria-label="Shot details" className="mt-4 flex border-b border-slate-800">
                {([["prompt", "Prompt & Settings"], ["reference", "Reference"], ["history", "History"]] as const).map(([id, l]) => (
                  <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
                    className={`border-b-2 px-4 py-2.5 text-sm font-bold transition ${tab === id ? "border-pink text-pink" : "border-transparent text-slate-400 hover:text-slate-100"}`}>{l}</button>
                ))}
              </div>

              <div className="mt-4">
                {tab === "prompt" && (
                  <div>
                    <div className="mb-1.5 flex items-center justify-between"><span className="text-sm font-semibold">Prompt</span>
                      <Button variant="outline" size="sm" onClick={() => promptRef.current?.focus()}><Pencil size={13} />Edit Prompt</Button></div>
                    <textarea ref={promptRef} rows={7} className="field !text-sm" maxLength={3000} value={cur.prompt} aria-label={`Prompt for shot ${cur.id}`} onChange={(e) => upd(cur.id, { prompt: e.target.value })} />
                    <div className="mt-1 text-right text-[0.7rem] text-slate-400">{cur.prompt.length}/3000</div>
                  </div>
                )}
                {tab === "reference" && (
                  <div className="grid gap-4 sm:grid-cols-[12rem_1fr]">
                    <div className="thumb aspect-[9/16]">{frame(cur) ? <img src={frame(cur)} alt="First frame" /> : <div className="grid h-full place-items-center p-3 text-center text-xs text-slate-500">No first frame. Veo may invent a person!</div>}</div>
                    <div>
                      <label className="mb-1 block text-sm font-semibold" htmlFor="ref-pick">First frame image</label>
                      <Select id="ref-pick" value={cur.first_frame || ""} onChange={(e) => upd(cur.id, { first_frame: e.target.value || undefined })}>
                        <option value="">none</option>
                        {o.files.stills.map((f) => <option key={f} value={`stills/${f}`}>{f}</option>)}
                      </Select>
                      <p className="mt-3 text-xs leading-relaxed text-slate-400">The video starts from this image. Images are made or replaced on the Assets page; pick which one this shot uses in "Change Reference Image".</p>
                    </div>
                  </div>
                )}
                {tab === "history" && (
                  <ul className="space-y-1.5 text-xs">
                    {history.map((r, i) => (
                      <li key={i} className="flex items-center justify-between gap-2 rounded-lg border border-slate-800 px-3 py-2">
                        <div className="min-w-0"><div className="truncate font-semibold text-slate-200">{String(r.model || "").split("/").pop()} · {r.stage}</div><div className="text-slate-400">{String(r.timestamp || "").slice(0, 16).replace("T", " ")} · {r.result}</div></div>
                        <span className="shrink-0 font-bold">{money(Number(r.cost || 0))}</span>
                      </li>
                    ))}
                    {!history.length && <li className="text-slate-400">No generations logged for this shot yet.</li>}
                  </ul>
                )}
              </div>
            </section>
          )}

          {/* edit shot */}
          {cur && (
            <aside className="space-y-4 xl:sticky xl:top-[4.75rem] xl:max-h-[calc(100vh-5.75rem)] xl:overflow-y-auto" aria-label="Edit shot">
              <RailCard title="Edit Shot">
                <div className="space-y-2.5">
                  {[
                    { icon: <Pencil size={17} />, t: "Edit Prompt", d: "Modify the description or script", on: () => { setTab("prompt"); setTimeout(() => promptRef.current?.focus(), 50); } },
                    { icon: <ImageIcon size={17} />, t: "Change Reference Image", d: "Pick another image as the first frame", on: () => { setTab("reference"); setTimeout(() => document.getElementById("ref-pick")?.focus(), 50); } },
                    { icon: <RefreshCw size={17} />, t: "Regenerate with Same Settings", d: "Generate a new version", on: () => generate(cur.id) },
                  ].map((a) => (
                    <button key={a.t} type="button" onClick={a.on} className="panel-quiet flex w-full items-center gap-3 p-3 text-left transition hover:border-slate-600">
                      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-slate-700 text-slate-200">{a.icon}</span>
                      <span className="min-w-0"><span className="block text-sm font-bold">{a.t}</span><span className="block text-xs text-slate-400">{a.d}</span></span>
                    </button>
                  ))}
                </div>
              </RailCard>

              <RailCard title="Generate Options">
                <div className="grid grid-cols-2 gap-3">
                  <div><label className="mb-1 block text-xs font-semibold text-slate-300">Model</label>
                    <Select value={cur.model} disabled aria-label="Model"><option>{cur.model.split("/").pop()}</option></Select></div>
                  <div><label className="mb-1 block text-xs font-semibold text-slate-300" htmlFor="dur">Duration</label>
                    <Select id="dur" value={cur.seconds} onChange={(e) => upd(cur.id, { seconds: Number(e.target.value) })} aria-label={`Seconds for ${cur.id}`}>
                      {[4, 6, 8].map((n) => <option key={n} value={n}>{n} seconds</option>)}</Select></div>
                </div>
                <div className="mt-3"><label className="mb-1 block text-xs font-semibold text-slate-300">Aspect Ratio</label>
                  <Select value="" disabled aria-label="Aspect ratio"><option>{o.shots.aspect_ratio || "9:16"} {(o.shots.aspect_ratio || "9:16") === "9:16" ? "(Vertical)" : ""}</option></Select></div>
                <div className="mt-3 flex items-center justify-between gap-3">
                  <label className="flex cursor-pointer items-center gap-2.5 text-sm font-semibold">
                    <button type="button" role="switch" aria-checked={!!cur.audio} aria-label="Use audio" onClick={() => upd(cur.id, { audio: !cur.audio })}
                      className={`relative h-6 w-11 rounded-full transition ${cur.audio ? "bg-pink" : "bg-slate-700"}`}><span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${cur.audio ? "left-[1.4rem]" : "left-0.5"}`} /></button>
                    Use Audio
                  </label>
                  <span className="tag">{(o.shots as any).language || "Auto"} (Auto)</span>
                </div>
                <button type="button" onClick={() => setAdv(!adv)} aria-expanded={adv} className="panel-quiet mt-3 flex w-full items-center justify-between p-3 text-left text-sm font-semibold">
                  <span className="flex items-center gap-2.5"><Settings2 size={16} />Advanced Settings</span><ChevronDown size={16} className={adv ? "rotate-180" : ""} />
                </button>
                {adv && <dl className="kv mt-2"><dt>Resolution</dt><dd>{cur.resolution || (o.shots as any).final_resolution || "default"}</dd><dt>First frame</dt><dd className="break-all font-mono text-xs">{cur.first_frame || "none"}</dd></dl>}
                <Button variant="pink" className="mt-4 w-full !py-3" disabled={busy} onClick={() => generate(cur.id)}>
                  {busy ? <><Spinner size={14} />Generating clip...</> : <>Generate New Version <ArrowRight size={16} /></>}
                </Button>
                <p className="mt-2 text-center text-[0.7rem] text-slate-400">Estimated {money(priceOf(cur))}</p>
              </RailCard>

              <RailCard title="Verification"><VerifyBar scope="shots" label="Shots" /></RailCard>
            </aside>
          )}
        </div>
      )}
    </div>
  );
}
