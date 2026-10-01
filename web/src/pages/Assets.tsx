import { useEffect, useRef, useState } from "react";
import * as Menu from "@radix-ui/react-dropdown-menu";
import {
  Crown, Image as ImageIcon, LayoutGrid, Maximize2, MoreHorizontal, Pencil, Plus, Sparkles, Trash2, Upload as UploadIcon, Users, X,
  ChevronLeft, ChevronRight, Wand2, Eye,
} from "lucide-react";
import { api, fileUrl, upload } from "../api";
import { Badge, Button, Field, Input } from "../ui";
import { Spinner, runKey } from "../Proposal";
import { useToast } from "../toast";
import { confirmDialog, promptDialog } from "../dialogs";
import { RenameButton } from "../Rename";
import { VerifyBar } from "../Verify";
import { PageBody } from "../app/Shell";
import { EmptyState, PageBanner, RailCard } from "../components/kit";
import { ID_OK, ImportStills, KINDS, ReviewBadge, stem, type TabProps } from "../ProjectPage";
import type { FoundStill, ImageSpec } from "../types";

type Kind = ImageSpec["kind"];
const KIND_ICON: Record<Kind, JSX.Element> = { character: <Users size={17} />, background: <ImageIcon size={17} />, frame: <LayoutGrid size={17} />, other: <UploadIcon size={17} /> };

const norm = (t: string) => t.toLowerCase().replace(/[^a-z0-9]/g, "");

/** Find the part of Story.md that describes this asset: a "###" heading named like the asset (character, place) or "Scene NN" for a scene frame (s01). */
export function storyDescription(story: string, i: ImageSpec): string {
  const lines = story.split("\n"); const key = norm(i.id.replace(/_(sheet|master|ref)$/, ""));
  const num = i.id.match(/^s(\d+)/i)?.[1];
  for (let k = 0; k < lines.length; k++) {
    const h = lines[k].match(/^#{2,4}\s+(.+?)\s*$/); if (!h) continue;
    const t = norm(h[1]); const isScene = /^(scene|shot)0*(\d+)/.test(t);
    const hit = num && isScene ? Number(t.match(/^(?:scene|shot)0*(\d+)/)![1]) === Number(num) : !!key && !isScene && (t === key || key.startsWith(t) || t.startsWith(key));
    if (!hit) continue;
    const body: string[] = [];
    for (let j = k + 1; j < lines.length && !/^#{1,4}\s/.test(lines[j]) && lines[j].trim() !== "---"; j++) if (lines[j].trim()) body.push(lines[j].trim().replace(/^[-*]\s*/, "").replace(/\*\*/g, ""));
    if (body.length) return body.join("\n");
  }
  return "";
}

export function AssetsTab({ o, name, load, start, running }: TabProps) {
  const toast = useToast();
  const [doc, setDoc] = useState<ImageSpec[]>(o.images.images); const [style, setStyle] = useState(o.images.style || ""); const [dirty, setDirty] = useState(false);
  const [adding, setAdding] = useState<Kind | null>(null); const [newId, setNewId] = useState(""); const [newPrompt, setNewPrompt] = useState("");
  const [pick, setPick] = useState<string | null>(null); const [active, setActive] = useState<Kind>("character"); const [dragId, setDragId] = useState<string | null>(null);
  const [found, setFound] = useState<FoundStill[]>([]);
  const [story, setStory] = useState("");
  useEffect(() => { api<{ text: string }>("GET", `/api/projects/${name}/docs/Story.md`).then((r) => setStory(r.text)).catch(() => setStory("")); }, [name, o.images]);
  const secs = useRef<Partial<Record<Kind, HTMLElement | null>>>({});
  useEffect(() => { setDoc(o.images.images); setStyle(o.images.style || ""); setDirty(false); }, [o.images]);
  useEffect(() => { api<{ files: FoundStill[] }>("GET", `/api/projects/${name}/stills/unregistered`).then((r) => setFound(r.files)).catch(() => setFound([])); }, [name, o.files.stills.join("|"), o.images.images.length]);

  const file = (id: string) => o.files.stills.find((f) => stem(f) === id);
  const url = (id: string) => { const f = file(id); return f ? fileUrl(name, `stills/${encodeURIComponent(f)}`) : undefined; };
  const edit = (next: ImageSpec[]) => { setDoc(next); setDirty(true); };
  const persist = async (images: ImageSpec[], quiet = false) => { await api("PUT", `/api/projects/${name}/images`, { style, images }); if (!quiet) toast("ok", "Image list saved."); load(); };
  const save = async () => { try { await persist(doc); } catch (e: any) { toast("error", e.message); } };
  const open = (kind: Kind) => { setActive(kind); setAdding(kind); setNewId(""); setNewPrompt(""); secs.current[kind]?.scrollIntoView({ behavior: "smooth", block: "start" }); };
  const add = async (kind: Kind) => {
    const id = newId.trim().toLowerCase();
    if (!ID_OK.test(id)) return toast("error", "Use a short id: lowercase letters, numbers, - or _ (for example ramesh_sheet).");
    if (doc.some((i) => i.id === id)) return toast("error", `An asset called ${id} already exists.`);
    const spec: ImageSpec = { id, kind, out: `stills/${id}.png`, prompt: newPrompt.trim() || `${kind} ${id}`, refs: [], aspect_ratio: kind === "frame" ? "9:16" : "3:2" };
    try { await persist([...doc, spec], true); setAdding(null); setNewId(""); setNewPrompt(""); setPick(id); toast("ok", `Added ${id}. Upload your image or generate one.`); } catch (e: any) { toast("error", e.message); }
  };
  const up = async (id: string, f: File | undefined, replace: boolean) => {
    if (!f) return;
    if (!f.type.startsWith("image/") && !/\.(png|jpe?g|webp|gif|bmp|tiff?|heic|heif)$/i.test(f.name)) return toast("error", "That is not a supported image.");
    try { await upload(name, `stills/${id}.png`, f, replace); toast("ok", replace ? `Replaced ${id}. The old image is in Discarded.` : `Uploaded ${id}.`); load(); }
    catch (e: any) { toast("error", e.message); }
  };
  const discard = async (rel: string) => { const reason = await promptDialog("Why discard this image?", { title: "Discard image", ok: "Discard" }); if (reason === null) return; await api("POST", `/api/projects/${name}/discard`, { rel, reason }); load(); };
  const remove = async (id: string) => { if (await confirmDialog(`Remove ${id} from the list? (Only possible while it has no image.)`, { title: "Remove asset", ok: "Remove", danger: true })) persist(doc.filter((i) => i.id !== id)).catch((e: any) => toast("error", e.message)); };
  const toggleRef = (i: ImageSpec, ref: string) => {
    const has = i.refs.includes(ref);
    if (!has && i.refs.length >= 4) return toast("error", "At most 4 reference images.");
    edit(doc.map((x) => x.id === i.id ? { ...x, refs: has ? x.refs.filter((r) => r !== ref) : [...x.refs, ref] } : x));
  };
  // a plain function (not a component): a component defined inside render is re-created on every render, which destroys the file input and loses a file being chosen
  const uploadLabel = (id: string, replace: boolean, cls: string, text?: string) => (
    <label className={`${cls} cursor-pointer`}>
      {text ?? (replace ? "Replace" : "Upload")}
      <input type="file" accept="image/*,.heic,.heif" hidden aria-label={`${replace ? "Replace" : "Upload"} image for ${id}`} onChange={(e) => { up(id, e.target.files?.[0], replace); e.currentTarget.value = ""; }} />
    </label>
  );

  const descOf = (i: ImageSpec) => storyDescription(story, i);
  const shown = doc.find((i) => i.id === pick) || doc.find((i) => i.kind === "character") || doc[0] || null;
  const scenesOf = (i: ImageSpec) => i.kind === "frame" ? o.shots.shots.filter((s) => s.first_frame?.includes(i.id)).length : doc.filter((x) => x.refs.includes(i.id)).length;
  const topChar = doc.filter((i) => i.kind === "character").sort((a, b) => scenesOf(b) - scenesOf(a))[0];
  const pics = KINDS.flatMap((k) => doc.filter((i) => i.kind === k.kind)).map((i) => url(i.id)).filter((u): u is string => !!u);

  const cardMenu = (i: ImageSpec) => {
    const f = file(i.id);
    return (
      <Menu.Root>
        <Menu.Trigger aria-label={`More for ${i.id}`} className="icon-btn !h-8 !w-8"><MoreHorizontal size={15} /></Menu.Trigger>
        <Menu.Portal>
          <Menu.Content align="end" sideOffset={6} className="menu-surface">
            <Menu.Item className="menu-item" onSelect={() => setPick(i.id)}><Pencil size={14} />Open in preview</Menu.Item>
            <Menu.Item className="menu-item" disabled={!!running[runKey("image", i.id)] || dirty} onSelect={() => start("image", i.id)}><Sparkles size={14} />{f ? "Regenerate with AI" : "Generate with AI"}</Menu.Item>
            {f && <Menu.Item className="menu-item" onSelect={() => start("review", i.id)}><Eye size={14} />Vision review</Menu.Item>}
            <Menu.Separator className="my-1 h-px bg-slate-800" />
            {f ? <Menu.Item className="menu-item" onSelect={() => discard(`stills/${f}`)}><Trash2 size={14} />Discard image</Menu.Item>
              : <Menu.Item className="menu-item" onSelect={() => remove(i.id)}><Trash2 size={14} />Remove from list</Menu.Item>}
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
    );
  };

  const card = (i: ImageSpec, idx: number) => {
    const f = file(i.id); const rv = o.reviews[i.id] ?? o.reviews[stem(f || "")]; const sel = shown?.id === i.id;
    const n = scenesOf(i);
    const shell = `panel h-full overflow-hidden transition ${sel ? "!border-pink shadow-glow-pink" : "hover:border-slate-700"} ${dragId === i.id ? "ring-2 ring-brand" : ""}`;
    const drop = {
      onDragOver: (e: React.DragEvent) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDragId(i.id); } },
      onDragLeave: () => setDragId((d) => (d === i.id ? null : d)),
      onDrop: (e: React.DragEvent) => { e.preventDefault(); setDragId(null); up(i.id, e.dataTransfer.files?.[0], !!f); },
    };
    const thumb = (cls: string) => (
      <button type="button" onClick={() => setPick(i.id)} className="block w-full text-left" aria-label={`Open ${i.id} in the preview`}>
        <div className={`thumb !rounded-none ${cls}`}>
          {f ? <img src={url(i.id)} alt="" loading="lazy" /> : <div className="grid h-full place-items-center text-xs text-slate-500">not made yet</div>}
          {running[runKey("image", i.id)] && <span className="absolute inset-0 grid place-items-center bg-black/60 text-xs text-white">Generating...</span>}
          {i.kind === "character" && f && <span className="thumb-badge right-2 top-2 flex items-center gap-1">{n > 0 ? (topChar?.id === i.id ? <><Crown size={11} className="text-amber-300" />Main Character</> : "Supporting") : "Not used yet"}</span>}
          {i.kind === "frame" && <>
            <span className="thumb-badge left-1.5 top-1.5">{String(idx + 1).padStart(2, "0")}</span>
            {f && <span className="thumb-badge right-1.5 top-1.5">{o.shots.shots.find((s) => s.first_frame?.includes(i.id))?.seconds ?? 5}.0s</span>}
          </>}
        </div>
      </button>
    );
    if (i.kind === "frame") return (
      <li key={i.id} className="w-[10.5rem] shrink-0"><section data-asset={i.id} className={shell} {...drop}>{thumb("aspect-square")}</section></li>
    );
    if (i.kind === "background") return (
      <li key={i.id} className="min-w-0"><section data-asset={i.id} className={shell} {...drop}>
        {thumb("aspect-[4/3]")}
        <div className="flex items-center justify-between gap-1 p-2.5">
          <div className="min-w-0"><div className="truncate text-sm font-semibold">{i.id}</div><div className="text-[0.7rem] text-slate-400">{n} {n === 1 ? "scene" : "scenes"}</div></div>
          {cardMenu(i)}
        </div>
      </section></li>
    );
    return (
      <li key={i.id} className="min-w-0"><section data-asset={i.id} className={shell} {...drop}>
        {thumb("aspect-video")}
        <div className="p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0"><div className="truncate text-base font-bold">{i.id}</div><div className="text-[0.7rem] text-slate-400">{i.kind === "character" ? `${n} ${n === 1 ? "scene" : "scenes"}` : (f ? "ready" : "no image")}</div></div>
            <div className="flex shrink-0 items-center gap-1.5">
              <button type="button" className="btn btn-outline btn-sm" onClick={() => setPick(i.id)}>Edit</button>
              {uploadLabel(i.id, !!f, "btn btn-outline btn-sm")}
              {cardMenu(i)}
            </div>
          </div>
          <ReviewBadge r={rv} />
        </div>
      </section></li>
    );
  };

  const section = (k: (typeof KINDS)[number]) => {
    const kind = k.kind as Kind; const items = doc.filter((i) => i.kind === kind);
    return (
      <section key={kind} ref={(el) => { secs.current[kind] = el; }} aria-label={k.title} className="panel panel-lit panel-pad scroll-mt-20">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-x-3">
            <h2 className="flex items-center gap-2.5 text-lg font-extrabold tracking-tight">
              <span className="grid h-9 w-9 place-items-center rounded-xl border border-slate-700 text-slate-100">{KIND_ICON[kind]}</span>
              {k.title} <span className="text-sm font-semibold text-slate-400">({items.length})</span>
            </h2>
            <span className="text-xs text-slate-400">{k.sub}</span>
          </div>
          <Button variant="outline" size="sm" onClick={() => open(kind)}><Plus size={14} />Add {kind === "frame" ? "Frame" : kind === "other" ? "Upload" : k.title.replace(/s$/, "")}</Button>
        </div>
        {adding === kind && (
          <div className="panel-quiet mb-3 grid gap-2 p-3 md:grid-cols-[200px_1fr_auto]">
            <Input autoFocus placeholder={`id, e.g. ${k.idHint}`} value={newId} onChange={(e) => setNewId(e.target.value)} aria-label="Asset id" />
            <Input placeholder="what it shows (used as the prompt if you generate it)" value={newPrompt} onChange={(e) => setNewPrompt(e.target.value)} aria-label="Asset description" />
            <div className="flex gap-2"><Button size="sm" onClick={() => add(kind)} disabled={!newId.trim()}>Add</Button><Button variant="ghost" size="sm" onClick={() => setAdding(null)}>Cancel</Button></div>
            <p className="text-xs text-slate-400 md:col-span-3">{k.hint}</p>
          </div>
        )}
        {kind === "frame" ? (
          <div className="relative">
            <ul className="snap-rail">{items.map((i, n) => card(i, n))}</ul>
          </div>
        ) : (
          <ul className={kind === "background" ? "grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5" : "grid gap-3 sm:grid-cols-2 2xl:grid-cols-3"}>
            {kind !== "background" && (
              <li className="min-w-0">
                <button type="button" onClick={() => open(kind)} className="add-tile h-full min-h-[11rem] w-full p-4">
                  <span><Plus size={30} className="mx-auto text-slate-300" />
                    <span className="mt-2 block text-sm font-bold">Add {kind === "other" ? "Upload" : k.title.replace(/s$/, "")}</span>
                    <span className="mt-1 block text-xs text-slate-400">Upload an image or generate with AI</span></span>
                </button>
              </li>
            )}
            {items.map((i, n) => card(i, n))}
          </ul>
        )}
        {!items.length && adding !== kind && kind !== "character" && kind !== "other" && <EmptyState title={`No ${k.title.toLowerCase()} yet`} text={k.hint} />}
      </section>
    );
  };

  return (
    <div className="animate-fade-up">
      <PageBanner title="Assets" sub="All your characters, backgrounds, scene frames and uploaded files." note={<>Use your own assets or<br />generate with AI</>} pics={pics} />

      <PageBody stickyRail rail={shown ? (
        <AssetPreview description={descOf(shown)} renameTo={async (n) => { await api("POST", `/api/projects/${name}/assets/${shown.id}/rename`, { new: n }); toast("ok", `Renamed ${shown.id} to ${n}.`); setPick(n); load(); }} o={o} name={name} spec={shown} file={file(shown.id)} img={url(shown.id)} urlOf={url} doc={doc} setPick={setPick} dirty={dirty} save={save} running={running} start={start}
          edit={edit} toggleRef={toggleRef} upload={(replace) => uploadLabel(shown.id, replace, "btn btn-outline w-full", replace ? "Replace Image" : "Upload Image")}
          discard={discard} remove={remove} reload={load} toast={toast} />
      ) : null}>
        <div className="space-y-4">
          {found.length > 0 && <ImportStills project={name} found={found} reload={load} />}

          <div className="panel sticky top-[4.5rem] z-20 flex flex-wrap items-center gap-2 !bg-[#101017] p-3">
            <div role="tablist" aria-label="Asset types" className="flex flex-wrap gap-2">
            {KINDS.map((k) => {
              const on = active === k.kind; const kind = k.kind as Kind;
              return (
                <button key={kind} type="button" role="tab" aria-selected={on} onClick={() => { setActive(kind); secs.current[kind]?.scrollIntoView({ behavior: "smooth", block: "start" }); }}
                  className={`pill !px-4 !py-2.5 ${on ? "!border-pink/70 !bg-pink/10 !text-white !bg-none shadow-glow-pink" : "!bg-slate-900"}`}>
                  {KIND_ICON[kind]}{k.title}
                  <span className={`rounded-lg px-1.5 text-[0.72rem] ${on ? "bg-pink/30" : "bg-white/10"}`}>{doc.filter((i) => i.kind === kind).length}</span>
                </button>
              );
            })}
            </div>
            <span className="flex-1" />
            <Button variant="pink" size="sm" onClick={() => open(active)}><Plus size={14} />Create with AI</Button>
            <Button variant="outline" size="sm" onClick={() => open("other")}><UploadIcon size={14} />Upload Assets</Button>
          </div>

          {KINDS.map((k) => section(k))}

          <section className="panel panel-lit panel-pad" aria-label="Shared style">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div><h2 className="text-base font-extrabold tracking-tight">Shared style</h2><p className="text-xs text-slate-400">Added to every generated image prompt. Make assets in order: characters, backgrounds, then scene frames.</p></div>
              <div className="flex items-center gap-2">{dirty && <span className="text-xs text-amber-400">unsaved changes</span>}<Button variant={dirty ? "pink" : "outline"} size="sm" onClick={save}>Save list</Button></div>
            </div>
            <Field id="shared-style" rows={2} value={style} aria-label="Shared style for generated images" onChange={(e) => { setStyle(e.target.value); setDirty(true); }} />
          </section>
        </div>
      </PageBody>
    </div>
  );
}

/** Right rail: large preview of the selected asset with prev/next, then its details. */
function AssetPreview({ description, renameTo, o, name, spec, file, img, urlOf, doc, setPick, dirty, save, running, start, edit, toggleRef, upload, discard, remove, reload, toast }: {
  description: string; renameTo: (n: string) => Promise<void>;
  o: TabProps["o"]; name: string; spec: ImageSpec; file?: string; img?: string; urlOf: (id: string) => string | undefined; doc: ImageSpec[]; setPick: (id: string) => void;
  dirty: boolean; save: () => void; running: TabProps["running"]; start: TabProps["start"]; edit: (n: ImageSpec[]) => void; toggleRef: (i: ImageSpec, r: string) => void;
  upload: (replace: boolean) => React.ReactNode; discard: (rel: string) => void; remove: (id: string) => void; reload: () => void; toast: (k: "ok" | "error" | "info", t: string) => void;
}) {
  const [tab, setTab] = useState<"details" | "used">("details");
  const idx = doc.findIndex((d) => d.id === spec.id);
  const step = (d: number) => setPick(doc[(idx + d + doc.length) % doc.length].id);
  const usedShots = o.shots.shots.filter((s) => s.first_frame?.includes(spec.id));
  const usedBy = doc.filter((i) => i.refs.includes(spec.id));
  const others = doc.filter((x) => x.id !== spec.id && !spec.refs.includes(x.id));
  const busy = !!running[runKey("image", spec.id)];
  const refMenu = (trigger: React.ReactNode, label: string) => (
    <Menu.Root>
      <Menu.Trigger aria-label={label} className="rounded-xl">{trigger}</Menu.Trigger>
      <Menu.Portal>
        <Menu.Content align="start" sideOffset={6} className="menu-surface">
          {others.length ? others.map((x) => <Menu.Item key={x.id} className="menu-item font-mono text-xs" onSelect={() => toggleRef(spec, x.id)}>{x.id}</Menu.Item>) : <div className="px-3 py-2 text-xs text-slate-400">No more assets to add.</div>}
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
  return (
    <>
      <RailCard title="Asset Preview" right={file ? <a href={img} target="_blank" rel="noreferrer" aria-label="Open the image full size" className="icon-btn !h-8 !w-8"><Maximize2 size={14} /></a> : undefined}>
        <div className="thumb relative aspect-video w-full">
          {file ? <img src={img} alt={`${spec.id} preview`} /> : <div className="grid h-full place-items-center text-xs text-slate-500">nothing to preview yet</div>}
          {doc.length > 1 && <>
            <button type="button" aria-label="Previous asset" onClick={() => step(-1)} className="absolute left-2 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-full border border-slate-600 bg-black/70 text-white hover:bg-slate-800"><ChevronLeft size={16} /></button>
            <button type="button" aria-label="Next asset" onClick={() => step(1)} className="absolute right-2 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-full border border-slate-600 bg-black/70 text-white hover:bg-slate-800"><ChevronRight size={16} /></button>
          </>}
        </div>
        <div className="mt-3 flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-2"><span className="truncate text-lg font-extrabold">{spec.id}</span>
            <RenameButton kind="asset" current={spec.id} label={`Rename asset ${spec.id}`}
              explain="The image file, the image list, the references in other assets, the shots that use it as a first frame, and its cost and discard history are all updated."
              onRename={async (n) => { await api("POST", `/api/projects/${name}/assets/${spec.id}/rename`, { new: n }); toast("ok", `Renamed ${spec.id} to ${n}.`); reload(); }} />
          </span>
          <Badge tone="pink">{spec.kind}</Badge>
        </div>

        <div role="tablist" aria-label="Asset details" className="mt-3 flex border-b border-slate-800">
          {(["details", "used"] as const).map((t) => (
            <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
              className={`flex-1 border-b-2 px-3 py-2 text-xs font-bold transition ${tab === t ? "border-pink text-pink" : "border-transparent text-slate-400 hover:text-slate-100"}`}>
              {t === "details" ? "Details" : `Used In (${usedShots.length + usedBy.length})`}
            </button>
          ))}
        </div>

        {tab === "details" && (
          <div className="mt-3 space-y-3">
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-300" htmlFor={`n-${spec.id}`}>Name (file name)</label>
              <input key={spec.id} id={`n-${spec.id}`} defaultValue={spec.id} aria-label={`Name of ${spec.id}`} className="field !py-2 !text-sm font-mono"
                onBlur={async (e) => {
                  const v = e.target.value.trim().toLowerCase(); if (v === spec.id) return;
                  if (!ID_OK.test(v)) { toast("error", "Use a short name: lowercase letters, numbers, - or _."); e.target.value = spec.id; return; }
                  try { await renameTo(v); } catch (er: any) { toast("error", er.message); e.target.value = spec.id; }
                }}
                onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") { e.currentTarget.value = spec.id; e.currentTarget.blur(); } }} />
              <p className="mt-1 text-[0.68rem] text-slate-400">Renames the image, the list, references, shots and history.</p>
            </div>
            <div>
              <span className="mb-1 block text-xs font-semibold text-slate-300">Description <span className="font-normal text-slate-400">(from Story.md)</span></span>
              <div className="panel-quiet whitespace-pre-line px-3 py-2 text-sm leading-relaxed text-slate-200">{description || <span className="italic text-slate-500">Nothing about "{spec.id}" in Story.md yet. Add a "### {spec.id}" section there.</span>}</div>
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-300" htmlFor={`d-${spec.id}`}>Prompt <span className="font-normal text-slate-400">(used to generate the image)</span></label>
              <Field id={`d-${spec.id}`} rows={5} className="!text-sm" value={spec.prompt} aria-label={`Prompt for ${spec.id}`} onChange={(e) => edit(doc.map((x) => x.id === spec.id ? { ...x, prompt: e.target.value } : x))} />
              {description && description !== spec.prompt && <button type="button" className="mt-1 text-[0.7rem] text-brand hover:underline" onClick={() => edit(doc.map((x) => x.id === spec.id ? { ...x, prompt: `${spec.kind} ${spec.id}: ${description.replace(/\n/g, ". ")}` } : x))}>Fill the prompt from the description</button>}
            </div>
            <div>
              <span className="mb-1 block text-xs font-semibold text-slate-300">Tags</span>
              <div className="flex flex-wrap items-center gap-1.5">
                {spec.refs.map((r) => (
                  <button key={r} type="button" onClick={() => toggleRef(spec, r)} aria-label={`Remove reference ${r}`} className="pill !px-3 !py-1 !text-xs">{r}<X size={11} /></button>
                ))}
                {refMenu(<span className="grid h-8 w-8 place-items-center rounded-full border border-slate-700 text-slate-300 hover:bg-slate-300/10"><Plus size={14} /></span>, "Add a reference")}
              </div>
            </div>
            <div>
              <span className="mb-1 block text-xs font-semibold text-slate-300">Ref Image</span>
              <div className="flex flex-wrap gap-2">
                {spec.refs.map((r) => (
                  <div key={r} className="thumb h-[4.5rem] w-[4.5rem]" title={r}>{urlOf(r) ? <img src={urlOf(r)} alt={r} /> : <div className="grid h-full place-items-center text-[0.6rem] text-slate-500">{r}</div>}</div>
                ))}
                {refMenu(<span className="add-tile h-[4.5rem] w-[4.5rem]"><Plus size={18} className="text-slate-400" /></span>, "Add a reference image")}
              </div>
            </div>
            {dirty && <Button variant="pink" className="w-full" onClick={save}>Save changes</Button>}
            <div className="space-y-2 pt-1">
              {upload(!!file)}
              <Button variant="pink" className="w-full" disabled={busy || dirty} title={dirty ? "Save the changes first" : ""} onClick={() => start("image", spec.id)}>
                {busy ? <><Spinner size={14} />Working...</> : <><Wand2 size={15} />{file ? "Edit with AI" : "Generate with AI"}</>}
              </Button>
              {file && <Button variant="outline" className="w-full" disabled={!!running[runKey("review", spec.id)]} onClick={() => start("review", spec.id)}><Eye size={15} />Vision review</Button>}
              <Button variant="outline" className="w-full !border-red-400/40 !text-red-300" onClick={() => (file ? discard(`stills/${file}`) : remove(spec.id))}>
                <Trash2 size={15} />{file ? "Delete Asset" : "Remove Asset"}
              </Button>
            </div>
          </div>
        )}

        {tab === "used" && (
          <ul className="mt-3 space-y-1.5 text-xs">
            {usedShots.map((s) => <li key={s.id} className="row-hover flex items-center justify-between gap-2 rounded-lg border border-slate-800 px-2.5 py-2"><span className="truncate font-semibold">{s.note || s.id}</span><span className="tag shrink-0">{s.seconds}.0s</span></li>)}
            {usedBy.map((i) => <li key={i.id} className="row-hover flex items-center justify-between gap-2 rounded-lg border border-slate-800 px-2.5 py-2"><button type="button" className="truncate font-semibold hover:underline" onClick={() => setPick(i.id)}>{i.id}</button><span className="tag shrink-0">{i.kind}</span></li>)}
            {!usedShots.length && !usedBy.length && <li className="text-slate-400">Nothing uses this asset yet.</li>}
          </ul>
        )}
      </RailCard>
      <RailCard title="Verification"><VerifyBar scope="assets" label="Assets" /></RailCard>
    </>
  );
}
