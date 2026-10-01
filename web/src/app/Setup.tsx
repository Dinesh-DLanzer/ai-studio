import { useCallback, useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Circle, Cpu, Sparkles } from "lucide-react";
import { Button } from "../ui";
import { Logo } from "../components/kit";
import ProvidersSection from "../settings/Providers";
import RolesSection from "../settings/Roles";

export interface SetupStatus {
  needed: boolean; locked: boolean; providers: { ready: string[]; total: number };
  roles: Record<"chat" | "image" | "video", { title: string; ready: boolean; models: string[]; problems: string[]; required: boolean }>;
}

const Step = ({ n, done, title, text }: { n: number; done: boolean; title: string; text: string }) => (
  <li className="flex items-start gap-3">
    <span className={`mt-0.5 shrink-0 ${done ? "text-emerald-400" : "text-slate-400"}`}>{done ? <CheckCircle2 size={20} aria-label="done" /> : <Circle size={20} aria-label="to do" />}</span>
    <div className="min-w-0"><div className="text-sm font-bold">{n}. {title}</div><div className="text-xs text-slate-400">{text}</div></div>
  </li>
);

/** First run: nothing else is usable until a provider is connected and a chat model is chosen. Shown instead of the whole app. */
export default function Setup({ status, refresh, onContinue, onBack }: { status: SetupStatus; refresh: () => Promise<void> | void; onContinue: () => void; onBack?: () => void }) {
  const [key, setKey] = useState(0);
  const changed = useCallback(() => { setKey((k) => k + 1); void refresh(); }, [refresh]);
  useEffect(() => { void refresh(); }, [key, refresh]);
  const hasProvider = status.providers.ready.length > 0; const chat = status.roles.chat; const done = hasProvider && chat.ready;
  return (
    <div className="mx-auto max-w-5xl px-4 py-8" data-testid="setup">
      <div className="mb-6 flex items-center justify-between gap-3"><Logo />{onBack && <Button variant="outline" size="sm" onClick={onBack} data-testid="setup-back">Back</Button>}</div>
      <h1 className="text-3xl font-extrabold tracking-tight">Set up <span className="text-pink">AI Studio</span></h1>
      <p className="mt-2 max-w-2xl text-sm text-slate-400">Before you make your first video, connect an AI provider and choose the models AI Studio should use. Your keys stay on this computer, are never shown again, and nothing is spent without your approval.</p>

      <div className="panel panel-lit panel-pad mt-6">
        <ol className="grid gap-4 md:grid-cols-3" aria-label="Setup steps">
          <Step n={1} done={hasProvider} title="Connect a provider" text={hasProvider ? `${status.providers.ready.length} connected` : "Add OpenRouter, Google, OpenAI, Anthropic or any compatible server, with its API key."} />
          <Step n={2} done={chat.ready} title="Choose a chat model" text={chat.ready ? chat.models.join(", ") : "Pick at least one model for Chat in Model Configuration below."} />
          <Step n={3} done={status.roles.image.ready && status.roles.video.ready} title="Image and video models" text={status.roles.image.ready && status.roles.video.ready ? "Ready to generate." : "Recommended before generating. You can finish this later in Settings."} />
        </ol>
        <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-slate-800 pt-4">
          <Button disabled={!done} onClick={onContinue} data-testid="setup-continue"><ArrowRight size={16} />{done ? "Continue to AI Studio" : "Finish steps 1 and 2 to continue"}</Button>
          {done && <span className="text-xs text-emerald-300" role="status">You are ready. You can change any of this later in Settings.</span>}
        </div>
      </div>

      <div className="mt-6 space-y-5">
        <section aria-label="AI Providers"><ProvidersSection onChanged={changed} /></section>
        {hasProvider
          ? <section aria-label="Model Configuration"><RolesSection reloadKey={key} onChanged={() => void refresh()} /></section>
          : <div className="panel panel-lit panel-pad flex items-center gap-3 text-sm text-slate-400"><Cpu size={18} /><span>Model Configuration unlocks after you connect a provider.</span><Sparkles size={14} className="ml-auto" /></div>}
      </div>
    </div>
  );
}
