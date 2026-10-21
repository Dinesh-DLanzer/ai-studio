import { useEffect, useState } from "react";
import {
  BarChart3,
  DollarSign,
  Image as ImageIcon,
  PieChart,
  Tag,
  TrendingDown,
  Video as VideoIcon,
  Wallet,
} from "lucide-react";
import { api, fileUrl } from "../api";
import { Badge, Button, Card, IconTile, Input, PageHeader, money, type TileTone } from "../ui";
import { confirmDialog } from "../dialogs";
import { PageBody } from "../app/Shell";
import { RailCard, StatTile } from "../components/kit";
import { fmtDate, type TabProps } from "../ProjectPage";

const MODEL_TONES: TileTone[] = ["pink", "violet", "sky", "amber", "lime"];
const MODEL_TAGS = ["tag-grad", "tag-violet", "tag-sky", "tag-amber", "tag-lime"];
const modelIdx = (m?: string) => {
  const k = String(m || "");
  let h = 0;
  for (const c of k) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h % MODEL_TONES.length;
};
const modelTone = (m?: string) => MODEL_TONES[modelIdx(m)];
const modelTag = (m?: string) => MODEL_TAGS[modelIdx(m)];
const dayLabel = (d: string) => {
  const [m, day] = d.split("-");
  return `${day} ${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m) - 1] || m}`;
};

/** Thumbnail of what a log row produced. */
function CostPreview({ project, r }: { project: string; r: any }) {
  const [bad, setBad] = useState(false);
  const isImg = r.stage === "image";
  const isClip = r.stage === "final";
  const icon = isImg ? <ImageIcon size={16} /> : <VideoIcon size={16} />;
  if (bad || (!isImg && !isClip)) return <div className="thumb grid h-10 w-16 place-items-center text-slate-500">{icon}</div>;
  return (
    <div className="thumb h-10 w-16">
      {isImg ? (
        <img src={fileUrl(project, `stills/${r.shot}.png`)} alt="" loading="lazy" onError={() => setBad(true)} />
      ) : (
        <video src={`${fileUrl(project, `clips/${r.shot}_final_a${r.attempt}.mp4`)}#t=0.5`} preload="metadata" muted playsInline onError={() => setBad(true)} />
      )}
    </div>
  );
}

/** A two-slice ring: used vs discarded. */
function DonutChart({ used, discarded }: { used: number; discarded: number }) {
  const total = used + discarded;
  const pct = total ? discarded / total : 0;
  const r = 20;
  const c = 2 * Math.PI * r;
  return (
    <svg width="86" height="86" viewBox="0 0 48 48" role="img" aria-label={`Used ${money(used)}, discarded ${money(discarded)}`} className="shrink-0">
      <circle cx="24" cy="24" r={r} fill="none" stroke="#d7ff3f" strokeWidth="7" strokeDasharray={`${c * (1 - pct)} ${c}`} transform="rotate(-90 24 24)" />
      <circle cx="24" cy="24" r={r} fill="none" stroke="#ff2d95" strokeWidth="7" strokeDasharray={`${c * pct} ${c}`} strokeDashoffset={-c * (1 - pct)} transform="rotate(-90 24 24)" />
      <text x="24" y="26" textAnchor="middle" className="fill-white" style={{ fontSize: "9px", fontWeight: "700" }}>
        {money(total)}
      </text>
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
            <span className="shrink-0 text-slate-400">
              {money(v)} · {Math.round((v / total) * 100)}%
            </span>
          </div>
          <div className="progress">
            <div className="progress-fill" style={{ width: `${(v / total) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function CostsTab({ o, name, load }: TabProps) {
  const [f, setF] = useState("0.2");
  const [rows, setRows] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const [tab, setTab] = useState<"generations" | "models">("generations");

  useEffect(() => {
    api<any>("GET", `/api/projects/${name}/costs`)
      .then((r) => setRows(r.rows))
      .catch(() => {});
  }, [name, o.costs.total]);

  const est = async () => {
    try {
      await api("POST", `/api/projects/${name}/estimate`, { failure: Number(f) });
      setMsg("Estimated. Approve it below to allow spending.");
      load();
    } catch (e: any) {
      setMsg(e.message);
    }
  };

  const appr = async () => {
    if (
      !(await confirmDialog(`Approve a budget of ${money(o.budget.estimate)} (stop-loss ${money(o.budget.stop_loss)})?`, {
        title: "Approve budget",
        ok: "Approve",
      }))
    )
      return;
    await api("POST", `/api/projects/${name}/budget/approve`);
    load();
  };

  // Spending by day, for the trend chart.
  const byDay = new Map<string, number>();
  rows.forEach((r) => {
    const d = String(r.timestamp || "").slice(5, 10);
    if (d) byDay.set(d, (byDay.get(d) || 0) + Number(r.cost || 0));
  });
  const days = [...byDay.entries()].sort((a, b) => a[0].localeCompare(b[0])).slice(-14);
  const peak = Math.max(0.0001, ...days.map(([, v]) => v));

  return (
    <div className="animate-fade-up">
      <PageHeader title="Costs" sub="Track your token usage, video generation costs, and manage your budget." icon={<Wallet size={24} />} art="/costs-banner.png" />

      <PageBody
        rail={
          <>
            <RailCard
              title={
                <span className="flex items-center gap-2">
                  <IconTile tone="lime">
                    <Wallet size={14} />
                  </IconTile>{" "}
                  Budget &amp; Limits
                </span>
              }
              right={<Badge tone={o.budget.approved ? "green" : "amber"}>{o.budget.approved ? "approved" : "not approved"}</Badge>}
            >
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
                <Button variant="outline" size="sm" className="flex-1" onClick={est}>
                  Estimate
                </Button>
              </div>
              {!!o.budget.estimate && !o.budget.approved && (
                <Button size="sm" className="mt-2 w-full" onClick={appr}>
                  Approve budget
                </Button>
              )}
            </RailCard>
            <RailCard
              title={
                <span className="flex items-center gap-2">
                  <IconTile tone="pink">
                    <Wallet size={14} />
                  </IconTile>{" "}
                  Recent transactions
                </span>
              }
              right={<Badge>{rows.length}</Badge>}
            >
              <ul className="space-y-2">
                {[...rows].slice(0, 6).map((r, i) => (
                  <li key={i} className="flex items-center justify-between gap-2 text-xs">
                    <IconTile tone={modelTone(r.model)}>{r.stage === "image" ? <ImageIcon size={14} /> : <VideoIcon size={14} />}</IconTile>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-semibold text-slate-200">{r.shot || r.stage}</div>
                      <div className="truncate text-slate-400">
                        {String(r.model || "").split("/").pop()} · {r.result}
                      </div>
                    </div>
                    <span className="shrink-0 font-bold">{money(Number(r.cost || 0))}</span>
                  </li>
                ))}
                {!rows.length && <li className="text-xs text-slate-400">Nothing spent yet.</li>}
              </ul>
            </RailCard>
          </>
        }
      >
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
                  <IconTile tone={c.tile} size="lg">
                    {c.icon}
                  </IconTile>
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
            <Card
              title={
                <span className="flex items-center gap-2.5">
                  <IconTile tone="violet" size="lg">
                    <BarChart3 size={20} />
                  </IconTile>
                  Spending Trend
                </span>
              }
              sub="Daily usage and cost breakdown"
            >
              {days.length ? (
                <div className="flex h-44 items-stretch gap-2 pt-4">
                  {days.map(([d, v], bi) => (
                    <div key={d} className="flex h-full min-w-0 flex-1 flex-col justify-end gap-1.5">
                      <span className="text-center text-[0.6rem] text-slate-400">{money(v)}</span>
                      <div
                        className={`w-full rounded-t-md bg-gradient-to-t ${["from-pink to-orange", "from-violet to-pink", "from-sky to-violet"][bi % 3]}`}
                        style={{ height: `${Math.max(4, (v / peak) * 100)}%` }}
                      />
                      <span className="truncate text-center text-[0.6rem] text-slate-400">{dayLabel(d)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="py-10 text-center text-sm text-slate-400">Nothing spent yet.</p>
              )}
            </Card>

            <Card
              title={
                <span className="flex items-center gap-2.5">
                  <IconTile tone="lime" size="lg">
                    <PieChart size={20} />
                  </IconTile>
                  Spend: used vs discarded
                </span>
              }
            >
              <div className="flex items-center gap-4 py-4">
                <DonutChart used={o.costs.used} discarded={o.costs.discarded} />
                <ul className="min-w-0 flex-1 space-y-2 text-xs">
                  <li className="flex items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5">
                      <i className="h-2 w-2 rounded-full bg-brand" />
                      Used
                    </span>
                    <b>{money(o.costs.used)}</b>
                  </li>
                  <li className="flex items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5">
                      <i className="h-2 w-2 rounded-full bg-pink" />
                      Discarded
                    </span>
                    <b>{money(o.costs.discarded)}</b>
                  </li>
                  <li className="divider !my-2" />
                  <li className="flex items-center justify-between gap-2 font-bold">
                    <span>Total</span>
                    <span>{money(o.costs.total)}</span>
                  </li>
                </ul>
              </div>
            </Card>
          </div>

          <section className="panel panel-lit panel-pad" aria-label="Cost log">
            <div role="tablist" aria-label="Cost breakdown" className="mb-4 flex flex-wrap gap-2">
              {(["generations", "models"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  aria-selected={tab === t}
                  onClick={() => setTab(t)}
                  className={`pill capitalize ${tab === t ? "" : "!bg-slate-900"}`}
                >
                  {t === "models" ? "Model Usage" : "Generations"}
                </button>
              ))}
            </div>

            {tab !== "generations" ? (
              <UsageBreakdown rows={rows} />
            ) : (
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Preview</th>
                      <th>Scene / Prompt</th>
                      <th>Model</th>
                      <th>Duration</th>
                      <th className="text-right">Cost</th>
                      <th>Result</th>
                      <th>Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={i}>
                        <td className="font-mono text-slate-400">{String(i + 1).padStart(2, "0")}</td>
                        <td>
                          <CostPreview project={name} r={r} />
                        </td>
                        <td className="max-w-[16rem] truncate font-semibold">{r.shot || r.stage}</td>
                        <td>
                          <span className={`tag ${modelTag(r.model)}`}>{String(r.model || "").split("/").pop()}</span>
                        </td>
                        <td className="text-slate-400">{r.seconds ? `${r.seconds}.0s` : "—"}</td>
                        <td className="text-right font-bold">{money(Number(r.cost || 0))}
                          {r.over_quoted && <div className="text-[0.7rem] font-semibold text-amber-300" data-testid="over-quoted">Charged more than the {money(Number(r.quoted))} quote</div>}
                        </td>
                        <td>
                          <Badge
                            tone={
                              r.result === "completed" || r.result === "done" || r.result === "ok"
                                ? "green"
                                : r.result === "error" || r.result === "failed"
                                ? "red"
                                : "amber"
                            }
                          >
                            {r.result}
                          </Badge>
                        </td>
                        <td className="whitespace-nowrap text-slate-400">{fmtDate(r.timestamp)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!rows.length && <p className="py-6 text-center text-sm text-slate-400">Nothing spent yet.</p>}
              </div>
            )}
            {msg && <p className="mt-3 text-xs text-brand">{msg}</p>}
            <p className="mt-3 text-[0.7rem] text-slate-400">
              Nothing can be generated until the budget is approved. Changing shots or images means estimating and approving again.
            </p>
          </section>
        </div>
      </PageBody>
    </div>
  );
}
