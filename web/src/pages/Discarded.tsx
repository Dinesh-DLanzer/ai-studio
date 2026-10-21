import { useState } from "react";
import { FileText, Image as ImageIcon, Play, RotateCcw, Trash2, Video as VideoIcon } from "lucide-react";
import { api, fileUrl } from "../api";
import { Button, Modal, PageHeader, Select, money } from "../ui";
import { EmptyState } from "../components/kit";
import { fmtDate, type TabProps } from "../ProjectPage";
import { confirmDialog } from "../dialogs";

export function DiscardedTab({ o, name, load }: TabProps) {
  const [msg, setMsg] = useState("");
  const [kind, setKind] = useState<"all" | "clips" | "stills" | "other">("all");
  const [sort, setSort] = useState<"new" | "old" | "cost">("new");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [playing, setPlaying] = useState<string | null>(null);

  const restore = async (rel: string, replace = false) => {
    try {
      await api("POST", `/api/projects/${name}/restore`, { rel, ...(replace ? { replace: true } : {}) });
      setMsg("");
      load();
    } catch (e: any) {
      if (!replace && /already exists/.test(e.message) && await confirmDialog(`${e.message}\n\nThe file that is there now is moved to Discarded (nothing is deleted) and this version takes its place.`, { title: "Replace the current file?", ok: "Restore and replace" })) return restore(rel, true);
      setMsg(e.message);
    }
  };

  const restoreMany = async () => {
    for (const rel of picked) {
      try {
        await api("POST", `/api/projects/${name}/restore`, { rel });
      } catch (e: any) {
        setMsg(e.message);
      }
    }
    setPicked(new Set());
    load();
  };

  const kindOf = (d: typeof o.discarded[number]) => (d.file.startsWith("clips/") ? "clips" : d.file.startsWith("stills/") ? "stills" : "other");
  const shown = o.discarded
    .filter((d) => kind === "all" || kindOf(d) === kind)
    .sort((a, b) => (sort === "cost" ? b.cost - a.cost : sort === "old" ? String(a.when).localeCompare(String(b.when)) : String(b.when).localeCompare(String(a.when))));

  const toggle = (rel: string) =>
    setPicked((s) => {
      const n = new Set(s);
      n.has(rel) ? n.delete(rel) : n.add(rel);
      return n;
    });

  const reasonTag = (r: string) => {
    let h = 0;
    for (const c of r) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return ["tag-red", "tag-amber", "tag-violet", "tag-sky", "tag-emerald"][h % 5];
  };

  const tabs = [
    { id: "all", label: "All", icon: <Trash2 size={15} /> },
    { id: "clips", label: "Videos", icon: <VideoIcon size={15} /> },
    { id: "stills", label: "Images", icon: <ImageIcon size={15} /> },
    { id: "other", label: "Prompts & assets", icon: <FileText size={15} /> },
  ] as const;

  return (
    <div className="animate-fade-up">
      <PageHeader title="Discarded" sub="Items you removed or didn't use. You can restore them anytime." icon={<Trash2 size={24} />} art="/discarded-banner.png" />

      <div className="space-y-4">
        <div className="panel flex flex-wrap items-center gap-2 p-3">
          <div role="tablist" aria-label="Filter discarded files" className="flex flex-wrap gap-2">
            {tabs.map((t) => {
              const on = kind === t.id;
              const n = t.id === "all" ? o.discarded.length : o.discarded.filter((d) => kindOf(d) === t.id).length;
              return (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  aria-selected={on}
                  onClick={() => setKind(t.id)}
                  className={`pill !px-4 !py-2.5 ${on ? "!border-pink/70 !bg-pink/10 !text-white !bg-none shadow-glow-pink" : "!bg-slate-900"}`}
                >
                  {t.icon}
                  {t.label}
                  <span className={`rounded-lg px-1.5 text-[0.72rem] ${on ? "bg-pink/30" : "bg-white/10"}`}>{n}</span>
                </button>
              );
            })}
          </div>
          <span className="flex-1" />
          {picked.size > 0 && (
            <Button variant="outline" size="sm" onClick={restoreMany}>
              <RotateCcw size={13} />Restore {picked.size} selected
            </Button>
          )}
          <Select aria-label="Sort discarded files" className="!w-40 !py-2" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
            <option value="new">Newest first</option>
            <option value="old">Oldest first</option>
            <option value="cost">Highest cost</option>
          </Select>
        </div>

        {msg && (
          <p className="text-sm text-red-400" role="alert">
            {msg}
          </p>
        )}

        <div className="panel panel-lit overflow-hidden">
          {shown.map((d) => {
            const k = kindOf(d);
            const fileName = d.file.split("/").pop() || d.file;
            return (
              <div
                key={d.file}
                className="row-hover grid grid-cols-[auto_auto_minmax(0,1fr)] items-center gap-x-4 gap-y-2 border-b border-slate-800 px-4 py-3 last:border-0 lg:grid-cols-[auto_auto_minmax(0,1.3fr)_minmax(0,1fr)_9rem_auto]"
              >
                <input type="checkbox" aria-label={`Select ${fileName}`} checked={picked.has(d.file)} onChange={() => toggle(d.file)} className="h-4 w-4 accent-pink" />
                <div className="thumb h-[4.5rem] w-32 shrink-0">
                  {k === "stills" ? (
                    <img src={fileUrl(name, d.file)} alt="" loading="lazy" />
                  ) : k === "clips" ? (
                    <>
                      <video src={`${fileUrl(name, d.file)}#t=0.5`} preload="metadata" muted playsInline />
                      <button
                        type="button"
                        aria-label={`Play ${fileName}`}
                        onClick={() => setPlaying(d.file)}
                        className="absolute inset-0 grid place-items-center bg-black/20 transition hover:bg-black/40"
                      >
                        <span className="grid h-9 w-9 place-items-center rounded-full border border-white/40 bg-black/60 text-white">
                          <Play size={16} fill="currentColor" />
                        </span>
                      </button>
                    </>
                  ) : (
                    <div className="grid h-full place-items-center text-violet">
                      <FileText size={22} />
                    </div>
                  )}
                </div>
                <div className="min-w-0">
                  <div className="truncate text-sm font-bold">{d.original || fileName}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-slate-400">
                    {k === "clips" ? <VideoIcon size={13} /> : k === "stills" ? <ImageIcon size={13} /> : <FileText size={13} />}
                    <span>{k === "clips" ? "Video" : k === "stills" ? "Image" : "File"}</span>
                    <span aria-hidden>•</span>
                    <span>{money(d.cost)}</span>
                  </div>
                </div>
                <div className="col-span-3 min-w-0 lg:col-span-1">
                  <p className="mb-1 text-xs text-slate-400">Discarded reason</p>
                  <span className={`tag ${reasonTag(d.reason || "")} !max-w-full`}>{d.reason || "no reason given"}</span>
                </div>
                <div className="text-xs text-slate-400">{fmtDate(d.when)}</div>
                <Button variant="outline" size="sm" onClick={() => restore(d.file)}>
                  <RotateCcw size={13} />Restore
                </Button>
              </div>
            );
          })}
          {!shown.length && <EmptyState title="Nothing discarded" text="Replaced or unwanted files will appear here, with their reason and cost." icon={<RotateCcw size={20} />} />}
        </div>

        <Modal open={!!playing} onClose={() => setPlaying(null)} title={playing?.split("/").pop() || ""}>
          {playing && <video key={playing} src={fileUrl(name, playing)} controls autoPlay className="mx-auto max-h-[70vh] w-full rounded-lg bg-black" />}
        </Modal>

        <p className="text-[0.7rem] text-slate-400">
          Nothing is ever deleted: {money(o.discarded.reduce((n, d) => n + d.cost, 0))} of spend sits in {o.discarded.length} discarded files. Replaced or bad files keep their reason and cost and can be restored at any time.
        </p>
      </div>
    </div>
  );
}
