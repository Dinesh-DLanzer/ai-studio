import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Check, CheckCheck, Circle, FolderOpen, Image as ImageIcon, Sliders, X } from "lucide-react";
import { fileUrl } from "./api";
import RolesSection from "./settings/Roles";
import { Badge, Button, Card, Field, Modal } from "./ui";
import { Spinner, type Running } from "./Proposal";
import type { ImageSpec, NextStep } from "./types";
import { LogoMark } from "./components/kit";
import { Markdown } from "./Markdown";
import { AI_NAME } from "./brand";
import { useChatStream } from "./hooks/useChatStream";
import { useBatchPipeline } from "./hooks/useBatchPipeline";
import { api } from "./api";

const clock = (ts: string) => { const d = new Date(ts); return ts && !isNaN(+d) ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : ""; };

const usd = (n: number) => `$${n < 1 ? n.toFixed(3) : n.toFixed(2)}`;

export default function Chat({ project, reloadAll, onApplied, openBudget, start, running, refreshKey }: {
  project: string; reloadAll: () => void; onApplied: () => void; openBudget: () => void; start: (k: "image" | "clip" | "review", t: string) => void | Promise<void>; running: Running; refreshKey?: unknown;
}) {
  const nav = useNavigate();
  const [showStory, setShowStory] = useState(false);
  const [models, setModels] = useState(false);

  const runAllRef = useRef<() => Promise<void>>(undefined);

  const {
    st,
    text,
    setText,
    busy,
    pending,
    files,
    setFiles,
    assetPickerOpen,
    setAssetPickerOpen,
    projectAssets,
    log,
    attach,
    load,
    send,
    attachFile,
    openAssetPicker,
    attachExistingAsset,
    apply,
  } = useChatStream({ project, reloadAll, onApplied, refreshKey, onBatchGenerate: () => runAllRef.current?.() });

  const { plan, setPlan, clicking, setClicking, batch, working, openPlan, runAll } = useBatchPipeline({
    project,
    running,
    reloadAll,
    load,
  });
  runAllRef.current = runAll;

  const act = async (n: NextStep) => {
    if (working) return;
    if (n.kind === "apply-story") void apply();
    else if (n.kind === "budget") openBudget();
    else if (n.kind === "image" || n.kind === "clip") {
      setClicking(true);
      try {
        await start(n.kind, n.target || "");
      } finally {
        setClicking(false);
      }
    } else if (n.kind === "approve") nav(`/p/${project}/shots`);
    else if (n.kind === "export") nav(`/p/${project}/review`);
  };

  const drop = async () => {
    await api("POST", `/api/projects/${project}/story/discard-pending`);
    await load();
  };
  if (!st) return <p className="text-slate-400">Loading...</p>;
  const first = st.messages.length === 0;
  const next = st.progress?.next;
  const queue = st.progress?.queue || [];

  return (
    <div className="animate-fade-up flex flex-col h-[calc(100vh-5.5rem)] w-full">
      <header className="page-head relative md:min-h-[8rem] !py-3.5 px-1 shrink-0 mb-3 w-full border-b border-slate-800/60">
        <img src="/chat-banner.png" alt="" aria-hidden className="pointer-events-none absolute -top-1 right-0 hidden h-[9.5rem] w-auto select-none md:block object-contain" style={{ position: "absolute" }} />
        <div className="w-full pr-0 md:pr-80">
          <h1 className="page-title !text-2xl sm:!text-3xl md:!text-4xl">Chat with <span className="grad-text">{AI_NAME}</span></h1>
          <p className="mt-1 text-xs sm:text-sm text-slate-400 max-w-2xl">Describe your idea and I'll interview you, write the storyboard and guide you to the finished video.</p>
        </div>
      </header>

      <div className="flex-1 min-h-0 flex flex-col">
        {/* Messages container - takes available space and scrolls */}
        <div ref={log} className="chat-log flex-1 overflow-y-auto pr-1 pb-2 min-h-[14rem]" role="log" aria-live="polite" aria-label="Conversation">
          {first && <div className="rounded-xl border border-dashed border-slate-700 p-4 text-sm text-slate-400">Say hello to begin, or describe your video in a sentence or two.</div>}
          {st.messages.map((m, i) => {
            const user = m.role === "user";
            return (
              <div key={i} className={`flex items-start gap-3 ${user ? "justify-end" : ""}`}>
                {!user && <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-slate-800 bg-slate-900" aria-hidden><LogoMark size={22} /></span>}
                {user && <span className="avatar !h-10 !w-10 shrink-0" aria-hidden>Y</span>}
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

        {/* Drafted Storyboard Card (if waiting) */}
        {st.pending_story && (
          <Card title="Drafted storyboard" className="my-2 shrink-0 !border-amber-400/60" right={<Badge tone="amber">waiting for you</Badge>}>
            <p className="text-xs text-slate-400">{AI_NAME} drafted this storyboard. Applying it creates the shots and image list and then asks you to set the budget. Nothing is generated yet.</p>
            <button type="button" className="btn btn-ghost btn-sm mt-2" onClick={() => setShowStory(!showStory)}>{showStory ? "Hide" : "Preview"} storyboard</button>
            {showStory && <pre className="markdown-area mt-2 max-h-48 overflow-y-auto !font-sans !text-xs">{pending}</pre>}
            <div className="mt-3 flex gap-2"><Button variant="pink" onClick={apply}>Apply storyboard</Button><Button variant="outline" onClick={drop}>Discard draft</Button></div>
          </Card>
        )}

        {/* Sticky bottom area: Checklist + Composer */}
        <div className="shrink-0 pt-2 bg-gradient-to-t from-slate-950 via-slate-950 to-transparent">
          {st.progress && st.progress.groups.length > 0 && (
            <section className="panel panel-lit panel-pad mb-2.5 !p-2.5 sm:!p-3" aria-label="Production checklist" data-testid="checklist">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
                <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400">Production checklist</h2>
                <ul className="flex flex-1 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-300">
                  {st.progress.groups.map((g) => { const ok = g.total > 0 && g.done >= g.total; return (
                    <li key={g.key} className={`inline-flex items-center gap-1 ${ok ? "text-emerald-300" : ""}`}>{ok ? <Check size={13} aria-label="done" /> : <Circle size={11} aria-label="to do" />}{g.label} <span className="text-slate-400">{g.done}/{g.total}</span></li>); })}
                </ul>
              </div>
              {next && (
                <div className="mt-2 flex flex-wrap items-center gap-3 border-t border-slate-800/80 pt-2">
                  <span className="text-[0.7rem] uppercase tracking-wider text-slate-400 font-bold">Next</span>
                  <span className="min-w-0 flex-1 text-xs sm:text-sm font-semibold truncate" data-testid="next-step">{next.label}</span>
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

          <div className="chat-composer">
            <Field rows={2} placeholder={"Type your message or idea here... (Press Enter to send, Shift+Enter for new line)"} aria-label="Message" value={text}
              onChange={(e) => setText(e.target.value)} disabled={busy}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
            <input ref={attach} type="file" accept="image/*" className="sr-only" aria-label="Attach an image (logo, product photo, reference)" tabIndex={-1} onChange={(e) => { attachFile(e.target.files?.[0]); e.target.value = ""; }} />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <button type="button" className="icon-btn !h-10 !w-10" aria-label="Upload an image" title="Upload an image: logo, photo or reference" onClick={() => attach.current?.click()}><ImageIcon size={16} /></button>
              <button type="button" className="icon-btn !h-10 !w-10" aria-label="Attach from Assets" title="Attach an image from your project assets" onClick={openAssetPicker}><FolderOpen size={16} /></button>
              <button type="button" className="icon-btn !h-10 !w-10" aria-label="Set up models" title="Set up models" onClick={() => setModels(true)}><Sliders size={16} /></button>
              {files.map((f) => (
                <span key={f.id} data-testid="pending-attachment" className="inline-flex h-10 items-center gap-2 rounded-xl border border-slate-800 bg-white/[.03] py-1 pl-1 pr-2 text-xs">
                  <img src={fileUrl(project, `stills/${f.file}`)} alt="" className="h-8 w-8 rounded-lg object-cover" />{f.id}
                  <button type="button" className="text-slate-400 hover:text-white" aria-label={`Remove ${f.id} from the next message`} onClick={() => setFiles((x) => x.filter((y) => y.id !== f.id))}><X size={13} /></button>
                </span>
              ))}
              <span className="ml-auto flex items-center gap-2">
                {first && <Button variant="outline" size="sm" onClick={() => send("Hello")} disabled={busy}>Start</Button>}
                <Button variant="pink" size="sm" onClick={() => send()} disabled={busy || !text.trim()} aria-label="Send">Send<ArrowRight size={15} /></Button>
              </span>
            </div>
          </div>
        </div>
      </div>

      <Modal open={assetPickerOpen} onClose={() => setAssetPickerOpen(false)} title="Attach from Assets" wide>
        <div className="space-y-4">
          <p className="text-sm text-slate-400">Choose images already in your project assets or uploads to attach to your chat message.</p>
          {projectAssets.length === 0 ? (
            <div className="rounded-xl border border-slate-800 p-8 text-center text-sm text-slate-400">
              No assets found yet in this project. You can upload an image using the upload button.
            </div>
          ) : (
            <div className="grid max-h-[60vh] grid-cols-2 gap-3 overflow-y-auto sm:grid-cols-3 md:grid-cols-4">
              {projectAssets.map((asset) => {
                const selected = files.some((f) => f.id === asset.id);
                return (
                  <div
                    key={asset.id}
                    onClick={() => attachExistingAsset(asset)}
                    className={`group relative cursor-pointer overflow-hidden rounded-xl border transition-all ${
                      selected ? "border-pink-500 ring-2 ring-pink-500/50" : "border-slate-800 hover:border-slate-600 bg-slate-900/40"
                    }`}
                  >
                    <div className="aspect-video w-full overflow-hidden bg-black/40">
                      <img
                        src={fileUrl(project, `stills/${asset.file}`)}
                        alt={asset.id}
                        className="h-full w-full object-cover transition-transform group-hover:scale-105"
                      />
                    </div>
                    <div className="flex items-center justify-between p-2 text-xs">
                      <div className="min-w-0">
                        <div className="truncate font-semibold text-slate-200">{asset.id}</div>
                        {asset.kind && <div className="text-[10px] text-slate-400 capitalize">{asset.kind}</div>}
                      </div>
                      <div className={`grid h-5 w-5 place-items-center rounded-md border text-[10px] ${
                        selected ? "border-pink-500 bg-pink-500 text-white" : "border-slate-700 bg-slate-800 text-transparent"
                      }`}>
                        ✓
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          <div className="flex items-center justify-between border-t border-slate-800 pt-3">
            <span className="text-xs text-slate-400">{files.length} of 4 images selected</span>
            <Button variant="pink" size="sm" onClick={() => setAssetPickerOpen(false)}>Done</Button>
          </div>
        </div>
      </Modal>

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
