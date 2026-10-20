import { useEffect, useState } from "react";
import { CheckCircle2, ExternalLink, Loader2, Terminal } from "lucide-react";
import { Button } from "../ui";
import { useToast } from "../toast";
import { alertDialog } from "../dialogs";
import { settingsApi } from "./client";
import type { ChatGPTStatus, Provider } from "./types";

/** Two ways to connect a ChatGPT Plus/Pro plan: reuse the Codex CLI session, or sign in through the browser. */
export function ChatGPTConnect({ onConnected, onBack }: { onConnected: (p: Provider) => void; onBack?: () => void }) {
  const toast = useToast();
  const [st, setSt] = useState<ChatGPTStatus | null>(null);
  const [busy, setBusy] = useState<"codex" | "browser" | null>(null);
  useEffect(() => { settingsApi.chatgptStatus().then(setSt).catch(() => setSt(null)); }, []);

  const finish = async (p: Provider) => {
    let final = p;
    try {
      const t = await settingsApi.testProvider(p.id);
      final = t.provider;
      toast(t.result.ok ? "ok" : "error", t.result.ok ? `${p.label}: ${t.result.message}` : `${p.label} was added, but the test failed: ${t.result.message}`);
    } catch (e) { toast("error", `${p.label} was added, but the test failed: ${(e as Error).message}`); }
    onConnected(final);
  };
  const importCodex = async () => {
    setBusy("codex");
    try { await finish(await settingsApi.chatgptImportCodex()); } catch (e) { toast("error", (e as Error).message); } finally { setBusy(null); }
  };
  const browser = async () => {
    setBusy("browser");
    try {
      const check = await settingsApi.chatgptCheckPort();
      if (!check.free) {
        setBusy(null);
        await alertDialog(
          "Port 1455 is currently occupied by another program (such as 'codex login' running in a terminal, or another background service).\n\nPlease close the process using port 1455 or run 'killall codex' in your terminal, then try again.",
          { title: "Port 1455 is in use", ok: "Got it", danger: true }
        );
        return;
      }

      const { url } = await settingsApi.chatgptAuthorize();
      window.open(url, "_blank", "noopener");
      toast("ok", "Finish signing in on the ChatGPT tab, then come back here.");
      for (let i = 0; i < 90; i++) {                     // the callback tab saves the session; poll until it shows up
        await new Promise((r) => setTimeout(r, 2000));
        const s = await settingsApi.chatgptStatus();
        if (s.connected && s.signed_in && s.provider_id) {
          const list = await settingsApi.providers();
          const p = list.providers.find((x) => x.id === s.provider_id);
          if (p) { await finish(p); return; }
        }
      }
      toast("error", "Sign-in was not completed. Try again.");
    } catch (e) {
      const msg = (e as Error).message || "Sign-in failed";
      if (msg.toLowerCase().includes("port 1455") || msg.toLowerCase().includes("1455")) {
        await alertDialog(
          "Port 1455 is currently occupied by another program (such as 'codex login' running in a terminal, or another background service).\n\nPlease close the process using port 1455 or run 'killall codex' in your terminal, then try again.",
          { title: "Port 1455 is in use", ok: "Got it", danger: true }
        );
      } else {
        toast("error", msg);
      }
    } finally { setBusy(null); }
  };

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">Use your ChatGPT Plus or Pro plan for chat, vision, verify and image generation. No API credits needed; video stays with your video provider.</p>
      <div className="panel-quiet rounded-xl p-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-100"><Terminal size={15} />Import from Codex CLI
          {st?.codex_detected && <span className="tag tag-emerald inline-flex items-center gap-1"><CheckCircle2 size={12} />Detected</span>}</div>
        <p className="mt-1 text-xs text-slate-400">{st?.codex_detected ? "Found a signed-in Codex session on this computer." : "Not found. Run `codex login` in a terminal, then reopen this."}</p>
        <Button variant="pink" className="mt-2" onClick={importCodex} disabled={!st?.codex_detected || busy !== null}>{busy === "codex" && <Loader2 size={14} className="animate-spin" />}Import session</Button>
      </div>
      <div className="panel-quiet rounded-xl p-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-100"><ExternalLink size={15} />Sign in with ChatGPT</div>
        <p className="mt-1 text-xs text-slate-400">Opens ChatGPT in a new tab. Needs port 1455 free (close `codex login` if it is running).</p>
        <Button variant="outline" className="mt-2" onClick={browser} disabled={busy !== null}>{busy === "browser" && <Loader2 size={14} className="animate-spin" />}Sign in with ChatGPT</Button>
      </div>
      {onBack && <div className="flex justify-end pt-1"><Button variant="outline" onClick={onBack} disabled={busy !== null}>Back</Button></div>}
    </div>
  );
}
