import { useEffect, useState } from "react";
import { Coins, Cpu, KeyRound, Plug, SlidersHorizontal, Sparkles } from "lucide-react";
import { Card, Input, IconTile, PageHeader } from "./ui";
import { useToast } from "./toast";
import { confirmDialog } from "./dialogs";
import ProvidersSection from "./settings/Providers";
import RolesSection from "./settings/Roles";
import IntegrationsSection from "./settings/Integrations";
import { settingsApi } from "./settings/client";
import type { RolesResponse } from "./settings/types";

const SECTIONS = [
  { id: "set-providers", label: "AI Providers", sub: "Connect & manage providers", icon: <Sparkles size={17} /> },
  { id: "set-models", label: "Model Configuration", sub: "Assign models for each process", icon: <Cpu size={17} /> },
  { id: "set-limits", label: "Usage & Limits", sub: "Track usage and set limits", icon: <Coins size={17} /> },
  { id: "set-integrations", label: "Integrations", sub: "Connect agents (MCP) and API keys", icon: <Plug size={17} /> },
  { id: "set-prefs", label: "Preferences", sub: "App preferences", icon: <SlidersHorizontal size={17} /> },
];

/** Settings: connect providers, give every process (chat, verify, vision, image, video) an ordered chain of models, set spending limits. */
export default function Settings() {
  const toast = useToast();
  const [key, setKey] = useState(0);
  const [limits, setLimits] = useState<RolesResponse | null>(null);
  const [active, setActive] = useState(SECTIONS[0].id);

  const load = () => settingsApi.roles().then(setLimits).catch((e) => toast("error", e.message));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [key]);

  // highlight the section being read
  useEffect(() => {
    const io = new IntersectionObserver((es) => { const v = es.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]; if (v) setActive(v.target.id); }, { rootMargin: "-20% 0px -60% 0px" });
    SECTIONS.forEach((s) => { const el = document.getElementById(s.id); if (el) io.observe(el); });
    return () => io.disconnect();
  }, []);

  const jump = (id: string) => { document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }); setActive(id); };
  const save = async (b: { allow_paid?: boolean; ai_cap_usd?: number; auto_verify?: boolean }) => {
    try { setLimits(await settingsApi.putLimits(b)); toast("ok", "Saved."); } catch (e: any) { toast("error", e.message); load(); }
  };
  const togglePaid = async (on: boolean) => {
    if (on && !(await confirmDialog("Paid or unpriced models charge your provider account for every chat message and every verification. Each call is logged in the project's Costs tab and stops at the AI spending cap below.\n\nAllow paid models?", { title: "Allow paid models?", ok: "Allow", danger: true }))) return;
    save({ allow_paid: on });
  };

  return (
    <div className="animate-fade-up">
      <PageHeader title="Settings" sub="Configure AI providers, models and preferences for your AI video workflow." icon={<Cpu size={24} />} />

      <div className="grid gap-5 lg:grid-cols-[16rem_minmax(0,1fr)]">
        <nav aria-label="Settings sections" className="panel panel-lit h-max p-2 lg:sticky lg:top-[4.75rem]">
          {SECTIONS.map((s) => {
            const on = active === s.id;
            return (
              <button key={s.id} type="button" onClick={() => jump(s.id)} aria-current={on ? "true" : undefined}
                className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left transition ${on ? "bg-pink/15 text-white ring-1 ring-pink/40" : "hover:bg-slate-300/8"}`}>
                <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${on ? "bg-pink/25 text-pink" : "bg-slate-300/10 text-slate-300"}`}>{s.icon}</span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-bold">{s.label}</span>
                  <span className="block truncate text-[0.68rem] text-slate-400">{s.sub}</span>
                </span>
              </button>
            );
          })}
        </nav>

        <div className="min-w-0 space-y-5">
          <section id="set-providers" className="scroll-mt-24"><ProvidersSection onChanged={() => setKey((k) => k + 1)} /></section>
          <section id="set-models" className="scroll-mt-24"><RolesSection reloadKey={key} /></section>

          <section id="set-limits" className="scroll-mt-24">
            <Card title={<span className="flex items-center gap-2"><IconTile tone="lime"><Coins size={15} /></IconTile> Usage &amp; Limits</span>}
              sub="Paid models cost money. Nothing is generated or spent without your approval.">
              {!limits ? <p className="text-sm text-slate-400">Loading...</p> : (
                <>
                  <label className="flex items-start gap-2.5 text-sm">
                    <input type="checkbox" className="mt-1" checked={limits.allow_paid} onChange={(e) => togglePaid(e.target.checked)} aria-label="Allow paid models" />
                    <span className="text-slate-200"><b>Allow paid and unpriced text models.</b> <span className="text-slate-400">Off by default: chat and verification only use models marked free. When on, every call is logged as cost and stops at the cap. Images and videos always need your approval at an exact price, whatever this setting says.</span></span>
                  </label>
                  <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
                    <label className="inline-flex items-center gap-2">AI spending cap per project (USD)
                      <Input className="!w-24" type="number" min={0} max={100} step={0.1} defaultValue={limits.ai_cap_usd} key={limits.ai_cap_usd}
                        onBlur={(e) => { const v = Number(e.target.value); if (v !== limits.ai_cap_usd) save({ ai_cap_usd: v }); }} aria-label="AI spending cap" />
                    </label>
                    <span className="text-xs text-slate-400">Only applies to paid text models. Free models cost $0.</span>
                  </div>
                </>
              )}
            </Card>
          </section>

          <section id="set-integrations" className="scroll-mt-24"><IntegrationsSection /></section>

          <section id="set-prefs" className="scroll-mt-24">
            <Card title={<span className="flex items-center gap-2"><IconTile tone="sky"><SlidersHorizontal size={15} /></IconTile> Preferences</span>} sub="How the app behaves day to day.">
              {limits && (
                <label className="flex items-center gap-2.5 text-sm">
                  <input type="checkbox" checked={limits.auto_verify} onChange={(e) => save({ auto_verify: e.target.checked })} aria-label="Verify automatically after every change" />
                  <span className="text-slate-200">Verify automatically with AI after every change <span className="text-slate-400">(the free rule checks always run)</span></span>
                </label>
              )}
              <p className="mt-4 flex items-start gap-2 text-xs text-slate-400"><KeyRound size={14} className="mt-0.5 shrink-0" />API keys are write-only: once saved they are never shown again, and they are never stored in your project folders.</p>
            </Card>
          </section>
        </div>
      </div>
    </div>
  );
}
