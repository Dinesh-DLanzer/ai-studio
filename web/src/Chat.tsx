import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Check, CheckCheck, Circle, Image as ImageIcon, Sliders, X } from "lucide-react";
import { api, fileUrl, upload } from "./api";
import RolesSection from "./settings/Roles";
import { Badge, Button, Card, Field, Modal } from "./ui";
import { Spinner, execAndWait, type Running } from "./Proposal";
import { useToast } from "./toast";
import type { ChatAttachment, ChatState, NextStep, Proposal } from "./types";
import { LogoMark } from "./components/kit";
import { Markdown } from "./Markdown";
import { notifyDone, notifyStart } from "./notify";
import { AI_NAME } from "./brand";

const clock = (ts: string) => { const d = new Date(ts); return ts && !isNaN(+d) ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : ""; };

const slug = (n: string) => n.replace(/\.[^.]+$/, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "upload";

interface PlanItem { kind: "image" | "clip"; target: string; label: string; price: number; model: string; }
interface Plan { items: PlanItem[]; total: number; budget: { estimate: number | null; stop_loss: number | null; spent: number } }
const usd = (n: number) => `$${n < 1 ? n.toFixed(3) : n.toFixed(2)}`;

export default function Chat({ project, reloadAll, onApplied, openBudget, start, running, refreshKey }: {
  project: string; reloadAll: () => void; onApplied: () => void; openBudget: () => void; start: (k: "image" | "clip" | "review", t: string) => void | Promise<void>; running: Running; refreshKey?: unknown;
}) {
  const toast = useToast(); const nav = useNavigate();
  const [st, setSt] = useState<ChatState | null>(null); const [text, setText] = useState(""); const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(""); const [showStory, setShowStory] = useState(false);
  const [plan, setPlan] = useState<Plan | null>(null); const [clicking, setClicking] = useState(false);
  const [batch, setBatch] = useState<{ i: number; total: number; label: string } | null>(null);
  const [models, setModels] = useState(false); const [files, setFiles] = useState<ChatAttachment[]>([]);
  const log = useRef<HTMLDivElement>(null); const attach = useRef<HTMLInputElement>(null);
  const load = useCallback(async () => {
    const s = await api<ChatState>("GET", `/api/projects/${project}/chat`); setSt(s);
    setPending(s.pending_story ? (await api<{ text: string }>("GET", `/api/projects/${project}/story/pending`)).text : "");
  }, [project]);
  useEffect(() => { load().catch((e) => toast("error", e.message)); }, [load, toast, refreshKey]);   // refreshKey: the project changed (an image or clip was made), so the checklist is re-read
  useEffect(() => {          // an idea typed into the command box (⌘K) becomes the first message
    const key = `ai-studio-idea:${project}`; const idea = sessionStorage.getItem(key);
    if (idea) { sessionStorage.removeItem(key); setTimeout(() => send(idea), 400); }
    /* eslint-disable-next-line */
  }, [project]);
  useEffect(() => { const el = log.current; if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" }); }, [st?.messages.length, busy]);

  const send = async (msg?: string) => {
    const t = (msg ?? text).trim(); if (!t || busy) return;
    setText(""); setBusy(true);
    const nid = notifyStart(`${AI_NAME} is replying`, t.length > 80 ? `${t.slice(0, 80)}…` : t, { project, to: `/p/${project}/chat` });
    const sent = files; setFiles([]);
    setSt((s) => s && { ...s, messages: [...s.messages, { role: "user", text: t, ts: new Date().toISOString(), ...(sent.length ? { attachments: sent } : {}) }] });
    try {
      const r = await api<{ applied?: boolean }>("POST", `/api/projects/${project}/chat`, { text: t, prefs: { auto_storyboard: true }, ...(sent.length ? { attachments: sent.map((f) => f.id) } : {}) });
      await load(); reloadAll();
      if (r.applied) { toast("ok", "Story.md and TODO.md are ready."); onApplied(); }
      notifyDone(nid, "ok", r.applied ? "Reply ready. Story.md and TODO.md were written from your brief." : "Reply ready.");
    }
    catch (e: any) { toast("error", e.message); notifyDone(nid, "error", e.message); await load(); }
    finally { setBusy(false); }
  };
  const attachFile = async (f?: File) => {
    if (!f) return;
    if (!f.type.startsWith("image/") && !/\.(png|jpe?g|webp|gif|bmp|tiff?|heic|heif)$/i.test(f.name)) return toast("error", "That is not a supported image.");
    try {
      const o = await api<any>("GET", `/api/projects/${project}`);
      const taken = new Set<string>((o.images?.images || []).map((i: any) => i.id)); let id = slug(f.name), n = 2; while (taken.has(id)) id = `${slug(f.name)}_${n++}`;
      await upload(project, `stills/${id}.png`, f, false);
      const o2 = await api<any>("GET", `/api/projects/${project}`);
      const file = (o2.files.stills as string[]).find((x) => x.startsWith(`${id}.`)) || `${id}.png`;
      await api("POST", `/api/projects/${project}/stills/import`, { items: [{ file, id, kind: "other" }] });
      setFiles((x) => [...x, { id, file }]); toast("ok", `${id} saved in Uploads. It is sent with your next message.`); reloadAll();
    } catch (e: any) { toast("error", e.message); }
  };
  // while anything is being made (one item or the whole run) every generate button is off and shows a loader
  const working = clicking || !!batch || Object.keys(running).length > 0;
  const act = async (n: NextStep) => {
    if (working) return;
    if (n.kind === "apply-story") void apply();
    else if (n.kind === "budget") openBudget();
    else if (n.kind === "image" || n.kind === "clip") { setClicking(true); try { await start(n.kind, n.target || ""); } finally { setClicking(false); } }
    else if (n.kind === "approve") nav(`/p/${project}/shots`);
    else if (n.kind === "export") nav(`/p/${project}/review`);
  };
  const apply = async () => {
    try { const r = await api<any>("POST", `/api/projects/${project}/story/apply-pending`); toast("ok", `Storyboard applied: ${r.shots.shots.length} shots, ${r.images.images.length} images.`); await load(); reloadAll(); onApplied(); }
    catch (e: any) { toast("error", e.message); }
  };
  const openPlan = async () => {
    if (working) return;
    setClicking(true);
    try { setPlan(await api<Plan>("GET", `/api/projects/${project}/generate-all`)); }
    catch (e: any) { toast("error", e.message); }
    finally { setClicking(false); }
  };
  /** One human approval for the whole list (exact prices shown first); each item then runs the normal propose / approve / execute steps in order and the run stops at the first problem. */
  const runAll = async () => {
    const items = plan?.items || []; setPlan(null);
    let done = 0;
    try {
      for (const [i, it] of items.entries()) {
        setBatch({ i: i + 1, total: items.length, label: it.label });
        const prop = await api<Proposal>("POST", `/api/projects/${project}/proposals`, { kind: it.kind, target: it.target });
        await api("POST", `/api/projects/${project}/proposals/${prop.id}/approve`, { code: prop.code });
        const msg = await execAndWait(project, prop.id, false);
        if (msg.startsWith("Provider error")) throw new Error(`${it.label}: ${msg}`);
        done++; reloadAll(); await load();
      }
      toast("ok", `Generated ${done} item${done === 1 ? "" : "s"}.`);
    } catch (e: any) { toast("error", `Stopped after ${done} of ${items.length}: ${e.message}`); }
    finally { setBatch(null); reloadAll(); await load().catch(() => {}); }
  };
  const drop = async () => { await api("POST", `/api/projects/${project}/story/discard-pending`); await load(); };
  if (!st) return <p className="text-slate-400">Loading...</p>;
  const first = st.messages.length === 0;
  const next = st.progress?.next;
  const queue = st.progress?.queue || [];

  return (
    <div className="animate-fade-up">
      <header className="page-head md:min-h-[11rem]">
        <img src="/chat-banner.png" alt="" aria-hidden className="pointer-events-none absolute -top-2 right-2 hidden h-[11.5rem] w-auto select-none md:block" style={{ position: "absolute" }} />
        <div className="max-w-xl pt-3">
          <h1 className="page-title">Chat with <span className="grad-text">{AI_NAME}</span></h1>
          <p className="mt-3 max-w-md text-sm text-slate-400">Hi, I'm {AI_NAME}, your producer. Describe your idea and I'll interview you, write the storyboard and guide you to the finished video.</p>
        </div>
      </header>

      <div className="min-w-0">
        <div ref={log} className="chat-log h-[30rem] sm:h-[34rem]" role="log" aria-live="polite" aria-label="Conversation">
          {first && <div className="rounded-xl border border-dashed border-slate-700 p-4 text-sm text-slate-400">Say hello to begin, or describe your video in a sentence or two.</div>}
          {st.messages.map((m, i) => {
            const user = m.role === "user";
            return (
              <div key={i} className={`flex items-start gap-3 ${user ? "justify-end" : ""}`}>
                {!user && <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-slate-800 bg-slate-900" aria-hidden><LogoMark size={26} /></span>}
                {user && <span className="avatar !h-11 !w-11 shrink-0" aria-hidden>Y</span>}
                <div className={`chat-bubble ${user ? "chat-bubble-user" : ""}`}>
                  {m.attachments?.length ? <div className="mb-2 flex flex-wrap gap-2" data-testid="msg-attachments">{m.attachments.map((a) => (
                    <figure key={a.id} className="m-0"><img src={fileUrl(project, `stills/${a.file}`)} alt={`Attached image ${a.id}`} className="h-28 max-w-[14rem] rounded-xl border border-slate-800 bg-black/30 object-contain" />
                      {a.colors?.length ? <figcaption className="mt-1 flex gap-1" aria-label={`Main colours of ${a.id}`}>{a.colors.map((c) => <span key={c} title={c} className="h-3.5 w-3.5 rounded-full border border-white/20" style={{ background: c }} />)}</figcaption> : null}</figure>))}</div> : null}
                  <div className="chat-md">{user ? <div className="whitespace-pre-wrap">{m.text}</div> : <Markdown text={m.text} />}</div>
                  <div className="mt-1.5 flex items-center justify-end gap-1.5 text-[0.7rem] text-slate-400">
                    {!user && <span className="mr-auto truncate opacity-80"><b className="font-bold text-slate-200">{AI_NAME}</b>{m.model ? ` · ${m.model}` : ""}{(m as any).cost ? ` · $${Number((m as any).cost).toFixed(4)}` : ""}</span>}
                    {clock(m.ts)}{user && <CheckCheck size={14} className="text-emerald-400" aria-label="sent" />}
                  </div>
                </div>
              </div>
            );
          })}
          {busy && <div className="flex items-center gap-2 pl-14 text-sm text-slate-400"><span className="spin"><Spinner size={15} /></span> {AI_NAME} is thinking (free models can take up to a minute)...</div>}
        </div>

        {st.progress && st.progress.groups.length > 0 && (
          <section className="panel panel-lit panel-pad mt-3" aria-label="Production checklist" data-testid="checklist">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <h2 className="text-sm font-bold">Production checklist</h2>
              <ul className="flex flex-1 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-300">
                {st.progress.groups.map((g) => { const ok = g.total > 0 && g.done >= g.total; return (
                  <li key={g.key} className={`inline-flex items-center gap-1 ${ok ? "text-emerald-300" : ""}`}>{ok ? <Check size={13} aria-label="done" /> : <Circle size={11} aria-label="to do" />}{g.label} <span className="text-slate-400">{g.done}/{g.total}</span></li>); })}
              </ul>
            </div>
            {next && (
              <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-slate-800 pt-3">
                <span className="text-xs uppercase tracking-wider text-slate-400">Next</span>
                <span className="min-w-0 flex-1 text-sm font-semibold" data-testid="next-step">{next.label}</span>
                {batch && <span className="text-xs text-slate-300" role="status" data-testid="batch-status">Generating {batch.i} of {batch.total}: {batch.label}</span>}
                {next.kind !== "chat" && (
                  <span className="flex items-center gap-2">
                    {(next.kind === "image" || next.kind === "clip") && queue.length > 1 && (
                      <Button variant="outline" size="sm" onClick={openPlan} disabled={working} data-testid="generate-all">
                        {working && <Spinner size={13} />}Generate all ({queue.length})
                      </Button>
                    )}
                    <Button variant="pink" size="sm" onClick={() => act(next)} disabled={working} data-testid="next-action">
                      {working && <Spinner size={13} />}{working ? "Generating..." : next.kind === "image" || next.kind === "clip" ? "Generate" : next.kind === "apply-story" ? "Apply" : next.kind === "budget" ? "Set the budget" : "Open"}
                    </Button>
                  </span>
                )}
              </div>
            )}
          </section>
        )}

        <div className="chat-composer mt-3">
          <Field rows={3} placeholder={"Describe your idea... (e.g. \u201CA 30s story about a tea seller whose small stall becomes the talk of the street\u201D)"} aria-label="Message" value={text}
            onChange={(e) => setText(e.target.value)} disabled={busy}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
          <input ref={attach} type="file" accept="image/*" className="sr-only" aria-label="Attach an image (logo, product photo, reference)" tabIndex={-1} onChange={(e) => { attachFile(e.target.files?.[0]); e.target.value = ""; }} />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button type="button" className="icon-btn !h-11 !w-11" aria-label="Attach an image" title="Attach an image: logo, product photo or reference. It is saved in Uploads." onClick={() => attach.current?.click()}><ImageIcon size={17} /></button>
            <button type="button" className="icon-btn !h-11 !w-11" aria-label="Set up models" title="Set up models" onClick={() => setModels(true)}><Sliders size={17} /></button>
            {files.map((f) => (
              <span key={f.id} data-testid="pending-attachment" className="inline-flex h-11 items-center gap-2 rounded-xl border border-slate-800 bg-white/[.03] py-1 pl-1 pr-2 text-sm">
                <img src={fileUrl(project, `stills/${f.file}`)} alt="" className="h-9 w-9 rounded-lg object-cover" />{f.id}
                <button type="button" className="text-slate-400 hover:text-white" aria-label={`Remove ${f.id} from the next message`} onClick={() => setFiles((x) => x.filter((y) => y.id !== f.id))}><X size={14} /></button>
              </span>
            ))}
            <span className="ml-auto flex items-center gap-2">
              {first && <Button variant="outline" onClick={() => send("Hello")} disabled={busy}>Start</Button>}
              <Button variant="pink" size="lg" onClick={() => send()} disabled={busy || !text.trim()} aria-label="Send">Send<ArrowRight size={16} /></Button>
            </span>
          </div>
        </div>

        {st.pending_story && (
          <Card title="Drafted storyboard" className="mt-5 !border-amber-400/60" right={<Badge tone="amber">waiting for you</Badge>}>
            <p className="text-xs text-slate-400">{AI_NAME} drafted this storyboard. Applying it creates the shots and image list and then asks you to set the budget. Nothing is generated yet.</p>
            <button type="button" className="btn btn-ghost btn-sm mt-2" onClick={() => setShowStory(!showStory)}>{showStory ? "Hide" : "Preview"} storyboard</button>
            {showStory && <pre className="markdown-area mt-2 !font-sans !text-xs">{pending}</pre>}
            <div className="mt-3 flex gap-2"><Button variant="pink" onClick={apply}>Apply storyboard</Button><Button variant="outline" onClick={drop}>Discard draft</Button></div>
          </Card>
        )}
      </div>

      <Modal open={!!plan} onClose={() => setPlan(null)} title="Generate everything that is left?">
        {plan && (
          <div className="space-y-3 text-sm" data-testid="plan">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={st.mode === "real" ? "red" : "green"}>{st.mode === "real" ? "REAL PROJECT: spends money" : "TEST PROJECT: no real money"}</Badge>
              <span className="text-slate-400">{plan.items.length} items, one after the other</span>
            </div>
            <div className="panel-quiet p-3">
              <div className="text-2xl font-extrabold tracking-tight" data-testid="plan-total">{usd(plan.total)}</div>
              <div className="mt-1 text-xs text-slate-400">The exact price of each item is below. Approving starts them in order; the run stops at the first problem, and the usual budget and stop-loss limits still apply to every item.</div>
              {plan.budget.estimate != null && <div className="mt-1 text-xs text-slate-400">Budget {usd(plan.budget.estimate)} · spent so far {usd(plan.budget.spent)}</div>}
              {plan.budget.stop_loss != null && plan.budget.spent + plan.total > plan.budget.stop_loss && <p role="alert" className="mt-2 text-xs text-amber-300">This is more than the stop-loss ({usd(plan.budget.stop_loss)}). The run will stop when the limit is reached.</p>}
            </div>
            <ul className="max-h-60 divide-y divide-slate-800 overflow-auto rounded-xl border border-slate-800">
              {plan.items.map((it) => <li key={`${it.kind}:${it.target}`} className="flex items-center gap-3 px-3 py-2"><span className="min-w-0 flex-1 truncate">{it.label}</span><span className="text-xs text-slate-400">{it.model}</span><span className="font-mono text-xs">{usd(it.price)}</span></li>)}
            </ul>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setPlan(null)}>Cancel</Button>
              <Button variant="pink" onClick={runAll} data-testid="approve-all">Approve and run all {usd(plan.total)}</Button>
            </div>
          </div>
        )}
      </Modal>

      <Modal open={models} onClose={() => setModels(false)} title="Set up models" wide>
        <p className="mb-3 text-sm text-slate-400">Pick the models for chat, vision, image and video. Use the arrows to reorder them: the first is tried first, the next is the fallback.</p>
        <RolesSection reloadKey={0} />
      </Modal>
    </div>
  );
}
