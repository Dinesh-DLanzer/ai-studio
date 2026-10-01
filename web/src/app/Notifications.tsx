import { useNavigate } from "react-router-dom";
import * as Menu from "@radix-ui/react-dropdown-menu";
import { Bell, CheckCircle2, Trash2, XCircle } from "lucide-react";
import { Spinner } from "../Proposal";
import { clearNotices, markAllRead, removeNotice, useNotices } from "../notify";

const ago = (ts: number) => {
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
  return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)} min ago` : s < 86400 ? `${Math.floor(s / 3600)} h ago` : new Date(ts).toLocaleDateString();
};

/** The bell: spinner while an AI process runs, a count of unread results, and the list of recent processes. */
export default function Notifications() {
  const nav = useNavigate(); const list = useNotices();
  const running = list.filter((n) => n.status === "running").length; const unread = list.filter((n) => n.status !== "running" && !n.read).length;
  return (
    <Menu.Root onOpenChange={(o) => { if (!o) markAllRead(); }}>
      <Menu.Trigger className="icon-btn relative hidden sm:grid" aria-label={`Notifications${running ? `, ${running} running` : unread ? `, ${unread} new` : ""}`}>
        {running ? <Spinner size={17} /> : <Bell size={17} />}
        {unread > 0 && !running && <span className="absolute -right-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full bg-pink px-1 text-[0.6rem] font-bold text-white">{unread > 9 ? "9+" : unread}</span>}
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content align="end" sideOffset={8} className="menu-surface !w-[min(380px,92vw)] !p-0">
          <div className="flex items-center justify-between gap-2 border-b border-slate-800 px-3.5 py-2.5">
            <span className="text-sm font-bold">Notifications</span>
            {list.some((n) => n.status !== "running") && <button type="button" className="text-xs text-slate-400 hover:text-white" onClick={clearNotices}>Clear all</button>}
          </div>
          <ul className="max-h-[22rem] overflow-y-auto">
            {list.length === 0 && <li className="px-4 py-8 text-center text-sm text-slate-400">Nothing yet. AI processes (chat, images, clips, reviews) show up here while they run and when they finish.</li>}
            {list.map((n) => (
              <li key={n.id} className="group flex items-start gap-2.5 border-b border-slate-800/60 px-3.5 py-2.5 last:border-0">
                <span className="mt-0.5 shrink-0">
                  {n.status === "running" ? <span className="text-sky-300"><Spinner size={16} /></span> : n.status === "ok" ? <CheckCircle2 size={16} className="text-emerald-400" /> : <XCircle size={16} className="text-red-400" />}
                </span>
                <Menu.Item className="min-w-0 flex-1 cursor-pointer outline-none" onSelect={() => n.to && nav(n.to)}>
                  <span className="block truncate text-sm font-semibold">{n.title}</span>
                  <span className={`mt-0.5 block text-xs leading-snug ${n.status === "error" ? "text-red-300" : "text-slate-400"}`}>{n.text}</span>
                  <span className="mt-1 block text-[0.65rem] text-slate-500">{n.status === "running" ? "running…" : ago(n.ts)}{n.project ? ` · ${n.project}` : ""}</span>
                </Menu.Item>
                {n.status !== "running" && <button type="button" aria-label="Dismiss notification" className="shrink-0 text-slate-500 opacity-0 transition hover:text-white focus:opacity-100 group-hover:opacity-100" onClick={() => removeNotice(n.id)}><Trash2 size={13} /></button>}
              </li>
            ))}
          </ul>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}
