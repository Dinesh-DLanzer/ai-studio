import { FlaskConical, KeyRound } from "lucide-react";
import { Logo } from "../components/kit";

/** First run with no provider: ask how to start. Real videos need a provider; a test project needs nothing and costs nothing. */
export default function Welcome({ onSetup, onTrial }: { onSetup: () => void; onTrial: () => void }) {
  return (
    <div className="mx-auto max-w-3xl px-4 py-10" data-testid="welcome">
      <div className="mb-6"><Logo /></div>
      <h1 className="text-3xl font-extrabold tracking-tight">Welcome to <span className="text-pink">AI Studio</span></h1>
      <p className="mt-2 text-sm text-slate-400">No AI provider is connected yet. How do you want to start?</p>
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <button type="button" onClick={onSetup} data-testid="choose-setup"
          className="panel panel-lit group flex flex-col items-start gap-3 p-5 text-left transition hover:border-pink/60 focus-visible:border-pink/60">
          <span className="grid h-11 w-11 place-items-center rounded-xl border border-pink/40 bg-pink/10 text-pink"><KeyRound size={20} /></span>
          <span className="text-lg font-extrabold">Set up a provider</span>
          <span className="text-sm text-slate-400">Connect OpenRouter, Google, OpenAI or another provider with your own API key and choose your models, to generate real AI videos. Nothing is spent without your approval.</span>
          <span className="mt-auto text-xs font-bold uppercase tracking-wider text-pink">Recommended for real videos</span>
        </button>
        <button type="button" onClick={onTrial} data-testid="choose-trial"
          className="panel panel-lit group flex flex-col items-start gap-3 p-5 text-left transition hover:border-sky/60 focus-visible:border-sky/60">
          <span className="grid h-11 w-11 place-items-center rounded-xl border border-sky/40 bg-sky/10 text-sky"><FlaskConical size={20} /></span>
          <span className="text-lg font-extrabold">Try a test project</span>
          <span className="text-sm text-slate-400">Explore the whole workflow with simulated images and clips. No key needed and it costs nothing. You can set up a provider any time.</span>
          <span className="mt-auto text-xs font-bold uppercase tracking-wider text-sky">Free, nothing real is generated</span>
        </button>
      </div>
    </div>
  );
}
