import { useCallback, useEffect, useRef, useState } from "react";
import { AlignCenter, AlignJustify, AlignLeft, AlignRight, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Bold, CaseSensitive, CheckCheck, ChevronDown, ChevronUp, Clock, Film, Italic, Layers, Music, Plus, Trash2, Underline, Upload } from "lucide-react";
import type { AClip, Aspect, Edit, FontInfo, Sel, TText, Tool, TransitionType, VClip, TElement, TransitionConfig, TSubtitleCue, TFilter, TEffect, TBackgroundConfig } from "./types";
import { MAX_TEXT, TRANSITION_GROUPS, FILTER_PRESETS, EFFECT_PRESETS, BACKGROUND_PRESETS } from "./types";
import { clamp, fileName, layout, round1, round2 } from "./time";
import { fileUrl, listElements } from "../api";

const TRANSITION_LABEL: Record<string, string> = Object.fromEntries(TRANSITION_GROUPS.flatMap((g) => g.items).map((t) => [t.id, t.label]));
const SWATCH = ["#a855f7", "#ffffff", "#ff2d95", "#111827"];
const PRESET_DURS = [0.3, 0.5, 0.8, 1.0, 1.5, 2.0];

export function Range({ value, min, max, step = 1, onChange, label }: { value: number; min: number; max: number; step?: number; onChange: (v: number) => void; label: string }) {
  const pct = ((value - min) / (max - min)) * 100;
  return <input type="range" aria-label={label} className="re-range" min={min} max={max} step={step} value={value} style={{ ["--p" as any]: `${pct}%` }} onChange={(e) => onChange(parseFloat(e.target.value))} />;
}
const Switch = ({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) =>
  <button type="button" role="switch" aria-checked={on} aria-label={label} className={`re-switch ${on ? "is-on" : ""}`} onClick={() => onChange(!on)}><span /></button>;
const Row = ({ label, children, className = "" }: { label: string; children: React.ReactNode; className?: string }) =>
  <div className={`re-prow ${className}`}><span className="re-plabel">{label}</span><div className="re-pctl">{children}</div></div>;
const Num = ({ value, onChange, min, max, step = 1, label, w = "w-20" }: { value: number; onChange: (v: number) => void; min: number; max: number; step?: number; label: string; w?: string }) =>
  <input type="number" aria-label={label} className={`re-num ${w}`} value={Number.isFinite(value) ? value : 0} min={min} max={max} step={step}
    onChange={(e) => { const v = parseFloat(e.target.value); if (!Number.isNaN(v)) onChange(clamp(v, min, max)); }} />;

function ColorRow({ value, onChange, allowNone, label }: { value: string | null; onChange: (c: string | null) => void; allowNone?: boolean; label: string }) {
  const pick = useRef<HTMLInputElement>(null);
  return (
    <div className="flex items-center gap-2">
      {allowNone && <button type="button" aria-label={`${label}: none`} aria-pressed={value === null} className={`re-swatch ${value === null ? "is-on" : ""}`} onClick={() => onChange(null)} />}
      {SWATCH.map((c) => <button key={c} type="button" aria-label={`${label} ${c}`} aria-pressed={value === c} className={`re-swatch ${value === c ? "is-on" : ""}`} style={{ background: c }} onClick={() => onChange(c)} />)}
      <button type="button" aria-label={`${label}: custom colour`} className="re-swatch re-swatch-plus" onClick={() => pick.current?.click()}><Plus size={15} /></button>
      <input ref={pick} type="color" tabIndex={-1} aria-hidden className="sr-only" value={value || "#ffffff"} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function PanelHead({ title, onDelete, delLabel }: { title: string; onDelete?: () => void; delLabel?: string }) {
  return <div className="re-phead"><h2>{title}</h2>{onDelete && <button type="button" className="re-tb" aria-label={delLabel || "Delete"} title={delLabel || "Delete"} onClick={onDelete}><Trash2 size={18} /></button>}</div>;
}

function TextPanel({ t, fonts, patch, remove }: { t: TText; fonts: FontInfo[]; patch: (p: Partial<TText>, key?: string) => void; remove: () => void }) {
  const fam = fonts.find((f) => f.family === t.font) || fonts[0];
  const weights = fam?.weights || [{ weight: 700, name: "Bold", file: "" }];
  const setBold = (b: boolean) => { const w = b ? (weights.find((x) => x.weight === 700) ? 700 : weights[weights.length - 1].weight) : (weights.find((x) => x.weight === 400) ? 400 : weights[0].weight); patch({ bold: b, weight: w }); };
  return (
    <>
      <PanelHead title="Text" onDelete={remove} delLabel="Delete text" />
      <div className="re-textarea-wrap">
        <textarea aria-label="Text" className="re-textarea" rows={2} maxLength={MAX_TEXT} value={t.text} onChange={(e) => patch({ text: e.target.value }, `txt${t.id}`)} />
        <span className="re-count">{t.text.length}/{MAX_TEXT}</span>
      </div>
      <Row label="Font">
        <div className="re-selwrap flex-1"><select aria-label="Font" className="re-select" value={t.font} onChange={(e) => { const f = fonts.find((x) => x.family === e.target.value); const w = f?.weights.find((x) => x.weight === t.weight)?.weight ?? (f?.weights.find((x) => x.weight === 400)?.weight ?? f?.weights[0].weight ?? 400); patch({ font: e.target.value, weight: w, bold: w >= 600 }); }}>
          {fonts.map((f) => <option key={f.family} value={f.family}>{f.family}</option>)}</select><ChevronDown size={15} /></div>
        <div className="re-selwrap w-28"><select aria-label="Font weight" className="re-select" value={t.weight} onChange={(e) => { const w = parseInt(e.target.value, 10); patch({ weight: w, bold: w >= 600 }); }}>
          {weights.map((w) => <option key={w.weight} value={w.weight}>{w.name}</option>)}</select><ChevronDown size={15} /></div>
      </Row>
      <Row label="Size">
        <div className="re-stepper"><input type="number" aria-label="Size" min={8} max={300} value={t.size} onChange={(e) => { const v = parseInt(e.target.value, 10); if (!Number.isNaN(v)) patch({ size: clamp(v, 8, 300) }, `size${t.id}`); }} />
          <span><button type="button" aria-label="Larger" onClick={() => patch({ size: clamp(t.size + 2, 8, 300) }, `size${t.id}`)}><ChevronUp size={13} /></button><button type="button" aria-label="Smaller" onClick={() => patch({ size: clamp(t.size - 2, 8, 300) }, `size${t.id}`)}><ChevronDown size={13} /></button></span></div>
      </Row>
      <Row label="Color"><ColorRow value={t.color} label="Text colour" onChange={(c) => c && patch({ color: c })} /></Row>
      <Row label="Background"><ColorRow value={t.bg} allowNone label="Background" onChange={(c) => patch({ bg: c })} /></Row>
      <Row label="Alignment">
        <div className="flex gap-2">{([["left", AlignLeft], ["center", AlignCenter], ["right", AlignRight], ["justify", AlignJustify]] as const).map(([a, I]) =>
          <button key={a} type="button" className={`re-sq ${t.align === a ? "is-on" : ""}`} aria-label={`Align ${a}`} aria-pressed={t.align === a} onClick={() => patch({ align: a })}><I size={17} /></button>)}</div>
      </Row>
      <Row label="Style">
        <div className="flex gap-2">
          <button type="button" className={`re-sq ${t.bold ? "is-on" : ""}`} aria-label="Bold" aria-pressed={t.bold} onClick={() => setBold(!t.bold)}><Bold size={17} /></button>
          <button type="button" className={`re-sq ${t.italic ? "is-on" : ""}`} aria-label="Italic" aria-pressed={t.italic} onClick={() => patch({ italic: !t.italic })}><Italic size={17} /></button>
          <button type="button" className={`re-sq ${t.underline ? "is-on" : ""}`} aria-label="Underline" aria-pressed={t.underline} onClick={() => patch({ underline: !t.underline })}><Underline size={17} /></button>
          <button type="button" className={`re-sq ${t.caps ? "is-on" : ""}`} aria-label="Capital letters" aria-pressed={t.caps} onClick={() => patch({ caps: !t.caps })}><CaseSensitive size={19} /></button>
        </div>
      </Row>
      <Row label="Opacity"><Range label="Opacity" value={Math.round(t.opacity * 100)} min={0} max={100} onChange={(v) => patch({ opacity: v / 100 }, `op${t.id}`)} /><span className="re-val">{Math.round(t.opacity * 100)}%</span></Row>
      <Row label="Shadow">
        <Switch on={t.shadow.on} label="Shadow" onChange={(v) => patch({ shadow: { ...t.shadow, on: v } })} />
        <input type="color" aria-label="Shadow colour" className="re-colorchip" value={t.shadow.color} onChange={(e) => patch({ shadow: { ...t.shadow, color: e.target.value } })} />
        <span className="re-plabel !w-auto">Blur</span>
        <Range label="Shadow blur" value={t.shadow.blur} min={0} max={100} onChange={(v) => patch({ shadow: { ...t.shadow, blur: v, on: true } }, `bl${t.id}`)} /><span className="re-val">{t.shadow.blur}</span>
      </Row>
      <Row label="Timing">
        <label className="re-mini">Start<Num label="Start (s)" value={round1(t.start)} min={0} max={36000} step={0.1} onChange={(v) => patch({ start: v, end: Math.max(t.end, v + 0.3) })} w="w-16" /></label>
        <label className="re-mini">End<Num label="End (s)" value={round1(t.end)} min={0.3} max={36000} step={0.1} onChange={(v) => patch({ end: Math.max(v, t.start + 0.3) })} w="w-16" /></label>
      </Row>
    </>
  );
}

function ElementPanel({ el, project, patch, remove }: { el: TElement; project: string; patch: (p: Partial<TElement>, key?: string) => void; remove: () => void }) {
  return (
    <>
      <PanelHead title="Element Overlay" onDelete={remove} delLabel="Delete element" />
      <div className="flex items-center gap-3 p-2.5 rounded-xl border border-slate-800 bg-slate-900/60 mb-3">
        <img src={fileUrl(project, el.src)} className="w-12 h-12 object-contain bg-black/60 rounded-lg p-1 border border-slate-700/50" alt="" />
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-sm truncate text-white">{el.name || fileName(el.src)}</div>
          <div className="text-xs text-slate-400 truncate">{el.src}</div>
        </div>
      </div>
      <Row label="Scale">
        <Range label="Scale" value={Math.round(el.scale * 100)} min={5} max={250} step={1} onChange={(v) => patch({ scale: round2(v / 100) }, `sc${el.id}`)} />
        <span className="re-val">{Math.round(el.scale * 100)}%</span>
      </Row>
      <Row label="Opacity">
        <Range label="Opacity" value={Math.round((el.opacity ?? 1) * 100)} min={0} max={100} step={1} onChange={(v) => patch({ opacity: round2(v / 100) }, `op${el.id}`)} />
        <span className="re-val">{Math.round((el.opacity ?? 1) * 100)}%</span>
      </Row>
      <Row label="Position">
        <label className="re-mini">X<Num label="Position X" value={round2(el.x * 100)} min={0} max={100} step={1} onChange={(v) => patch({ x: round2(v / 100) }, `px${el.id}`)} w="w-16" />%</label>
        <label className="re-mini">Y<Num label="Position Y" value={round2(el.y * 100)} min={0} max={100} step={1} onChange={(v) => patch({ y: round2(v / 100) }, `py${el.id}`)} w="w-16" />%</label>
      </Row>
      <div className="re-grid-btns mt-2" role="group" aria-label="Quick placement">
        <button type="button" className="re-chip" onClick={() => patch({ x: 0.5, y: 0.5 }, `ctr${el.id}`)}>Center</button>
        <button type="button" className="re-chip" onClick={() => patch({ x: 0.15, y: 0.15 }, `tl${el.id}`)}>Top Left</button>
        <button type="button" className="re-chip" onClick={() => patch({ x: 0.85, y: 0.15 }, `tr${el.id}`)}>Top Right</button>
        <button type="button" className="re-chip" onClick={() => patch({ x: 0.15, y: 0.85 }, `bl${el.id}`)}>Bottom Left</button>
        <button type="button" className="re-chip" onClick={() => patch({ x: 0.85, y: 0.85 }, `br${el.id}`)}>Bottom Right</button>
      </div>
      <Row label="Timing">
        <label className="re-mini">Start<Num label="Start (s)" value={round1(el.start)} min={0} max={36000} step={0.1} onChange={(v) => patch({ start: v, end: Math.max(el.end, v + 0.3) })} w="w-16" /></label>
        <label className="re-mini">End<Num label="End (s)" value={round1(el.end)} min={0.3} max={36000} step={0.1} onChange={(v) => patch({ end: Math.max(v, el.start + 0.3) })} w="w-16" /></label>
      </Row>
      <p className="re-note">You can also drag and resize the element directly in the preview window.</p>
    </>
  );
}

function ElementsLibraryPanel({ project, addElement, uploadElement, uploading }: { project: string; addElement: (src: string, name?: string) => void; uploadElement: (f: File) => void; uploading: boolean }) {
  const fileIn = useRef<HTMLInputElement>(null);
  const [assets, setAssets] = useState<Array<{ src: string; name: string; kind: "uploaded" | "still" }>>([]);
  const [filter, setFilter] = useState<"all" | "uploaded" | "still">("all");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    setLoading(true);
    listElements(project)
      .then((res) => setAssets(res))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [project]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const filtered = assets.filter((a) => (filter === "all" ? true : a.kind === filter));

  return (
    <>
      <PanelHead title="Elements & Overlays" />
      <p className="re-note !mt-0">Upload custom graphics, badges, or logos, or pick from your project stills to overlay on screen.</p>
      <input ref={fileIn} type="file" accept=".png,.jpg,.jpeg,.webp,.svg,image/*" className="sr-only" aria-label="Upload an image overlay" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) { uploadElement(f); setTimeout(refresh, 800); } }} />
      <button type="button" className="re-chip re-chip-lg w-full justify-center !my-3" disabled={uploading} onClick={() => fileIn.current?.click()}>
        <Upload size={16} />{uploading ? "Uploading..." : "Upload Image / Asset"}
      </button>

      <div className="flex items-center gap-1.5 my-2">
        {(["all", "uploaded", "still"] as const).map((k) => (
          <button key={k} type="button" className={`re-chip text-xs !py-1 !px-2.5 ${filter === k ? "is-on" : ""}`} onClick={() => setFilter(k)}>
            {k === "all" ? "All Assets" : k === "uploaded" ? "Uploaded" : "Project Stills"}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="re-note text-center py-4">Loading assets...</p>
      ) : filtered.length === 0 ? (
        <div className="re-soon !my-3">
          <p>No {filter === "all" ? "" : filter} assets found.</p>
          <p className="text-xs mt-1">Upload a PNG/JPG or generate story stills.</p>
        </div>
      ) : (
        <div className="re-asset-grid" data-testid="elements-asset-grid">
          {filtered.map((item) => (
            <div key={item.src} className="re-asset-card" onClick={() => addElement(item.src, item.name)} title={`Add ${item.name} to video`}>
              <img src={fileUrl(project, item.src)} className="re-asset-thumb" alt={item.name} loading="lazy" />
              <span className="re-asset-name">{item.name}</span>
              <span className="text-[11px] text-violet-400 flex items-center gap-1 mt-1 font-semibold"><Plus size={12} />Add overlay</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function TransitionPicker({ clip, patch, first, onApplyAll, maxDur }: {
  clip: VClip; patch: (p: Partial<VClip>, key?: string) => void; first: boolean; onApplyAll?: () => void; maxDur?: number;
}) {
  const tr = clip.transition;
  const isCut = tr.type === "cut";
  const isWipe = tr.type.startsWith("wipe");
  const isSlide = tr.type.startsWith("slide") || tr.type.startsWith("smooth");
  const isFade = tr.type === "fade" || tr.type === "fadewhite" || tr.type === "fadegrays";

  const changeType = (newType: string) => {
    patch({ transition: { ...tr, type: newType } }, `ttype${clip.id}`);
  };

  const changeDur = (d: number) => {
    patch({ transition: { ...tr, dur: round1(clamp(d, 0.1, maxDur ?? 3.0)) } }, `tdur${clip.id}`);
  };

  const setDirection = (dir: "left" | "right" | "up" | "down") => {
    if (isWipe) {
      const type = dir === "left" ? "wipe" : `wipe${dir}`;
      patch({ transition: { ...tr, type, direction: dir } }, `tdir${clip.id}`);
    } else if (isSlide) {
      const type = `slide${dir}`;
      patch({ transition: { ...tr, type, direction: dir } }, `tdir${clip.id}`);
    }
  };

  const setColor = (col: "black" | "white" | "gray") => {
    const type = col === "black" ? "fade" : (col === "white" ? "fadewhite" : "fadegrays");
    patch({ transition: { ...tr, type, color: col } }, `tcol${clip.id}`);
  };

  return (
    <div className="space-y-3">
      <div className="re-selwrap">
        <select aria-label="Transition into this clip" className="re-select" disabled={first} value={tr.type} onChange={(e) => changeType(e.target.value)}>
          {TRANSITION_GROUPS.map((g) => <optgroup key={g.group} label={g.group}>{g.items.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}</optgroup>)}
        </select><ChevronDown size={15} />
      </div>
      <div className="re-grid-btns" role="group" aria-label="Popular transitions">
        {[
          { id: "cut", label: "Cut" },
          { id: "dissolve", label: "Dissolve" },
          { id: "crossfade", label: "Crossfade" },
          { id: "fade", label: "Dip Black" },
          { id: "fadewhite", label: "Dip White" },
          { id: "wipe", label: "Wipe Left" },
          { id: "wiperight", label: "Wipe Right" },
          { id: "slideleft", label: "Slide Left" },
          { id: "slideright", label: "Slide Right" },
          { id: "circleopen", label: "Circle Open" },
          { id: "pixelize", label: "Pixelate" },
          { id: "zoomin", label: "Zoom In" },
        ].map((item) => (
          <button key={item.id} type="button" disabled={first} aria-pressed={tr.type === item.id} className={`re-chip ${tr.type === item.id ? "is-on" : ""}`}
            onClick={() => changeType(item.id)}>{item.label}</button>
        ))}
      </div>

      {!isCut && (
        <div className="rounded-xl border border-slate-800 bg-[#0e0e18] p-3 space-y-3">
          <Row label="Duration">
            <Range label="Transition duration" value={tr.dur} min={0.1} max={Math.min(maxDur ?? 3.0, 3.0)} step={0.1} onChange={changeDur} />
            <span className="re-val">{tr.dur.toFixed(1)}s</span>
          </Row>
          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-400 font-medium">Timer Presets:</span>
            <div className="flex flex-wrap gap-1">
              {PRESET_DURS.map((d) => (
                <button key={d} type="button" disabled={first} className={`px-2 py-0.5 rounded text-[11px] font-bold border transition ${tr.dur === d ? "!border-pink-500 !bg-pink-500/20 text-pink-300" : "border-slate-700 bg-slate-800/80 text-slate-300 hover:border-slate-500"}`}
                  onClick={() => changeDur(d)}>{d}s</button>
              ))}
            </div>
          </div>

          {(isWipe || isSlide) && (
            <Row label="Direction">
              <div className="flex items-center gap-1">
                <button type="button" title="Left" className={`re-chip !px-2.5 ${tr.type.includes("left") || tr.type === "wipe" ? "is-on" : ""}`} onClick={() => setDirection("left")}><ArrowLeft size={13} /></button>
                <button type="button" title="Right" className={`re-chip !px-2.5 ${tr.type.includes("right") ? "is-on" : ""}`} onClick={() => setDirection("right")}><ArrowRight size={13} /></button>
                <button type="button" title="Up" className={`re-chip !px-2.5 ${tr.type.includes("up") ? "is-on" : ""}`} onClick={() => setDirection("up")}><ArrowUp size={13} /></button>
                <button type="button" title="Down" className={`re-chip !px-2.5 ${tr.type.includes("down") ? "is-on" : ""}`} onClick={() => setDirection("down")}><ArrowDown size={13} /></button>
              </div>
            </Row>
          )}

          {isFade && (
            <Row label="Dip Color">
              <div className="flex items-center gap-1">
                <button type="button" className={`re-chip ${tr.type === "fade" ? "is-on" : ""}`} onClick={() => setColor("black")}>Black</button>
                <button type="button" className={`re-chip ${tr.type === "fadewhite" ? "is-on" : ""}`} onClick={() => setColor("white")}>White</button>
                <button type="button" className={`re-chip ${tr.type === "fadegrays" ? "is-on" : ""}`} onClick={() => setColor("gray")}>Gray</button>
              </div>
            </Row>
          )}

          {onApplyAll && (
            <button type="button" className="btn btn-outline w-full !py-2 text-xs font-semibold flex items-center justify-center gap-1.5 !border-violet-500/50 text-violet-300 hover:!bg-violet-900/30"
              onClick={onApplyAll}>
              <CheckCheck size={14} /> Apply {TRANSITION_LABEL[tr.type] || tr.type} ({tr.dur}s) to all cuts
            </button>
          )}
        </div>
      )}

      <p className="re-note !mt-2">{first ? "The first clip has nothing before it." : "Plays live in the preview canvas and exported via ffmpeg."}</p>
    </div>
  );
}

function ClipPanel({ clip, idx, patch, remove, srcDur, onApplyAll }: { clip: VClip; idx: number; patch: (p: Partial<VClip>, key?: string) => void; remove: () => void; srcDur?: number; onApplyAll?: () => void }) {
  return (
    <>
      <PanelHead title="Clip" onDelete={remove} delLabel="Delete clip" />
      <p className="re-note !mt-0 truncate" title={clip.src}><Film size={13} className="mr-1 inline" />{fileName(clip.src)}{srcDur ? ` (${srcDur.toFixed(1)}s long)` : ""}</p>
      <Row label="Trim">
        <label className="re-mini">In<Num label="Clip in (s)" value={round1(clip.in)} min={0} max={clip.out - 0.3} step={0.1} onChange={(v) => patch({ in: round2(v) }, `in${clip.id}`)} w="w-16" /></label>
        <label className="re-mini">Out<Num label="Clip out (s)" value={round1(clip.out)} min={clip.in + 0.3} max={srcDur ?? 36000} step={0.1} onChange={(v) => patch({ out: round2(v) }, `out${clip.id}`)} w="w-16" /></label>
      </Row>
      <Row label="Volume"><Range label="Clip volume" value={Math.round(clip.volume * 100)} min={0} max={200} onChange={(v) => patch({ volume: v / 100 }, `vol${clip.id}`)} /><span className="re-val">{Math.round(clip.volume * 100)}%</span></Row>
      <h3 className="re-sub">Transition into this clip</h3>
      <TransitionPicker clip={clip} patch={patch} first={idx === 0} onApplyAll={idx > 0 ? onApplyAll : undefined} />
    </>
  );
}

function AudioPanel({ a, patch, remove, srcDur }: { a: AClip; patch: (p: Partial<AClip>, key?: string) => void; remove: () => void; srcDur?: number }) {
  return (
    <>
      <PanelHead title="Audio" onDelete={remove} delLabel="Delete sound" />
      <p className="re-note !mt-0 truncate"><Music size={13} className="mr-1 inline" />{a.name || fileName(a.src)}</p>
      <Row label="Volume"><Range label="Sound volume" value={Math.round(a.volume * 100)} min={0} max={200} onChange={(v) => patch({ volume: v / 100 }, `av${a.id}`)} /><span className="re-val">{Math.round(a.volume * 100)}%</span></Row>
      <Row label="Starts at"><Num label="Sound starts at (s)" value={round1(a.start)} min={0} max={36000} step={0.1} onChange={(v) => patch({ start: v })} w="w-20" /></Row>
      <Row label="Trim">
        <label className="re-mini">In<Num label="Sound in (s)" value={round1(a.in)} min={0} max={a.out - 0.3} step={0.1} onChange={(v) => patch({ in: round2(v) })} w="w-16" /></label>
        <label className="re-mini">Out<Num label="Sound out (s)" value={round1(a.out)} min={a.in + 0.3} max={srcDur ?? 36000} step={0.1} onChange={(v) => patch({ out: round2(v) })} w="w-16" /></label>
      </Row>
      <Row label="Fade in"><Range label="Fade in" value={a.fadeIn} min={0} max={10} step={0.1} onChange={(v) => patch({ fadeIn: round1(v) }, `fi${a.id}`)} /><span className="re-val">{a.fadeIn.toFixed(1)}s</span></Row>
      <Row label="Fade out"><Range label="Fade out" value={a.fadeOut} min={0} max={10} step={0.1} onChange={(v) => patch({ fadeOut: round1(v) }, `fo${a.id}`)} /><span className="re-val">{a.fadeOut.toFixed(1)}s</span></Row>
    </>
  );
}

const SOON: Partial<Record<Tool, string>> = {
  filters: "Colour filters", effects: "Visual effects", subtitles: "Automatic captions", background: "Background colour and blur",
};

export interface InspectorProps {
  project: string; edit: Edit; sel: Sel; tool: Tool; fonts: FontInfo[]; clips: string[]; durs: Record<string, number>;
  patch: (kind: "video" | "text" | "audio" | "elements", id: string, p: any, key?: string) => void; remove: (s: NonNullable<Sel>) => void;
  addClip: (file: string) => void; addText: (preset: "title" | "subtitle" | "caption") => void; uploadAudio: (f: File) => void;
  addElement: (src: string, name?: string) => void; uploadElement: (f: File) => void;
  setAspect: (a: Aspect) => void; uploading: boolean;
  setSel: (s: Sel) => void;
  applyAllTransitions?: (t: TransitionConfig) => void;
  t?: number;
  patchRoot?: (p: Partial<Edit>, key?: string) => void;
  patchSubtitles?: (cues: TSubtitleCue[], style?: "tiktok" | "classic" | "minimal") => void;
}

function FiltersPanel({ edit, patchRoot }: { edit: Edit; patchRoot?: (p: Partial<Edit>, key?: string) => void }) {
  const cur = edit.filter || { id: "none", intensity: 1.0 };
  return (
    <>
      <PanelHead title="Color Filters" />
      <p className="re-note !mt-0">Apply cinematic color grading and mood presets across your video.</p>
      <div className="re-grid-btns mt-3" role="group" aria-label="Filter presets">
        {FILTER_PRESETS.map((f) => (
          <button key={f.id} type="button" aria-pressed={cur.id === f.id}
            className={`re-chip ${cur.id === f.id ? "is-on" : ""}`}
            onClick={() => patchRoot?.({ filter: { id: f.id, intensity: cur.intensity || 1.0 } }, "filter")}>
            {f.label}
          </button>
        ))}
      </div>
      {cur.id !== "none" && (
        <div className="mt-4 rounded-xl border border-slate-800 bg-[#0e0e18] p-3 space-y-3">
          <Row label="Intensity">
            <Range label="Filter intensity" value={Math.round((cur.intensity ?? 1) * 100)} min={0} max={100} step={1}
              onChange={(v) => patchRoot?.({ filter: { ...cur, intensity: v / 100 } }, "filter_int")} />
            <span className="re-val">{Math.round((cur.intensity ?? 1) * 100)}%</span>
          </Row>
        </div>
      )}
    </>
  );
}

function EffectsPanel({ edit, patchRoot }: { edit: Edit; patchRoot?: (p: Partial<Edit>, key?: string) => void }) {
  const cur = edit.effect || { id: "none", intensity: 1.0 };
  return (
    <>
      <PanelHead title="Visual Effects" />
      <p className="re-note !mt-0">Add textures, camera motion, and cinematic overlays.</p>
      <div className="re-grid-btns mt-3" role="group" aria-label="Effect presets">
        {EFFECT_PRESETS.map((fx) => (
          <button key={fx.id} type="button" aria-pressed={cur.id === fx.id}
            className={`re-chip ${cur.id === fx.id ? "is-on" : ""}`}
            onClick={() => patchRoot?.({ effect: { id: fx.id, intensity: cur.intensity || 1.0 } }, "effect")}>
            {fx.label}
          </button>
        ))}
      </div>
      {cur.id !== "none" && (
        <div className="mt-4 rounded-xl border border-slate-800 bg-[#0e0e18] p-3 space-y-3">
          <Row label="Intensity">
            <Range label="Effect intensity" value={Math.round((cur.intensity ?? 1) * 100)} min={0} max={100} step={1}
              onChange={(v) => patchRoot?.({ effect: { ...cur, intensity: v / 100 } }, "effect_int")} />
            <span className="re-val">{Math.round((cur.intensity ?? 1) * 100)}%</span>
          </Row>
        </div>
      )}
    </>
  );
}

function BackgroundPanel({ edit, patchRoot }: { edit: Edit; patchRoot?: (p: Partial<Edit>, key?: string) => void }) {
  const cur = edit.background || { type: "black" };
  return (
    <>
      <PanelHead title="Canvas Background" />
      <p className="re-note !mt-0">Fill letterbox borders when clips don't match the aspect ratio.</p>
      <div className="space-y-2 mt-3">
        {BACKGROUND_PRESETS.map((bg, idx) => {
          const isSelected = cur.type === bg.type && (bg.color ? cur.color === bg.color : true);
          return (
            <div key={idx} className={`flex items-center justify-between p-2.5 rounded-xl border cursor-pointer transition ${isSelected ? "border-violet-500 bg-violet-950/30" : "border-slate-800 bg-[#0e0e18] hover:border-slate-700"}`}
              onClick={() => patchRoot?.({ background: { type: bg.type, color: bg.color, gradient: bg.gradient, blurRadius: cur.blurRadius ?? 25 } }, "bg")}>
              <div>
                <div className="text-xs font-semibold text-white">{bg.label}</div>
                <div className="text-[11px] text-slate-400">{bg.desc}</div>
              </div>
              <div className="w-6 h-6 rounded-md border border-white/20 shrink-0" style={{
                background: bg.type === "blur" ? "radial-gradient(#8b5cf6, #1e1b4b)" : bg.color || (bg.gradient ? `linear-gradient(135deg, ${bg.gradient.from}, ${bg.gradient.to})` : "#000")
              }} />
            </div>
          );
        })}
      </div>
      {cur.type === "blur" && (
        <div className="mt-4 rounded-xl border border-slate-800 bg-[#0e0e18] p-3 space-y-3">
          <Row label="Blur Radius">
            <Range label="Blur radius" value={cur.blurRadius ?? 25} min={5} max={60} step={1}
              onChange={(v) => patchRoot?.({ background: { ...cur, blurRadius: v } }, "bg_blur")} />
            <span className="re-val">{cur.blurRadius ?? 25}px</span>
          </Row>
        </div>
      )}
    </>
  );
}

function SubtitlesPanel({ edit, t = 0, patchTracks, setSel }: {
  edit: Edit; t?: number; patchTracks?: (cues: TSubtitleCue[], style?: "tiktok" | "classic" | "minimal") => void; setSel: (s: Sel) => void;
}) {
  const subs = edit.tracks.subtitles || { cues: [], style: "tiktok" };
  const addCue = () => {
    const id = "sub" + Math.random().toString(36).slice(2, 9);
    const cue: TSubtitleCue = { id, start: round2(t), end: round2(t + 3), text: "New subtitle text" };
    patchTracks?.([...subs.cues, cue], subs.style);
    setSel({ kind: "subtitle", id });
  };
  const setStyle = (style: "tiktok" | "classic" | "minimal") => {
    patchTracks?.(subs.cues, style);
  };
  return (
    <>
      <PanelHead title="Subtitles & Captions" />
      <p className="re-note !mt-0">Synchronized captions with social media typography styles.</p>
      <button type="button" className="re-chip re-chip-lg w-full justify-center !my-3" onClick={addCue}>
        <Plus size={16} />Add Subtitle at Playhead ({round1(t)}s)
      </button>
      <Row label="Style">
        {(["tiktok", "classic", "minimal"] as const).map((st) => (
          <button key={st} type="button" className={`re-chip text-xs !py-1 !px-2.5 ${(subs.style || "tiktok") === st ? "is-on" : ""}`}
            onClick={() => setStyle(st)}>
            {st === "tiktok" ? "TikTok Pop" : st === "classic" ? "Netflix Classic" : "Minimal Bar"}
          </button>
        ))}
      </Row>
      <h3 className="re-sub mt-4 flex items-center justify-between">
        <span>Subtitle Cues ({subs.cues.length})</span>
      </h3>
      <div className="space-y-2 mt-2">
        {subs.cues.map((c, i) => (
          <div key={c.id} className="p-2.5 rounded-xl border border-slate-800 bg-[#0e0e18] cursor-pointer hover:border-slate-700"
            onClick={() => setSel({ kind: "subtitle", id: c.id })}>
            <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
              <span className="font-bold text-violet-400">#{i + 1} ({round1(c.start)}s - {round1(c.end)}s)</span>
              <button type="button" className="text-red-400 hover:text-red-300" onClick={(e) => { e.stopPropagation(); patchTracks?.(subs.cues.filter((x) => x.id !== c.id), subs.style); }}>
                <Trash2 size={13} />
              </button>
            </div>
            <div className="text-xs text-slate-200 truncate">{c.text}</div>
          </div>
        ))}
        {subs.cues.length === 0 && <p className="re-note text-center py-4">No subtitle cues yet. Click above to add one.</p>}
      </div>
    </>
  );
}

function SubtitleCuePanel({ cue, onUpdate, onDelete }: {
  cue: TSubtitleCue; onUpdate: (pt: Partial<TSubtitleCue>) => void; onDelete: () => void;
}) {
  return (
    <>
      <PanelHead title="Subtitle Cue" onDelete={onDelete} delLabel="Delete cue" />
      <div className="re-textarea-wrap">
        <textarea rows={3} className="re-textarea" value={cue.text}
          onChange={(e) => onUpdate({ text: e.target.value })} />
      </div>
      <Row label="Timing">
        <label className="re-mini">Start<Num label="Start (s)" value={round1(cue.start)} min={0} max={36000} step={0.1} onChange={(v) => onUpdate({ start: v, end: Math.max(cue.end, v + 0.3) })} w="w-16" /></label>
        <label className="re-mini">End<Num label="End (s)" value={round1(cue.end)} min={0.3} max={36000} step={0.1} onChange={(v) => onUpdate({ end: Math.max(v, cue.start + 0.3) })} w="w-16" /></label>
      </Row>
    </>
  );
}

function TransitionsStudioPanel({ edit, sel, setSel, patch, applyAllTransitions }: {
  edit: Edit; sel: Sel; setSel: (s: Sel) => void;
  patch: (kind: "video", id: string, p: any, key?: string) => void;
  applyAllTransitions?: (t: TransitionConfig) => void;
}) {
  const { placed } = layout(edit.tracks.video);
  if (placed.length < 2) {
    return (
      <>
        <PanelHead title="Transitions Studio" />
        <p className="re-note !mt-0">Add at least two video clips to the timeline to use transitions.</p>
      </>
    );
  }

  // Active cut is either the selected one or the first cut (clip 1 -> clip 2)
  const activeCutClip = (sel?.kind === "transition" ? edit.tracks.video.find((x) => x.id === sel.id) : null)
    || (sel?.kind === "video" && edit.tracks.video.findIndex((x) => x.id === sel.id) > 0 ? edit.tracks.video.find((x) => x.id === sel.id) : null)
    || edit.tracks.video[1];
  const activeIdx = edit.tracks.video.findIndex((x) => x.id === activeCutClip.id);
  const prevClip = edit.tracks.video[activeIdx - 1];

  return (
    <>
      <PanelHead title="Transitions Studio" />
      <div className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-violet-950/40 border border-violet-800/40 mb-3 text-xs">
        <span className="font-bold text-violet-300">Active Cut {activeIdx}</span>
        <span className="truncate text-slate-300 font-medium">{fileName(prevClip.src)} ⇄ {fileName(activeCutClip.src)}</span>
      </div>

      <TransitionPicker clip={activeCutClip} patch={(pt, key) => patch("video", activeCutClip.id, pt, key)} first={false}
        onApplyAll={applyAllTransitions ? () => applyAllTransitions(activeCutClip.transition) : undefined} />

      <h3 className="re-sub mt-4 flex items-center justify-between">
        <span>Timeline Cuts ({placed.length - 1})</span>
        <span className="text-[11px] font-normal text-slate-400">Click to inspect</span>
      </h3>
      <ul className="re-list mt-1.5 space-y-1" data-testid="transition-list">
        {placed.slice(1).map((pl, i) => {
          const isSelected = activeCutClip.id === pl.clip.id;
          const tr = pl.clip.transition;
          const isCut = tr.type === "cut";
          return (
            <li key={pl.clip.id} className={`flex items-center justify-between gap-2 p-2 rounded-lg border transition cursor-pointer ${isSelected ? "border-pink-500/80 bg-pink-950/25 ring-1 ring-pink-500/50" : "border-slate-800/80 bg-[#0e0e18] hover:border-slate-700"}`}
              onClick={() => setSel({ kind: "transition", id: pl.clip.id })}>
              <span className="font-bold text-xs text-slate-400 shrink-0">{i + 1} ⇄ {i + 2}</span>
              <span className="text-xs font-semibold text-slate-200 truncate flex-1">{TRANSITION_LABEL[tr.type] || tr.type}</span>
              <div className="flex items-center gap-1.5 shrink-0">
                {!isCut && (
                  <span className="px-1.5 py-0.5 rounded text-[11px] font-bold bg-violet-600/30 text-violet-200 border border-violet-500/30">
                    {tr.dur.toFixed(1)}s
                  </span>
                )}
                {isCut && <span className="text-[11px] text-slate-500 font-medium">Cut</span>}
              </div>
            </li>
          );
        })}
      </ul>
    </>
  );
}

export default function Inspector(p: InspectorProps) {
  const { edit, sel } = p; const fileIn = useRef<HTMLInputElement>(null);
  let body: React.ReactNode = null;
  if (sel?.kind === "text") {
    const t = edit.tracks.text.find((x) => x.id === sel.id);
    if (t) body = <TextPanel t={t} fonts={p.fonts} patch={(pt, key) => p.patch("text", t.id, pt, key)} remove={() => p.remove(sel)} />;
  } else if (sel?.kind === "element") {
    const el = edit.tracks.elements?.find((x) => x.id === sel.id);
    if (el) body = <ElementPanel el={el} project={p.project} patch={(pt, key) => p.patch("elements", el.id, pt, key)} remove={() => p.remove(sel)} />;
  } else if (sel?.kind === "subtitle") {
    const cue = edit.tracks.subtitles?.cues.find((x) => x.id === sel.id);
    if (cue) {
      body = (
        <SubtitleCuePanel cue={cue}
          onUpdate={(pt) => {
            const cues = (edit.tracks.subtitles?.cues || []).map((c) => c.id === cue.id ? { ...c, ...pt } : c);
            p.patchSubtitles?.(cues);
          }}
          onDelete={() => {
            const cues = (edit.tracks.subtitles?.cues || []).filter((c) => c.id !== cue.id);
            p.patchSubtitles?.(cues);
            p.setSel(null);
          }} />
      );
    }
  } else if (sel?.kind === "video") {
    const idx = edit.tracks.video.findIndex((x) => x.id === sel.id);
    if (idx >= 0) { const c = edit.tracks.video[idx]; body = <ClipPanel clip={c} idx={idx} srcDur={p.durs[fileUrl(p.project, c.src)]} patch={(pt, key) => p.patch("video", c.id, pt, key)} remove={() => p.remove(sel)} onApplyAll={p.applyAllTransitions ? () => p.applyAllTransitions!(c.transition) : undefined} />; }
  } else if (sel?.kind === "transition") {
    body = <TransitionsStudioPanel edit={edit} sel={sel} setSel={p.setSel} patch={(k, id, pt, key) => p.patch(k, id, pt, key)} applyAllTransitions={p.applyAllTransitions} />;
  } else if (sel?.kind === "audio") {
    const a = edit.tracks.audio.find((x) => x.id === sel.id);
    if (a) body = <AudioPanel a={a} srcDur={p.durs[fileUrl(p.project, a.src)]} patch={(pt, key) => p.patch("audio", a.id, pt, key)} remove={() => p.remove(sel)} />;
  }
  if (!body) {
    switch (p.tool) {
      case "media": body = (
        <>
          <PanelHead title="Media" />
          <p className="re-note !mt-0">Your project's video clips. Add one to the end of the timeline.</p>
          {p.clips.length === 0 && <p className="re-note">No clips yet. Generate shots first (Shots page).</p>}
          <ul className="re-list" data-testid="media-list">
            {p.clips.map((f) => (
              <li key={f}><video src={fileUrl(p.project, `clips/${f}`)} muted preload="metadata" className="re-thumb" /><span className="min-w-0 flex-1 truncate">{f}</span>
                <button type="button" className="re-chip" aria-label={`Add ${f} to the timeline`} onClick={() => p.addClip(f)}><Plus size={13} />Add</button></li>
            ))}
          </ul>
        </>); break;
      case "text": body = (
        <>
          <PanelHead title="Text" />
          <p className="re-note !mt-0">Adds text at the playhead for 3 seconds. Then drag it in the preview.</p>
          <div className="re-presets">
            <button type="button" onClick={() => p.addText("title")} className="re-preset" style={{ fontSize: 22, fontWeight: 800 }}>Add a title</button>
            <button type="button" onClick={() => p.addText("subtitle")} className="re-preset" style={{ fontSize: 15, fontWeight: 600 }}>Add a subtitle</button>
            <button type="button" onClick={() => p.addText("caption")} className="re-preset re-preset-bubble">Caption bubble</button>
          </div>
        </>); break;
      case "elements":
        body = <ElementsLibraryPanel project={p.project} addElement={p.addElement} uploadElement={p.uploadElement} uploading={p.uploading} />;
        break;

      case "filters":
        body = <FiltersPanel edit={edit} patchRoot={p.patchRoot} />;
        break;

      case "effects":
        body = <EffectsPanel edit={edit} patchRoot={p.patchRoot} />;
        break;

      case "background":
        body = <BackgroundPanel edit={edit} patchRoot={p.patchRoot} />;
        break;

      case "subtitles":
        body = <SubtitlesPanel edit={edit} t={p.t} patchTracks={p.patchSubtitles} setSel={p.setSel} />;
        break;

      case "audio": body = (
        <>
          <PanelHead title="Audio" />
          <p className="re-note !mt-0">Add background music or a voice-over (mp3, wav, m4a, aac, ogg; up to 25 MB). It is saved in the project's audio folder.</p>
          <input ref={fileIn} type="file" accept=".mp3,.wav,.m4a,.aac,.ogg,audio/*" className="sr-only" aria-label="Upload a sound file" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) p.uploadAudio(f); }} />
          <button type="button" className="re-chip re-chip-lg" disabled={p.uploading} onClick={() => fileIn.current?.click()}><Upload size={15} />{p.uploading ? "Uploading..." : "Upload sound"}</button>
        </>); break;
      case "transitions": {
        body = <TransitionsStudioPanel edit={edit} sel={sel} setSel={p.setSel} patch={(k, id, pt, key) => p.patch(k, id, pt, key)} applyAllTransitions={p.applyAllTransitions} />;
        break;
      }
      case "aspect": body = (
        <>
          <PanelHead title="Aspect Ratio" />
          <p className="re-note !mt-0">Clips that do not match get black bars.</p>
          <div className="re-grid-btns" role="group" aria-label="Aspect ratio">
            {([["9:16", "Vertical 9:16"], ["16:9", "Wide 16:9"], ["1:1", "Square 1:1"]] as const).map(([a, l]) => <button key={a} type="button" aria-pressed={edit.aspect === a} className={`re-chip ${edit.aspect === a ? "is-on" : ""}`} onClick={() => p.setAspect(a)}>{l}</button>)}
          </div>
        </>); break;
      default: {
        const name = String(p.tool || "Properties");
        body = (
          <>
            <PanelHead title={name[0].toUpperCase() + name.slice(1)} />
            <div className="re-soon"><span>Coming soon</span><p>This tool is not in this version yet.</p></div>
          </>
        );
        break;
      }
    }
  }
  return <aside className="re-card re-inspector" aria-label="Properties" data-testid="inspector">{body}</aside>;
}
