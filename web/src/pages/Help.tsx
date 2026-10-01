import { useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { BookOpen, CircleHelp, ExternalLink, Keyboard, LifeBuoy, MessageCircle, Plug, Rocket, Settings as SettingsIcon, Sparkles, FolderOpen } from "lucide-react";
import { Card, IconTile, PageHeader } from "../ui";
import { RailCard } from "../components/kit";
import { PageBody } from "../app/Shell";
import { REPO_URL } from "../brand";
import ApiReference from "./help/ApiReference";
import { BENEFITS, FAQ, FEATURES, FLOW, GUIDES, KINDS, SETUP, SHORTCUTS, TROUBLE } from "./help/content";

const TABS = [
  { id: "start", label: "Getting Started", icon: <Rocket size={15} /> },
  { id: "guides", label: "Guides", icon: <BookOpen size={15} /> },
  { id: "features", label: "Features", icon: <Sparkles size={15} /> },
  { id: "api", label: "API & Integrations", icon: <Plug size={15} /> },
  { id: "trouble", label: "Troubleshooting", icon: <LifeBuoy size={15} /> },
  { id: "faq", label: "FAQ", icon: <CircleHelp size={15} /> },
] as const;
type Tab = (typeof TABS)[number]["id"];

/** One collapsible entry: native <details>, so it works with the keyboard and without any state. */
const Item = ({ title, sub, open, children }: { title: ReactNode; sub?: ReactNode; open?: boolean; children: ReactNode }) => (
  <details open={open} className="group rounded-xl border border-slate-800 bg-white/[.02] open:bg-white/[.04]">
    <summary className="flex cursor-pointer list-none items-start gap-3 px-4 py-3">
      <span className="min-w-0 flex-1"><span className="block text-sm font-bold">{title}</span>{sub && <span className="mt-0.5 block text-xs text-slate-400">{sub}</span>}</span>
      <span className="mt-1 text-slate-400 transition-transform group-open:rotate-180" aria-hidden>▾</span>
    </summary>
    <div className="border-t border-slate-800 px-4 py-3 text-sm leading-relaxed text-slate-300 [&_code]:rounded [&_code]:bg-white/10 [&_code]:px-1 [&_code]:text-[0.8em] [&_kbd]:rounded [&_kbd]:border [&_kbd]:border-slate-700 [&_kbd]:bg-slate-900 [&_kbd]:px-1.5 [&_kbd]:text-[0.75em]">{children}</div>
  </details>
);

export default function Help() {
  const [sp, setSp] = useSearchParams();
  const asked = sp.get("tab") as Tab | null;
  const [tab, setTabState] = useState<Tab>(TABS.some((t) => t.id === asked) ? (asked as Tab) : "start");
  const setTab = (t: Tab) => { setTabState(t); setSp(t === "start" ? {} : { tab: t }, { replace: true }); };
  const link = "flex items-center gap-2.5 rounded-lg px-2 py-2 text-xs font-bold row-hover";

  return (
    <div className="animate-fade-up">
      <PageHeader title="Help &" accent="Documentation" sub="Set it up, make your first video, connect your agents, and fix what goes wrong." icon={<BookOpen size={24} />} />

      <div role="tablist" aria-label="Help categories" className="mb-5 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)} className={`pill !px-4 !py-2.5 ${tab === t.id ? "" : "!bg-slate-900"}`}>
            {t.icon}{t.label}
          </button>
        ))}
      </div>

      <PageBody stickyRail rail={<>
        <RailCard title={<span className="flex items-center gap-2"><IconTile><ExternalLink size={14} /></IconTile> Go to</span>}>
          <ul className="space-y-0.5">
            <li><Link to="/" className={link}><FolderOpen size={14} className="text-slate-300" />Projects</Link></li>
            <li><Link to="/settings" className={link}><SettingsIcon size={14} className="text-slate-300" />Settings: providers, models, keys</Link></li>
            <li><button type="button" onClick={() => setTab("api")} className={`${link} w-full text-left`}><Plug size={14} className="text-slate-300" />API reference and MCP setup</button></li>
            <li><a href={REPO_URL} target="_blank" rel="noreferrer" className={link}><BookOpen size={14} className="text-slate-300" />README and source on GitHub</a></li>
          </ul>
        </RailCard>

        <RailCard title={<span className="flex items-center gap-2"><IconTile tone="sky"><Keyboard size={14} /></IconTile> Shortcuts</span>}>
          <dl className="space-y-2 text-xs">
            {SHORTCUTS.map(([k, d]) => <div key={k}><dt><kbd className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 font-mono text-[0.7rem]">{k}</kbd></dt><dd className="mt-0.5 text-slate-400">{d}</dd></div>)}
          </dl>
        </RailCard>

        <div className="panel panel-lit relative overflow-hidden p-5">
          <div className="pointer-events-none absolute -right-10 -top-12 h-32 w-32 rounded-full bg-violet/25 blur-2xl" aria-hidden />
          <div className="relative">
            <div className="flex items-center gap-2 text-sm font-bold"><MessageCircle size={17} className="text-pink" />Still stuck?</div>
            <p className="mt-1.5 text-xs text-slate-400">Check Troubleshooting first. For a bug or an idea, open an issue with what you did and what you saw (never paste a key or a token).</p>
            <a href={`${REPO_URL}issues`} target="_blank" rel="noreferrer" className="btn btn-grad btn-sm mt-3 w-full">Open an issue</a>
          </div>
        </div>
      </>}>
        <div className="space-y-4">
          {tab === "start" && (
            <>
              <Card title="What AI Studio does for you" sub="A local studio that turns an idea into a finished short video, with you in charge of every decision and every cent.">
                <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {BENEFITS.map((b) => <li key={b.title} className="panel-quiet p-3.5"><div className="text-sm font-bold">{b.title}</div><p className="mt-1 text-xs leading-relaxed text-slate-400">{b.text}</p></li>)}
                </ul>
              </Card>

              <Card title={<span className="flex items-center gap-2"><IconTile tone="violet"><Rocket size={15} /></IconTile> Set it up</span>} sub="About five minutes, once.">
                <ol className="space-y-3">
                  {SETUP.map((s, i) => (
                    <li key={s.title} className="flex gap-3">
                      <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-gradient-to-br from-pink to-violet text-xs font-extrabold text-white" aria-hidden>{i + 1}</span>
                      <div className="min-w-0 text-sm text-slate-300 [&_code]:rounded [&_code]:bg-white/10 [&_code]:px-1 [&_code]:text-[0.8em]"><div className="font-bold text-slate-100">{s.title}</div><p className="mt-0.5 leading-relaxed text-slate-400">{s.text}</p></div>
                    </li>
                  ))}
                </ol>
              </Card>

              <Card title="From idea to MP4" sub="The same order every time. The app enforces it, so you never generate something that depends on a step you skipped.">
                <ol className="space-y-2">
                  {FLOW.map((f) => (
                    <li key={f.n} className="grid gap-2 rounded-xl border border-slate-800 bg-white/[.02] p-3 sm:grid-cols-[9rem_1fr_1fr]">
                      <div className="flex items-center gap-2 text-sm font-bold"><span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-slate-300/10 text-xs">{f.n}</span>{f.name}</div>
                      <p className="text-xs leading-relaxed text-slate-300"><span className="font-bold text-slate-100">You: </span>{f.you}</p>
                      <p className="text-xs leading-relaxed text-slate-400"><span className="font-bold text-slate-300">The app: </span>{f.app}</p>
                    </li>
                  ))}
                </ol>
              </Card>

              <Card title="Safety rules" sub="Promises the app keeps, enforced by the server, not just by the screens.">
                <ul className="list-disc space-y-1.5 pl-5 text-sm text-slate-300">
                  <li>Every paid action shows its exact price and runs only after a human approves that exact request. If the prompt, model, price or input image changes afterwards, the approval is void.</li>
                  <li>A budget must be approved first. Generation stops at 130% of the estimate and after 3 final attempts per shot, unless you override on purpose.</li>
                  <li>Nothing is ever deleted: replaced or rejected files go to Discarded, deleted projects go to the trash, and both can be restored.</li>
                  <li>Agents and API keys can propose but never approve. Provider keys are write-only: once saved they are never shown again.</li>
                </ul>
              </Card>

              <Card title="Test project or real project" sub="Decided per project, from what it contains. There is no global mode switch.">
                <div className="overflow-x-auto"><table className="w-full text-left text-xs">
                  <thead><tr className="text-slate-400"><th className="py-2 pr-3 font-semibold" scope="col"> </th><th className="py-2 pr-3 font-semibold" scope="col">Test project</th><th className="py-2 font-semibold" scope="col">Real project</th></tr></thead>
                  <tbody className="divide-y divide-slate-800">{KINDS.map((k) => <tr key={k.row}><th scope="row" className="py-2 pr-3 align-top font-bold text-slate-200">{k.row}</th><td className="py-2 pr-3 align-top text-slate-300">{k.test}</td><td className="py-2 align-top text-slate-300">{k.real}</td></tr>)}</tbody>
                </table></div>
              </Card>
            </>
          )}

          {tab === "guides" && (
            <Card title={<span className="flex items-center gap-2"><IconTile tone="pink"><BookOpen size={15} /></IconTile> Guides</span>} sub="One guide per part of the app. Open the one you need.">
              <div className="space-y-2" data-testid="guides">
                {GUIDES.map((g, i) => <Item key={g.id} open={i === 0} title={g.title} sub={g.summary}>{g.body}</Item>)}
              </div>
            </Card>
          )}

          {tab === "features" && (
            <Card title={<span className="flex items-center gap-2"><IconTile tone="violet"><Sparkles size={15} /></IconTile> What is inside</span>} sub="The capabilities that are not obvious from the screens.">
              <ul className="grid gap-3 sm:grid-cols-2">
                {FEATURES.map((f) => <li key={f.title} className="panel-quiet p-3.5"><div className="text-sm font-bold">{f.title}</div><p className="mt-1 text-xs leading-relaxed text-slate-400">{f.text}</p></li>)}
              </ul>
            </Card>
          )}

          {tab === "api" && <ApiReference />}

          {tab === "trouble" && (
            <Card title={<span className="flex items-center gap-2"><IconTile tone="amber"><LifeBuoy size={15} /></IconTile> Troubleshooting</span>} sub="The problem, then what to do.">
              <div className="space-y-2" data-testid="trouble">{TROUBLE.map((t) => <Item key={t.problem} title={t.problem}>{t.fix}</Item>)}</div>
            </Card>
          )}

          {tab === "faq" && (
            <Card title={<span className="flex items-center gap-2"><IconTile tone="sky"><CircleHelp size={15} /></IconTile> Frequently asked questions</span>}>
              <div className="space-y-2" data-testid="faq">{FAQ.map((f) => <Item key={f.q} title={f.q}>{f.a}</Item>)}</div>
            </Card>
          )}
        </div>
      </PageBody>
    </div>
  );
}
