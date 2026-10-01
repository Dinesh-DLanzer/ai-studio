import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import * as Menu from "@radix-ui/react-dropdown-menu";
import {
  ArrowLeft, Download, FolderArchive, Film, Image as ImageIcon, LayoutTemplate, Maximize, Music, Pause, Play, Redo2, Shapes, Sparkles, Subtitles, Trash2, Type, Undo2, Volume2, VolumeX, MoreHorizontal, Wand2, X, ChevronDown, FolderOpen, Layers, Droplets,
} from "lucide-react";
import { api, fileUrl, uploadAudio } from "../api";
import { useProject } from "../app/ProjectLayout";
import { useToast } from "../toast";
import { deleteProject, downloadProjectZip } from "../projectActions";
import { useEdit } from "../editor/useEdit";
import Preview from "../editor/Preview";
import Timeline from "../editor/Timeline";
import Inspector from "../editor/Inspector";
import type { Aspect, Edit, FontInfo, Sel, TText, Tool } from "../editor/types";
import { clamp, editEnd, layout, mmss, nid, round2 } from "../editor/time";
import { duration, knownDuration } from "../editor/media";
import "../editor/editor.css";

const TOOLS: { id: Tool; label: string; icon: typeof Film }[] = [
  { id: "media", label: "Media", icon: ImageIcon }, { id: "text", label: "Text", icon: Type }, { id: "elements", label: "Elements", icon: Shapes },
  { id: "audio", label: "Audio", icon: Music }, { id: "transitions", label: "Transitions", icon: Layers }, { id: "filters", label: "Filters", icon: Droplets },
  { id: "effects", label: "Effects", icon: Sparkles }, { id: "subtitles", label: "Subtitles", icon: Subtitles }, { id: "aspect", label: "Aspect Ratio", icon: LayoutTemplate },
  { id: "background", label: "Background", icon: Wand2 },
];

function ExportDialog({ project, open, onClose, edit, flush, ffmpeg }: { project: string; open: boolean; onClose: () => void; edit: Edit; flush: () => Promise<void>; ffmpeg: boolean }) {
  const [state, setState] = useState<"idle" | "running" | "done" | "error">("idle"); const [pct, setPct] = useState(0); const [msg, setMsg] = useState(""); const [file, setFile] = useState("");
  const alive = useRef(true); useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const start = async () => {
    setState("running"); setPct(0); setMsg(""); setFile("");
    try {
      await flush();
      const { job } = await api<{ job: string }>("POST", `/api/projects/${project}/edit/export`);
      for (;;) {
        await new Promise((r) => setTimeout(r, 400)); if (!alive.current) return;
        const j = await api<any>("GET", `/api/jobs/${job}`);
        if (j.status === "running") setPct(j.progress || 0);
        else if (j.status === "done") { setPct(100); setFile(j.result.file); setState("done"); return; }
        else { setMsg(j.error || "The export failed"); setState("error"); return; }
      }
    } catch (e: any) { setMsg(e.message); setState("error"); }
  };
  useEffect(() => { if (open) { setState("idle"); setMsg(""); } }, [open]);
  const clips = edit.tracks.video.length;
  return (
    <Dialog.Root open={open} onOpenChange={(o) => { if (!o && state !== "running") onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim" />
        <Dialog.Content aria-describedby={undefined} className="re-dialog">
          <div className="flex items-start justify-between gap-3">
            <Dialog.Title className="text-lg font-bold">Export video</Dialog.Title>
            <Dialog.Close className="icon-btn" aria-label="Close" disabled={state === "running"}><X size={16} /></Dialog.Close>
          </div>
          {state === "idle" && (
            <>
              <p className="mt-2 text-sm text-slate-300">{clips} clip{clips === 1 ? "" : "s"}, {edit.tracks.text.length} text, {edit.tracks.audio.length} sound{edit.tracks.audio.length === 1 ? "" : "s"}, {edit.aspect}, about {mmss(layout(edit.tracks.video).total)}.</p>
              <p className="mt-1 text-xs text-slate-400">The video is made on this computer with ffmpeg and saved in the project's exports folder. It is free: no AI model is used.</p>
              {!ffmpeg && <p role="alert" className="mt-3 rounded-xl border border-red-400/40 bg-red-400/10 p-3 text-sm text-red-200">ffmpeg is not installed. Install it (macOS: brew install ffmpeg), then restart AI Studio.</p>}
              <div className="mt-5 flex justify-end gap-2"><button type="button" className="btn btn-outline" onClick={onClose}>Cancel</button>
                <button type="button" className="btn btn-grad" disabled={!ffmpeg || !clips} onClick={start}><Download size={15} />Start export</button></div>
            </>
          )}
          {state === "running" && (
            <div className="mt-4"><div className="re-progress" role="progressbar" aria-label="Export progress" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${pct}%` }} /></div>
              <p className="mt-2 text-sm text-slate-300" aria-live="polite">Making your video... {Math.round(pct)}%</p></div>
          )}
          {state === "error" && (
            <>
              <p role="alert" className="mt-3 rounded-xl border border-red-400/40 bg-red-400/10 p-3 text-sm text-red-200">{msg}</p>
              <div className="mt-5 flex justify-end gap-2"><button type="button" className="btn btn-outline" onClick={onClose}>Close</button><button type="button" className="btn btn-grad" onClick={start}>Try again</button></div>
            </>
          )}
          {state === "done" && (
            <>
              <video data-testid="export-result" className="mt-3 max-h-[46vh] w-full rounded-xl bg-black" controls src={fileUrl(project, file)} />
              <p className="mt-2 break-all text-xs text-slate-400">Saved as {file}</p>
              <div className="mt-4 flex justify-end gap-2"><button type="button" className="btn btn-outline" onClick={onClose}>Done</button>
                <a className="btn btn-grad" href={fileUrl(project, file)} download={file.split("/").pop()}><Download size={15} />Download</a></div>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default function ReviewExport() {
  const { name, o } = useProject(); const nav = useNavigate(); const toast = useToast();
  const { data, edit, set, undo, redo, canUndo, canRedo, save, saveErr, flush } = useEdit(name);
  const [t, setT] = useState(0); const [playing, setPlaying] = useState(false); const [muted, setMuted] = useState(false);
  const [sel, setSel] = useState<Sel>(null); const [tool, setTool] = useState<Tool>("media"); const [fonts, setFonts] = useState<FontInfo[]>([]);
  const [fit, setFit] = useState<"fit" | "fill">("fit"); const [exportOpen, setExportOpen] = useState(false); const [uploading, setUploading] = useState(false); const [tick, bump] = useState(0);
  const stage = useRef<HTMLDivElement>(null);

  useEffect(() => { fetch("/api/fonts").then((r) => r.json()).then((j) => setFonts(j.fonts)).catch(() => {}); }, []);
  const fontCss = useMemo(() => fonts.flatMap((f) => [
    ...f.weights.map((w) => `@font-face{font-family:"${f.family}";font-weight:${w.weight};font-style:normal;src:url(/api/fonts/${w.file});font-display:swap}`),
    ...f.italic.map((w) => `@font-face{font-family:"${f.family}";font-weight:${w.weight};font-style:italic;src:url(/api/fonts/${w.file});font-display:swap}`),
  ]).join("\n"), [fonts]);

  const total = edit ? layout(edit.tracks.video).total : 0;
  const end = edit ? editEnd(edit) : 0;

  // playback clock: the playhead advances in real time; the video and sound elements follow it
  useEffect(() => {
    if (!playing) return; let last = performance.now(); let id = 0;
    const tick = (now: number) => { const dt = (now - last) / 1000; last = now; setT((p) => { const n = p + dt; if (n >= total) { setPlaying(false); return total; } return n; }); id = requestAnimationFrame(tick); };
    id = requestAnimationFrame(tick); return () => cancelAnimationFrame(id);
  }, [playing, total]);
  const togglePlay = useCallback(() => { if (!total) return; if (!playing && t >= total - 0.05) setT(0); setPlaying((p) => !p); }, [playing, t, total]);
  const seek = useCallback((x: number) => setT(clamp(x, 0, Math.max(total, end))), [total, end]);

  // remember source lengths so trim handles cannot go past the end of a file
  useEffect(() => { if (!edit) return; [...edit.tracks.video, ...edit.tracks.audio].forEach((c) => { const u = fileUrl(name, c.src); if (knownDuration(u) === undefined) duration(u, "src" in c && c.src.startsWith("audio/") ? "audio" : "video").then(() => bump((n) => n + 1)).catch(() => {}); }); }, [edit, name]);
  const durs = useMemo(() => { const m: Record<string, number> = {}; if (edit) [...edit.tracks.video, ...edit.tracks.audio].forEach((c) => { const u = fileUrl(name, c.src); const d = knownDuration(u); if (d) m[u] = d; }); return m; }, [edit, name, tick]);

  const patch = useCallback((kind: "video" | "text" | "audio", id: string, p: any, key = "") =>
    set((e) => ({ ...e, tracks: { ...e.tracks, [kind]: (e.tracks[kind] as any[]).map((x) => (x.id === id ? { ...x, ...p } : x)) } as Edit["tracks"] }), key || `p${kind}${id}${Object.keys(p).join()}`), [set]);

  const remove = useCallback((s: NonNullable<Sel>) => { set((e) => ({ ...e, tracks: { ...e.tracks, [s.kind]: (e.tracks[s.kind] as any[]).filter((x) => x.id !== s.id) } as Edit["tracks"] })); setSel(null); }, [set]);

  const addClip = useCallback(async (file: string) => {
    try {
      const d = await duration(fileUrl(name, `clips/${file}`)); const id = nid("v");
      set((e) => ({ ...e, tracks: { ...e.tracks, video: [...e.tracks.video, { id, src: `clips/${file}`, in: 0, out: round2(Math.max(0.3, d)), volume: 1, transition: { type: "cut", dur: 0.5 } }] } }));
      setSel({ kind: "video", id });
    } catch { toast("error", `Cannot read ${file}`); }
  }, [name, set, toast]);

  const addText = useCallback((preset: "title" | "subtitle" | "caption") => {
    const id = nid("t"); const base = { id, start: round2(t), end: round2(t + 3), font: "Poppins", italic: false, underline: false, caps: false, opacity: 1, align: "center" as const };
    const v: Record<string, Partial<TText>> = {
      title: { text: "Your title", x: 0.5, y: 0.3, size: 72, weight: 800, bold: true, color: "#ffffff", bg: null, shadow: { on: true, color: "#000000", blur: 20 } },
      subtitle: { text: "Your subtitle", x: 0.5, y: 0.8, size: 44, weight: 600, bold: true, color: "#ffffff", bg: null, shadow: { on: true, color: "#000000", blur: 20 } },
      caption: { text: "Turn Ideas into\nStunning Videos", x: 0.5, y: 0.62, size: 56, weight: 700, bold: true, color: "#ffffff", bg: "#a855f7", shadow: { on: false, color: "#000000", blur: 20 } },
    };
    set((e) => ({ ...e, tracks: { ...e.tracks, text: [...e.tracks.text, { ...base, ...v[preset] } as TText] } })); setSel({ kind: "text", id });
  }, [set, t]);

  const onUploadAudio = useCallback(async (f: File) => {
    setUploading(true);
    try {
      const r = await uploadAudio(name, f); const id = nid("a"); const d = r.duration || (await duration(fileUrl(name, r.src), "audio").catch(() => 30));
      set((e) => ({ ...e, tracks: { ...e.tracks, audio: [...e.tracks.audio, { id, src: r.src, name: r.name, start: round2(t), in: 0, out: round2(Math.max(0.3, d)), volume: 0.6, fadeIn: 0, fadeOut: 0 }] } })); setSel({ kind: "audio", id });
    } catch (e: any) { toast("error", e.message); } finally { setUploading(false); }
  }, [name, set, t, toast]);

  const split = useCallback(() => {
    if (!edit) return; const MIN = 0.15; let s = sel;
    if (!s) { const pl = layout(edit.tracks.video).placed.find((p) => t > p.start + MIN && t < p.end - MIN); if (pl) s = { kind: "video", id: pl.clip.id }; }
    if (!s) { toast("info", "Move the playhead inside a clip, or select one, then split."); return; }
    if (s.kind === "video") {
      const { placed } = layout(edit.tracks.video); const i = placed.findIndex((p) => p.clip.id === s!.id); const p = placed[i];
      if (!p || t <= p.start + MIN || t >= p.end - MIN) { toast("info", "Put the playhead inside the selected clip to split it."); return; }
      const cut = round2(p.clip.in + (t - p.start)); const nidv = nid("v");
      set((e) => { const v = [...e.tracks.video]; v.splice(i, 1, { ...p.clip, out: cut }, { ...p.clip, id: nidv, in: cut, transition: { type: "cut", dur: 0.5 } }); return { ...e, tracks: { ...e.tracks, video: v } }; }); setSel({ kind: "video", id: nidv });
    } else if (s.kind === "text") {
      const x = edit.tracks.text.find((z) => z.id === s!.id); if (!x || t <= x.start + MIN || t >= x.end - MIN) { toast("info", "Put the playhead inside the text bar to split it."); return; }
      const idn = nid("t"); set((e) => ({ ...e, tracks: { ...e.tracks, text: e.tracks.text.flatMap((z) => (z.id === x.id ? [{ ...z, end: round2(t) }, { ...z, id: idn, start: round2(t) }] : [z])) } })); setSel({ kind: "text", id: idn });
    } else {
      const x = edit.tracks.audio.find((z) => z.id === s!.id); const len = x ? x.out - x.in : 0; if (!x || t <= x.start + MIN || t >= x.start + len - MIN) { toast("info", "Put the playhead inside the sound bar to split it."); return; }
      const cut = round2(x.in + (t - x.start)); const ida = nid("a");
      set((e) => ({ ...e, tracks: { ...e.tracks, audio: e.tracks.audio.flatMap((z) => (z.id === x.id ? [{ ...z, out: cut }, { ...z, id: ida, in: cut, start: round2(t) }] : [z])) } })); setSel({ kind: "audio", id: ida });
    }
  }, [edit, sel, set, t, toast]);

  const duplicate = useCallback(() => {
    if (!edit || !sel) return;
    if (sel.kind === "video") { const i = edit.tracks.video.findIndex((x) => x.id === sel.id); if (i < 0) return; const id = nid("v"); set((e) => { const v = [...e.tracks.video]; v.splice(i + 1, 0, { ...v[i], id, transition: { type: "cut", dur: 0.5 } }); return { ...e, tracks: { ...e.tracks, video: v } }; }); setSel({ kind: "video", id }); }
    else if (sel.kind === "text") { const x = edit.tracks.text.find((z) => z.id === sel.id); if (!x) return; const id = nid("t"); const len = x.end - x.start; set((e) => ({ ...e, tracks: { ...e.tracks, text: [...e.tracks.text, { ...x, id, start: x.end, end: round2(x.end + len) }] } })); setSel({ kind: "text", id }); }
    else { const x = edit.tracks.audio.find((z) => z.id === sel.id); if (!x) return; const id = nid("a"); set((e) => ({ ...e, tracks: { ...e.tracks, audio: [...e.tracks.audio, { ...x, id, start: round2(x.start + x.out - x.in) }] } })); setSel({ kind: "audio", id }); }
  }, [edit, sel, set]);

  const setAspect = useCallback((a: Aspect) => set((e) => ({ ...e, aspect: a })), [set]);

  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement; if (el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable)) return;
      if (document.querySelector('[role="dialog"]')) return;
      const k = e.key; const mod = e.metaKey || e.ctrlKey;
      if (mod && k.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); }
      else if (mod && k.toLowerCase() === "y") { e.preventDefault(); redo(); }
      else if (mod) return;
      else if (k === " ") { e.preventDefault(); togglePlay(); }
      else if (k.toLowerCase() === "s") { e.preventDefault(); split(); }
      else if ((k === "Delete" || k === "Backspace") && sel) { e.preventDefault(); remove(sel); }
      else if (k === "ArrowLeft") { e.preventDefault(); seek(t - (e.shiftKey ? 1 : 0.1)); }
      else if (k === "ArrowRight") { e.preventDefault(); seek(t + (e.shiftKey ? 1 : 0.1)); }
    };
    addEventListener("keydown", f); return () => removeEventListener("keydown", f);
  }, [redo, undo, togglePlay, split, remove, sel, seek, t]);

  const doDelete = async () => {
    try { if (await deleteProject(name)) { toast("ok", `${name} moved to the trash. You can restore it from the Projects page.`); nav("/"); } }
    catch (e: any) { toast("error", e.message); }
  };

  if (!edit || !data) return <div className="re-loading" role="status">Loading the editor...</div>;
  const clipFiles = o.files.clips;
  const missing = data.missing.length ? data.missing : [];
  return (
    <div className="re-page" data-testid="review-export">
      <style>{fontCss}</style>
      <header className="re-head">
        <button type="button" className="re-back" aria-label="Back to overview" onClick={() => nav(`/p/${name}`)}><ArrowLeft size={22} /></button>
        <div className="min-w-0">
          <h2 className="re-title">Review &amp; Export</h2>
          <p className="re-subtitle">Edit your short video and export or save the project</p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <span className={`re-save ${save === "error" ? "is-err" : ""}`} role="status" aria-live="polite" data-testid="save-state">{save === "saving" ? "Saving..." : save === "saved" ? "Saved" : save === "error" ? `Not saved: ${saveErr}` : ""}</span>
          <button type="button" className="re-tb" aria-label="Undo" title="Undo (Ctrl/Cmd+Z)" disabled={!canUndo} onClick={undo}><Undo2 size={19} /></button>
          <button type="button" className="re-tb" aria-label="Redo" title="Redo (Ctrl/Cmd+Shift+Z)" disabled={!canRedo} onClick={redo}><Redo2 size={19} /></button>
          <Menu.Root>
            <Menu.Trigger className="re-tb" aria-label="More actions"><MoreHorizontal size={20} /></Menu.Trigger>
            <Menu.Portal>
              <Menu.Content align="end" sideOffset={6} className="menu-surface">
                <Menu.Item className="menu-item" onSelect={() => downloadProjectZip(name)}><FolderArchive size={14} />Export project (zip)</Menu.Item>
                <Menu.Item className="menu-item" onSelect={() => downloadProjectZip(name, true)}><FolderArchive size={14} />Export project with discarded files</Menu.Item>
                <Menu.Item className="menu-item" onSelect={() => nav(`/p/${name}/shots`)}><Film size={14} />Open Shots</Menu.Item>
                <Menu.Separator className="my-1 h-px bg-slate-800" />
                <Menu.Item className="menu-item !text-red-300" onSelect={() => setTimeout(doDelete, 0)}><Trash2 size={14} />Delete project...</Menu.Item>
              </Menu.Content>
            </Menu.Portal>
          </Menu.Root>
          <button type="button" className="re-btn-outline" onClick={() => { downloadProjectZip(name); toast("info", "Preparing the project zip. Your browser will download it."); }}><FolderOpen size={17} />Export Project</button>
          <button type="button" className="re-btn-grad" onClick={() => setExportOpen(true)}><Download size={17} />Export Video</button>
        </div>
      </header>

      {(missing.length > 0 || data.warning || !data.tools.ffmpeg) && (
        <div className="re-warn" role="alert">
          {missing.length > 0 && <div>These files are missing, so the export will fail until you remove them or restore the files: {missing.join(", ")}.</div>}
          {data.warning && <div>{data.warning}</div>}
          {!data.tools.ffmpeg && <div>ffmpeg is not installed, so Export Video is off. Install it (macOS: brew install ffmpeg) and restart.</div>}
        </div>
      )}

      <div className="re-main">
        <nav className="re-rail re-card" aria-label="Editor tools">
          {TOOLS.map((x) => { const I = x.icon; return (
            <button key={x.id} type="button" className={`re-rail-btn ${tool === x.id ? "is-on" : ""}`} aria-pressed={tool === x.id} onClick={() => { setTool(x.id); setSel(null); }}><I size={20} /><span>{x.label}</span></button>
          ); })}
        </nav>

        <section className="re-card re-player" aria-label="Preview">
          <div ref={stage} className={`re-stagebox ${fit === "fill" ? "is-fill" : ""}`}>
            <Preview project={name} edit={edit} t={t} playing={playing} muted={muted} sel={sel} setSel={setSel} fit={fit}
              onText={(id, p, key) => patch("text", id, p, key)} />
          </div>
          <div className="re-transport">
            <button type="button" className="re-play" aria-label={playing ? "Pause" : "Play"} onClick={togglePlay} disabled={!total}>{playing ? <Pause size={22} fill="currentColor" /> : <Play size={22} fill="currentColor" />}</button>
            <span className="re-time" data-testid="time"><b>{mmss(t)}</b> / {mmss(total)}</span>
            <input type="range" className="re-range re-seek" aria-label="Seek" min={0} max={Math.max(total, 0.1)} step={0.05} value={Math.min(t, Math.max(total, 0.1))} style={{ ["--p" as any]: `${total ? (t / total) * 100 : 0}%` }}
              onChange={(e) => seek(parseFloat(e.target.value))} />
            <button type="button" className="re-tb" aria-label={muted ? "Unmute" : "Mute"} aria-pressed={muted} onClick={() => setMuted((m) => !m)}>{muted ? <VolumeX size={20} /> : <Volume2 size={20} />}</button>
            <div className="re-selwrap w-24"><select aria-label="Preview size" className="re-select" value={fit} onChange={(e) => setFit(e.target.value as any)}><option value="fit">Fit</option><option value="fill">Fill</option></select><ChevronDown size={15} /></div>
            <button type="button" className="re-tb" aria-label="Full screen" onClick={() => stage.current?.requestFullscreen?.().catch(() => {})}><Maximize size={19} /></button>
          </div>
        </section>

        <Inspector project={name} edit={edit} sel={sel} tool={tool} fonts={fonts} clips={clipFiles} durs={durs} patch={patch} remove={remove}
          addClip={addClip} addText={addText} uploadAudio={onUploadAudio} setAspect={setAspect} uploading={uploading} />
      </div>

      <Timeline project={name} edit={edit} set={set} t={t} setT={seek} sel={sel} setSel={setSel} undo={undo} redo={redo} canUndo={canUndo} canRedo={canRedo}
        split={split} remove={() => sel && remove(sel)} duplicate={duplicate} playing={playing} />

      <ExportDialog project={name} open={exportOpen} onClose={() => setExportOpen(false)} edit={edit} flush={flush} ffmpeg={data.tools.ffmpeg} />
    </div>
  );
}
