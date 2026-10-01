import { useRef } from "react";
import { AlignCenter, AlignJustify, AlignLeft, AlignRight, Bold, CaseSensitive, ChevronDown, ChevronUp, Clock, Film, Italic, Music, Plus, Trash2, Underline, Upload } from "lucide-react";
import type { AClip, Aspect, Edit, FontInfo, Sel, TText, Tool, TransitionType, VClip } from "./types";
import { MAX_TEXT, TRANSITION_GROUPS } from "./types";
import { clamp, fileName, layout, round1, round2 } from "./time";
import { fileUrl } from "../api";

const TRANSITION_LABEL: Record<string, string> = Object.fromEntries(TRANSITION_GROUPS.flatMap((g) => g.items).map((t) => [t.id, t.label]));
const SWATCH = ["#a855f7", "#ffffff", "#ff2d95", "#111827"];

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
      {allowNone && <button type="button" aria-label={`${label}: none`} aria-pressed={value === null} className={`re-swatch re-swatch-none ${value === null ? "is-on" : ""}`} onClick={() => onChange(null)} />}
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

function TransitionPicker({ clip, patch, first }: { clip: VClip; patch: (p: Partial<VClip>) => void; first: boolean }) {
  return (
    <>
      <div className="re-selwrap" style={{ marginBottom: 8 }}>
        <select aria-label="Transition into this clip" className="re-select" disabled={first} value={clip.transition.type} onChange={(e) => patch({ transition: { ...clip.transition, type: e.target.value as TransitionType } })}>
          {TRANSITION_GROUPS.map((g) => <optgroup key={g.group} label={g.group}>{g.items.map((tr) => <option key={tr.id} value={tr.id}>{tr.label}</option>)}</optgroup>)}
        </select><ChevronDown size={15} />
      </div>
      <div className="re-grid-btns" role="group" aria-label="Popular transitions">
        {["cut", "crossfade", "dissolve", "fade", "slideleft", "circleopen", "pixelize", "zoomin"].map((id) => <button key={id} type="button" disabled={first} aria-pressed={clip.transition.type === id} className={`re-chip ${clip.transition.type === id ? "is-on" : ""}`}
          onClick={() => patch({ transition: { ...clip.transition, type: id as TransitionType } })}>{TRANSITION_LABEL[id]}</button>)}
      </div>
      <Row label="Length"><Range label="Transition length" value={clip.transition.dur} min={0.1} max={2} step={0.1} onChange={(v) => patch({ transition: { ...clip.transition, dur: round1(v) } })} /><span className="re-val">{clip.transition.dur.toFixed(1)}s</span></Row>
      <p className="re-note">{first ? "The first clip has nothing before it." : "The preview shows a cut. The exported video has the transition."}</p>
    </>
  );
}

function ClipPanel({ clip, idx, patch, remove, srcDur }: { clip: VClip; idx: number; patch: (p: Partial<VClip>, key?: string) => void; remove: () => void; srcDur?: number }) {
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
      <TransitionPicker clip={clip} patch={patch} first={idx === 0} />
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
  elements: "Stickers and shapes", filters: "Colour filters", effects: "Visual effects", subtitles: "Automatic captions", background: "Background colour and blur",
};

export interface InspectorProps {
  project: string; edit: Edit; sel: Sel; tool: Tool; fonts: FontInfo[]; clips: string[]; durs: Record<string, number>;
  patch: (kind: "video" | "text" | "audio", id: string, p: any, key?: string) => void; remove: (s: NonNullable<Sel>) => void;
  addClip: (file: string) => void; addText: (preset: "title" | "subtitle" | "caption") => void; uploadAudio: (f: File) => void; setAspect: (a: Aspect) => void; uploading: boolean;
}

export default function Inspector(p: InspectorProps) {
  const { edit, sel } = p; const fileIn = useRef<HTMLInputElement>(null);
  let body: React.ReactNode = null;
  if (sel?.kind === "text") {
    const t = edit.tracks.text.find((x) => x.id === sel.id);
    if (t) body = <TextPanel t={t} fonts={p.fonts} patch={(pt, key) => p.patch("text", t.id, pt, key)} remove={() => p.remove(sel)} />;
  } else if (sel?.kind === "video") {
    const idx = edit.tracks.video.findIndex((x) => x.id === sel.id);
    if (idx >= 0) { const c = edit.tracks.video[idx]; body = <ClipPanel clip={c} idx={idx} srcDur={p.durs[fileUrl(p.project, c.src)]} patch={(pt, key) => p.patch("video", c.id, pt, key)} remove={() => p.remove(sel)} />; }
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
      case "audio": body = (
        <>
          <PanelHead title="Audio" />
          <p className="re-note !mt-0">Add background music or a voice-over (mp3, wav, m4a, aac, ogg; up to 25 MB). It is saved in the project's audio folder.</p>
          <input ref={fileIn} type="file" accept=".mp3,.wav,.m4a,.aac,.ogg,audio/*" className="sr-only" aria-label="Upload a sound file" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) p.uploadAudio(f); }} />
          <button type="button" className="re-chip re-chip-lg" disabled={p.uploading} onClick={() => fileIn.current?.click()}><Upload size={15} />{p.uploading ? "Uploading..." : "Upload sound"}</button>
        </>); break;
      case "transitions": {
        const { placed } = layout(edit.tracks.video);
        body = (
          <>
            <PanelHead title="Transitions" />
            <p className="re-note !mt-0">Pick how each clip comes in. The preview shows a cut; the export has the transition.</p>
            {placed.length < 2 && <p className="re-note">Add at least two clips to use transitions.</p>}
            <ul className="re-list" data-testid="transition-list">
              {placed.slice(1).map((pl, i) => (
                <li key={pl.clip.id}><span className="re-plabel !w-auto shrink-0">{i + 1} <Clock size={11} className="inline" /> {i + 2}</span>
                  <div className="re-selwrap flex-1"><select className="re-select" aria-label={`Transition into clip ${i + 2}`} value={pl.clip.transition.type} onChange={(e) => p.patch("video", pl.clip.id, { transition: { ...pl.clip.transition, type: e.target.value } })}>
                    {TRANSITION_GROUPS.map((g) => <optgroup key={g.group} label={g.group}>{g.items.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}</optgroup>)}</select><ChevronDown size={15} /></div></li>
              ))}
            </ul>
          </>); break;
      }
      case "aspect": body = (
        <>
          <PanelHead title="Aspect Ratio" />
          <p className="re-note !mt-0">Clips that do not match get black bars.</p>
          <div className="re-grid-btns" role="group" aria-label="Aspect ratio">
            {([["9:16", "Vertical 9:16"], ["16:9", "Wide 16:9"], ["1:1", "Square 1:1"]] as const).map(([a, l]) => <button key={a} type="button" aria-pressed={edit.aspect === a} className={`re-chip ${edit.aspect === a ? "is-on" : ""}`} onClick={() => p.setAspect(a)}>{l}</button>)}
          </div>
        </>); break;
      default: body = (
        <>
          <PanelHead title={p.tool[0].toUpperCase() + p.tool.slice(1)} />
          <div className="re-soon"><span>Coming soon</span><p>{SOON[p.tool] || "This tool"} is not in this version yet.</p></div>
        </>);
    }
  }
  return <aside className="re-card re-inspector" aria-label="Properties" data-testid="inspector">{body}</aside>;
}
