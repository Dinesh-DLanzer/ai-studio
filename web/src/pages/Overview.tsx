import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight, BadgeCheck, ChevronRight, Clapperboard, ImageIcon, MessageSquare,
  MoreHorizontal, MoreVertical, Pencil, Play, Plus, RefreshCw, ScrollText, ShieldAlert, Users, Wallet,
} from "lucide-react";
import { api, fileUrl } from "../api";
import { Badge, Button, Card, IconTile, money } from "../ui";
import { execAndWait, runKey, Spinner } from "../Proposal";
import { Phone, PillTabs, ProgressBar, RailCard, SectionHeader, StatTile } from "../components/kit";
import { PageBody } from "../app/Shell";
import BriefForm, { voiceLanguages } from "../BriefForm";
import type { TabProps } from "../ProjectPage";
import type { Brief, ImageSpec, Overview, Shot } from "../types";

const stem = (f: string) => f.replace(/\.[^.]+$/, "");

/** The hero banner: display headline, the pipeline line, and a collage of the project's frames. */
function Hero({ name, nextTo, nextLabel, pics }: { name: string; nextTo: string; nextLabel: string; pics: string[] }) {
  return (
    <section aria-label="Project hero" className="panel panel-lit relative overflow-hidden p-6 md:p-8">
      <div className="pointer-events-none absolute -right-24 -top-28 h-80 w-80 rounded-full bg-pink/25 blur-3xl" aria-hidden />
      <div className="pointer-events-none absolute -bottom-32 left-1/4 h-64 w-64 rounded-full bg-brand/10 blur-3xl" aria-hidden />
      <div className="relative grid items-center gap-8 md:grid-cols-[1.05fr_1fr]">
        <div className="min-w-0">
          <h2 className="display text-4xl md:text-6xl">
            Turn ideas<br />into <span className="grad-text">AI videos</span>
          </h2>
          <p className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-slate-300">
            {["Chat", "Storyboard", "Generate", "Review", "Export"].map((s, i, all) => (
              <span key={s} className="inline-flex items-center gap-2">
                {s}{i < all.length - 1 && <ArrowRight size={12} className="text-brand" />}
              </span>
            ))}
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            <Link to={nextTo} className="btn btn-lime btn-lg">{nextLabel} <ArrowRight size={16} /></Link>
            <Link to={`/p/${name}/chat`} className="btn btn-outline btn-lg">Chat with Tara</Link>
          </div>
        </div>
        <div className="relative hidden h-64 md:block" aria-hidden>
          {[0, 1, 2].map((i) => (
            <Phone key={i} src={pics[i]} className={`absolute top-0 h-60 w-[8.5rem] ${["left-[6%] -rotate-6 scale-95", "left-[36%] z-10 -translate-y-3", "left-[66%] rotate-6 scale-95"][i]}`} />
          ))}
        </div>
      </div>
    </section>
  );
}

/** The four-step pipeline with the arrows that connect them. */
function Workflow({ steps }: { steps: { n: string; title: string; text: string; to: string; icon: React.ReactNode; done: boolean; stat: string }[] }) {
  return (
    <ol className="panel panel-lit grid gap-3 p-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Workflow">
      {steps.map((s, i) => (
        <li key={s.n} className="relative min-w-0">
          <Link to={s.to} title={s.stat} className="flex h-full gap-3 rounded-xl p-3 transition hover:bg-white/[.035]">
            <span className="flex flex-col items-center">
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-white/5 text-brand ring-1 ring-white/10">{s.icon}</span>
              {i < steps.length - 1 && <ArrowRight size={16} className="mt-3 hidden text-brand xl:block" aria-hidden />}
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2 text-xs font-extrabold uppercase tracking-[0.14em] text-pink">
                {s.n}{s.done && <BadgeCheck size={15} className="text-emerald-400" aria-label="done" />}
              </span>
              <span className="mt-1.5 block text-[0.95rem] font-bold leading-tight">{s.title}</span>
              <span className="mt-1 block text-xs leading-snug text-slate-400">{s.text}</span>
            </span>
          </Link>
        </li>
      ))}
    </ol>
  );
}

const sceneText = (s: Shot) => {
  const m = s.prompt.match(/ACTION:\s*([^.]*\.?)/i);
  return (m ? m[1] : s.prompt.replace(/^SUBJECT:\s*/i, "")).trim();
};

function SceneCard({ s, i, o, name, running, start, active }: {
  s: Shot; i: number; o: Overview; name: string; running: boolean; start: TabProps["start"]; active: boolean;
}) {
  const ff = s.first_frame?.replace("stills/", ""); const hasFrame = !!ff && o.files.stills.includes(ff);
  const clips = o.files.clips.filter((c) => c.startsWith(`${s.id}_final_a`)); const hasClip = clips.length > 0; const latest = clips[clips.length - 1];
  const title = s.note || s.id;
  const sound = (e: React.SyntheticEvent<HTMLElement>, on: boolean) => { const v = e.currentTarget.querySelector("video"); if (v) { v.muted = !on; if (on) v.play().catch(() => { v.muted = true; }); } };
  return (
    <li onMouseEnter={(e) => sound(e, true)} onMouseLeave={(e) => sound(e, false)}
      className="panel overflow-hidden w-48 shrink-0 p-2.5 transition hover:!border-pink hover:shadow-glow-pink">
      <Link to={`/p/${name}/shots`} className={`thumb block h-28 w-full`} aria-label={`Open scene ${s.id}`}>
        {hasClip
          ? <video src={fileUrl(name, `clips/${latest}`)} poster={hasFrame ? fileUrl(name, s.first_frame!) : undefined} autoPlay loop muted playsInline preload="metadata" />
          : hasFrame
          ? <img src={fileUrl(name, s.first_frame!)} alt="" loading="lazy" />
          : <div className="grid h-full place-items-center text-slate-500"><ImageIcon /></div>}
        <span className="thumb-badge left-2 top-2">{String(i + 1).padStart(2, "0")}</span>
        <span className="thumb-badge right-2 top-2">{s.seconds}.0s</span>
        {s.final_ok && <span className="absolute bottom-2 left-2"><Badge tone="green">approved</Badge></span>}
      </Link>
      <div className="min-w-0 flex-1 pt-2">
        <div className="truncate text-sm font-bold" title={title}>{title}</div>
        <p className="mt-1 line-clamp-2 text-xs leading-snug text-slate-400">{sceneText(s)}</p>
        <div className="mt-2.5 flex gap-2">
          <Button variant={hasClip ? "outline" : "pink"} size="sm" className="min-w-0 flex-1" disabled={running} onClick={() => start("clip", s.id)}>
            {running ? <><Spinner size={13} /> Working</> : <><RefreshCw size={14} /> {hasClip ? "Regenerate" : "Generate"}</>}
          </Button>
          <Link to={`/p/${name}/shots`} aria-label={`More for scene ${s.id}`} className="icon-btn !h-9 !w-9"><MoreHorizontal size={16} /></Link>
        </div>
      </div>
    </li>
  );
}

function StoryboardStrip({ o, name, start, running }: { o: Overview; name: string; start: TabProps["start"]; running: TabProps["running"] }) {
  const shots = o.shots.shots; const rail = useRef<HTMLUListElement>(null);
  const hasClip = (s: Shot) => o.files.clips.some((c) => c.startsWith(`${s.id}_final_a`));
  const activeId = shots.find((s) => !hasClip(s))?.id;
  return (
    <section aria-label="Storyboard" className="panel panel-lit panel-pad">
      <SectionHeader
        title={<><IconTile><ScrollText size={15} /></IconTile> Storyboard</>}
        count={`${shots.length} ${shots.length === 1 ? "scene" : "scenes"}`}
        right={
          <div className="flex items-center gap-2">
            <Link to={`/p/${name}/storyboard`} className="btn btn-grad btn-sm"><Plus size={16} />Add Scene</Link>
          </div>
        }
      />
      {shots.length === 0
        ? <div className="add-tile p-8 text-sm text-slate-400">No scenes yet. <Link className="text-brand hover:underline" to={`/p/${name}/chat`}>Chat with Tara</Link> to draft the storyboard.</div>
        : <div className="relative">
            <ul ref={rail} className="snap-rail">
              {shots.map((s, i) => <SceneCard key={s.id} s={s} i={i} o={o} name={name} start={start} running={!!running[runKey("clip", s.id)]} active={s.id === activeId} />)}
            </ul>
            {shots.length > 3 && (
              <button type="button" aria-label="Scroll scenes" onClick={() => rail.current?.scrollBy({ left: 480, behavior: "smooth" })}
                className="absolute right-1 top-16 grid h-11 w-11 place-items-center rounded-full border border-slate-600 bg-black/80 text-white transition hover:bg-slate-800">
                <ChevronRight size={20} />
              </button>
            )}
          </div>}
    </section>
  );
}

function AssetsStrip({ o, name }: { o: Overview; name: string }) {
  const tabs = [
    { id: "character", label: "Characters" }, { id: "background", label: "Backgrounds" },
    { id: "frame", label: "Scene Frames" }, { id: "other", label: "Uploads" },
  ] as const;
  const [kind, setKind] = useState<ImageSpec["kind"]>("character");
  const list = o.images.images.filter((i) => i.kind === kind);
  const cur = tabs.find((t) => t.id === kind)!;
  return (
    <section aria-label="Assets" className="panel panel-lit panel-pad">
      <SectionHeader
        title={<><IconTile><Users size={15} /></IconTile> Assets</>}
        right={<PillTabs items={tabs.map((t) => ({ id: t.id as ImageSpec["kind"], label: t.label, count: o.images.images.filter((i) => i.kind === t.id).length }))} value={kind} onChange={setKind} />}
      />
      <ul className="snap-rail">
        <li className="shrink-0">
          <Link to={`/p/${name}/assets`} className="add-tile h-[8.5rem] w-48 p-3 hover:border-brand">
            <span><Plus size={26} className="mx-auto text-slate-400" /><span className="mt-1 block text-xs font-bold">Add {cur.label.replace(/s$/, "")}</span>
              <span className="mt-0.5 block text-[0.68rem] text-slate-400">Upload or generate</span></span>
          </Link>
        </li>
        {list.map((i) => {
          const f = o.files.stills.find((x) => stem(x) === i.id);
          return (
            <li key={i.id} className="w-48 shrink-0">
              <div className="panel overflow-hidden">
                <Link to={`/p/${name}/assets`} className="thumb block h-[6.5rem]">
                  {f ? <img src={fileUrl(name, `stills/${f}`)} alt="" loading="lazy" /> : <div className="grid h-full place-items-center text-[0.68rem] text-slate-500">not made yet</div>}
                </Link>
                <div className="flex items-center justify-between px-3 py-2 text-xs font-medium">
                  <span className="truncate">{i.id}</span>
                  <Link to={`/p/${name}/assets`} aria-label={`More for ${i.id}`} className="text-slate-400 hover:text-white"><MoreVertical size={15} /></Link>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function SummaryRail({ name, brief, reload }: { name: string; brief: Brief | null; reload: () => void }) {
  const [edit, setEdit] = useState(false); const [all, setAll] = useState(false);
  const fields = (brief?.fields || []).filter((f) => f.key !== "extra_languages").map((f) => f.key === "language" ? { ...f, value: voiceLanguages(brief?.fields || []) } : f);
  const shown = all ? fields : fields.filter((f) => f.required || f.value);
  return (
    <RailCard title="Project Summary" sub="Same as brief.md" right={
      <div className="flex items-center gap-1">
        {!edit && <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAll(!all)}>{all ? "Less" : "All"}</button>}
        <button type="button" aria-label="Edit the project summary" className="btn btn-ghost btn-sm" onClick={() => setEdit(!edit)}>{edit ? "Close" : <><Pencil size={13} />Edit</>}</button>
      </div>}>
      {!brief ? <p className="text-sm text-slate-400">Loading...</p> : edit ? (
        <BriefForm name={name} brief={brief} compact onSaved={() => { reload(); setEdit(false); }} />
      ) : (
        <dl className="kv">
          {shown.map((f) => (
            <div key={f.key} className="col-span-2 grid grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)] gap-2 border-b border-slate-800/70 pb-1.5 last:border-0">
              <dt>{f.label}</dt><dd className={f.value ? "line-clamp-3" : "italic text-slate-500"}>{f.value || "not answered"}</dd>
            </div>
          ))}
        </dl>
      )}
    </RailCard>
  );
}

function BudgetRail({ o, openBudget }: { o: Overview; openBudget: () => void }) {
  const pct = o.budget.estimate ? o.costs.total / o.budget.estimate : 0;
  return (
    <RailCard title={<span className="flex items-center gap-2"><IconTile tone="lime"><Wallet size={14} /></IconTile> Budget &amp; Cost</span>}
      right={<Badge tone={o.budget.approved ? "green" : "amber"}>{o.budget.approved ? "Approved" : "Not approved"}</Badge>}>
      <ProgressBar value={o.costs.total} max={o.budget.estimate || 1} label="Spent of estimate" />
      <p className="mt-2 text-xs text-slate-400">Spent {money(o.costs.total)} / Est {o.budget.estimate ? money(o.budget.estimate) : "-"}{pct > 0.9 ? " · nearly used up" : ""}</p>
      <div className="mt-3 grid grid-cols-3 gap-2">
        <StatTile value={money(o.costs.used)} label="Used" />
        <StatTile value={money(o.costs.discarded)} label="Discarded" tone="text-amber-400" />
        <StatTile value={money(o.costs.total)} label="Total" />
      </div>
      <p className="mt-3 text-[0.7rem] text-slate-400">{o.budget.estimate ? `Stop-loss ${money(o.budget.stop_loss)}` : "Budget not estimated yet"}</p>
      <Button variant="outline" className="mt-2 w-full" onClick={openBudget}>{o.budget.approved ? "Re-estimate budget" : "Set the budget"}</Button>
    </RailCard>
  );
}

export function OverviewTab({ o, name, load, start, running, openBudget, todoNode, todosDone }: TabProps) {
  const [msg, setMsg] = useState(""); const [brief, setBrief] = useState<Brief | null>(null);
  const [railTab, setRailTab] = useState<"summary" | "todo">("summary"); const tabChosen = useRef(false);
  useEffect(() => {
    if (tabChosen.current || !brief) return;
    setRailTab(!brief.complete ? "summary" : todosDone ? "summary" : "todo");
  }, [brief, todosDone]);
  useEffect(() => { api<Brief>("GET", `/api/projects/${name}/brief`).then(setBrief).catch(() => setBrief(null)); }, [name, o]);
  const waiting = o.proposals.filter((p) => p.status === "pending" || p.status === "approved");
  const act = async (pid: string, how: "approve" | "run" | "reject") => {
    try {
      if (how === "reject") await api("POST", `/api/projects/${name}/proposals/${pid}/reject`);
      else {
        const cur = o.proposals.find((p) => p.id === pid);
        if (cur?.status === "pending") await api("POST", `/api/projects/${name}/proposals/${pid}/approve-human`);
        if (how === "run") setMsg(await execAndWait(name, pid));
      }
      load();
    } catch (e: any) { setMsg(e.message); load(); }
  };

  const shots = o.shots.shots;
  const approved = shots.filter((s) => s.final_ok).length;
  const withClip = shots.filter((s) => o.files.clips.some((c) => c.startsWith(`${s.id}_final_a`))).length;
  const planDone = !!brief?.complete; const storyDone = shots.length > 0;
  const genDone = shots.length > 0 && withClip === shots.length; const reviewDone = shots.length > 0 && approved === shots.length;
  const next = !planDone ? { to: `/p/${name}/chat`, label: "Continue planning" }
    : !storyDone ? { to: `/p/${name}/chat`, label: "Draft the storyboard" }
      : !o.budget.approved ? { to: `/p/${name}/costs`, label: "Set the budget" }
        : !genDone ? { to: `/p/${name}/shots`, label: "Generate shots" }
          : { to: `/p/${name}/shots`, label: "Review clips" };
  const pics = [...shots.map((s) => s.first_frame?.replace("stills/", "")).filter((f): f is string => !!f && o.files.stills.includes(f)), ...o.files.stills].slice(0, 3).map((f) => fileUrl(name, `stills/${f}`));

  const steps = [
    { n: "01", title: "Chat & Plan", text: "Describe your idea, product and style.", to: `/p/${name}/chat`, icon: <MessageSquare size={19} />, done: planDone, stat: brief ? `${brief.required_done}/${brief.required_total} answers` : "" },
    { n: "02", title: "AI Storyboard", text: "Scenes, voice lines and prompts.", to: `/p/${name}/storyboard`, icon: <ScrollText size={19} />, done: storyDone, stat: `${shots.length} scenes` },
    { n: "03", title: "Generate Shots", text: "One clip at a time, you approve each.", to: `/p/${name}/shots`, icon: <Clapperboard size={19} />, done: genDone, stat: `${withClip}/${shots.length} clips` },
    { n: "04", title: "Review & Export", text: "Check, approve, then edit the final video.", to: `/p/${name}/shots`, icon: <Play size={19} />, done: reviewDone, stat: `${approved}/${shots.length} approved` },
  ];

  return (
    <div className="animate-fade-up space-y-5">
      <Hero name={name} nextTo={next.to} nextLabel={next.label} pics={pics} />

      {waiting.length > 0 && (
        <Card title={<span className="flex items-center gap-2"><IconTile tone="pink"><ShieldAlert size={15} /></IconTile> Waiting for your decision</span>} className="!border-amber-400/60">
          <p className="mb-3 text-xs text-slate-400">An AI agent (or you) proposed these paid actions. Nothing has been spent. Check the price and the prompt, then approve or reject.</p>
          {waiting.map((p) => (
            <div key={p.id} className="row-hover flex flex-wrap items-start justify-between gap-3 border-t border-slate-800 py-2.5 text-sm">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge>{p.kind}</Badge><span className="font-mono">{p.shot}</span>
                  <span className="text-slate-400">{p.model}</span><b>{money(p.price)}</b>
                  {p.status === "approved" && <Badge tone="green">approved, not run yet</Badge>}
                </div>
                {p.summary?.prompt && <div className="mt-1 line-clamp-3 text-xs text-slate-400">{p.summary.prompt}</div>}
                <div className="mt-1 text-[0.7rem] text-slate-400">{p.summary?.seconds ? `${p.summary.seconds}s · ` : ""}{p.summary?.audio ? "with audio · " : ""}{p.summary?.first_frame ? `first frame ${p.summary.first_frame}` : ""}</div>
              </div>
              <div className="flex gap-2">
                {p.status === "pending" && <Button variant="outline" size="sm" onClick={() => act(p.id, "approve")}>Approve</Button>}
                <Button size="sm" onClick={() => act(p.id, "run")}>{p.status === "pending" ? "Approve and run" : "Run"}</Button>
                <Button variant="ghost" size="sm" onClick={() => act(p.id, "reject")}>Reject</Button>
              </div>
            </div>
          ))}
          {msg && <p className="mt-2 text-sm">{msg}</p>}
        </Card>
      )}

      <Workflow steps={steps} />

      <PageBody rail={
        <>
          <BudgetRail o={o} openBudget={openBudget} />
          <PillTabs items={[{ id: "summary", label: "Project Summary" }, { id: "todo", label: "TODO" }]} value={railTab} onChange={(v) => { tabChosen.current = true; setRailTab(v as "summary" | "todo"); }} />
          {railTab === "summary" ? <SummaryRail name={name} brief={brief} reload={load} /> : todoNode}
          {msg && waiting.length === 0 && <p className="text-sm text-red-400">{msg}</p>}
        </>
      } stickyMain="auto">
        <div className="space-y-5">
          <StoryboardStrip o={o} name={name} start={start} running={running} />
          <AssetsStrip o={o} name={name} />
        </div>
      </PageBody>
    </div>
  );
}
