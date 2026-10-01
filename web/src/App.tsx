import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { HashRouter, Route, Routes, useParams } from "react-router-dom";
import { api, initToken, setToken } from "./api";
import { Button, Card, Input, Label } from "./ui";
import { Logo } from "./components/kit";
import { ToastProvider } from "./toast";
import Shell from "./app/Shell";
import ProjectLayout, { useProject } from "./app/ProjectLayout";
import Projects from "./pages/Projects";
import Chat from "./Chat";
import { AssetsTab } from "./pages/Assets";
import { ShotsTab } from "./pages/Shots";
import { CostsTab, DiscardedTab, StoryTab } from "./ProjectPage";
import { OverviewTab } from "./pages/Overview";
import ReviewExport from "./pages/ReviewExport";
import NotFound from "./pages/NotFound";
import Setup, { type SetupStatus } from "./app/Setup";
import Welcome from "./app/Welcome";
import { SetupContext } from "./app/setupContext";

// rarely opened pages load on demand, so the first screen downloads less
const Settings = lazy(() => import("./Settings"));
const Help = lazy(() => import("./pages/Help"));
const Kit = lazy(() => import("./pages/Kit"));

function TokenGate({ onOk }: { onOk: () => void }) {
  const [v, setV] = useState(""); const [err, setErr] = useState("");
  const submit = async () => { setToken(v); try { await api("GET", "/api/projects"); onOk(); } catch (e: any) { setErr(e.message); } };
  return (
    <div className="mx-auto mt-24 max-w-md p-4">
      <div className="mb-5 flex items-center gap-3"><Logo /></div>
      <Card title="Enter the session token" sub="It protects the page that can approve spending.">
        <p className="mb-4 text-sm text-slate-400">The token was printed in the terminal where you started the server.</p>
        <Label>Token</Label>
        <div className="flex gap-2">
          <Input className="flex-1" value={v} onChange={(e) => setV(e.target.value)} placeholder="token" onKeyDown={(e) => e.key === "Enter" && submit()} />
          <Button onClick={submit}>Open</Button>
        </div>
        {err && <p className="mt-2 text-sm text-red-400" role="alert">{err}</p>}
      </Card>
    </div>
  );
}

// the screens read the loaded project from the layout (useProject) and are mounted in the new shell
const Overview = () => <OverviewTab {...useProject()} />;
const Storyboard = () => <StoryTab {...useProject()} />;
const Assets = () => <AssetsTab {...useProject()} />;
const Shots = () => <ShotsTab {...useProject()} />;
const Costs = () => <CostsTab {...useProject()} />;
const Discarded = () => <DiscardedTab {...useProject()} />;
function ChatPage() { const { name, load, openBudget, start, o, running } = useProject(); return <Chat project={name} reloadAll={load} onApplied={openBudget} openBudget={openBudget} start={start} running={running} refreshKey={o} />; }
function ProjectNotFound() { const { name } = useProject(); return <NotFound name={name} />; }
function ProjectRoute() { const { name = "" } = useParams(); return <ProjectLayout key={name} name={name} />; }
const Plain = ({ children }: { children: React.ReactNode }) => <Shell><Suspense fallback={<p className="p-6 text-slate-400">Loading...</p>}>{children}</Suspense></Shell>;

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  // how this browser chose to start while no provider exists: "setup" (connect a provider) or "trial" (test mode)
  const [start, setStartState] = useState<"setup" | "trial" | null>(() => { try { const v = localStorage.getItem("aistudio-start"); return v === "setup" || v === "trial" ? v : null; } catch { return null; } });
  const setStart = useCallback((v: "setup" | "trial" | null) => { setStartState(v); try { v ? localStorage.setItem("aistudio-start", v) : localStorage.removeItem("aistudio-start"); } catch { /* private window */ } }, []);
  const refreshSetup = useCallback(async () => { try { setSetup(await api<SetupStatus>("GET", "/api/setup")); } catch { /* an old server without /api/setup: do not block */ setSetup((s) => s ?? ({ needed: false } as SetupStatus)); } }, []);
  useEffect(() => { initToken(); api("GET", "/api/projects").then(() => setAuthed(true)).catch(() => setAuthed(false)); }, []);
  useEffect(() => { if (authed) refreshSetup().then(() => undefined); }, [authed, refreshSetup]);
  // a provider arrived while in trial mode: the trial banner is no longer needed
  useEffect(() => { if (setup && !setup.needed && start === "trial") setStart(null); }, [setup, start, setStart]);
  if (authed === null) return null;
  if (!authed) return <ToastProvider><TokenGate onOk={() => setAuthed(true)} /></ToastProvider>;
  if (setup === null) return null;
  if (setup.needed && !start) return <ToastProvider><Welcome onSetup={() => setStart("setup")} onTrial={() => setStart("trial")} /></ToastProvider>;
  if (start === "setup") return <ToastProvider><Setup status={setup} refresh={refreshSetup} onContinue={() => setStart(null)} onBack={setup.needed ? () => setStart(null) : undefined} /></ToastProvider>;
  const trial = setup.needed && start === "trial";
  return (
    <ToastProvider>
      <SetupContext.Provider value={{ needed: !!setup.needed }}>
      {trial && (
        <div role="status" data-testid="trial-banner" className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-sky/30 bg-sky/10 px-3 py-1.5 text-center text-xs text-sky">
          <span><b>No provider connected.</b> New projects are test projects: simulated, free, nothing is charged.</span>
          <button type="button" className="font-bold underline underline-offset-2 hover:text-white" onClick={() => setStart("setup")}>Set up a provider</button>
        </div>
      )}
      <HashRouter>
        <Routes>
          <Route path="/" element={<Plain><Projects /></Plain>} />
          <Route path="/settings" element={<Plain><Settings /></Plain>} />
          <Route path="/help" element={<Plain><Help /></Plain>} />
          <Route path="/kit" element={<Plain><Kit /></Plain>} />
          <Route path="/p/:name" element={<ProjectRoute />}>
            <Route index element={<Overview />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="storyboard" element={<Storyboard />} />
            <Route path="assets" element={<Assets />} />
            <Route path="shots" element={<Shots />} />
            <Route path="review" element={<ReviewExport />} />
            <Route path="costs" element={<Costs />} />
            <Route path="discarded" element={<Discarded />} />
            <Route path="*" element={<ProjectNotFound />} />
          </Route>
          <Route path="*" element={<Plain><NotFound /></Plain>} />
        </Routes>
      </HashRouter>
      </SetupContext.Provider>
    </ToastProvider>
  );
}
