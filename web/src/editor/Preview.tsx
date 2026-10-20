import { useEffect, useRef, useState } from "react";
import { fileUrl } from "../api";
import type { Edit, Sel, TText, TElement, TFilter, TEffect, TBackgroundConfig, TSubtitlesConfig } from "./types";
import { layout, clamp, round2 } from "./time";
import { rememberDuration } from "./media";

/** The colour grade as a CSS filter chain (mirror of `_filter_chain` in aistudio/editor.py so the preview matches the export). */
export function filterCss(f?: TFilter): string {
  if (!f || f.id === "none") return "";
  const k = clamp(f.intensity ?? 1, 0, 1); if (k <= 0) return "";
  const q = (v: number) => v.toFixed(3);
  switch (f.id) {
    case "cinema": return `contrast(${q(1 + 0.12 * k)}) saturate(${q(1 + 0.18 * k)}) sepia(${q(0.12 * k)})`;
    case "teal_orange": return `sepia(${q(0.35 * k)}) hue-rotate(${(-14 * k).toFixed(1)}deg) saturate(${q(1 + 0.35 * k)}) contrast(${q(1 + 0.06 * k)})`;
    case "vintage": return `contrast(${q(1 - 0.1 * k)}) saturate(${q(1 - 0.25 * k)}) sepia(${q(0.35 * k)}) brightness(${q(1 + 0.04 * k)})`;
    case "noir": return `saturate(${q(1 - k)}) contrast(${q(1 + 0.25 * k)})`;
    case "vibrant": return `saturate(${q(1 + 0.4 * k)}) contrast(${q(1 + 0.05 * k)})`;
    case "cyberpunk": return `sepia(${q(0.25 * k)}) hue-rotate(${(60 * k).toFixed(1)}deg) saturate(${q(1 + 0.5 * k)}) contrast(${q(1 + 0.08 * k)})`;
    case "warm": return `sepia(${q(0.3 * k)}) saturate(${q(1 + 0.1 * k)}) brightness(${q(1 + 0.05 * k)})`;
    default: return "";
  }
}

const FX_BASE: React.CSSProperties = { position: "absolute", inset: 0, zIndex: 15, pointerEvents: "none" };
const GRAIN_SVG = "<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='3' stitchTiles='stitch'/></filter><rect width='160' height='160' filter='url(#n)' opacity='0.6'/></svg>";
const GRAIN_URL = `url("data:image/svg+xml,${encodeURIComponent(GRAIN_SVG)}")`;

/** Live vignette / grain / glitch overlay (the export uses ffmpeg's vignette and noise filters). */
function EffectOverlay({ effect }: { effect?: TEffect }) {
  if (!effect || effect.id === "none") return null;
  const k = clamp(effect.intensity ?? 1, 0, 1); if (k <= 0) return null;
  if (effect.id === "vignette") return <div data-testid="fx-vignette" aria-hidden style={{ ...FX_BASE, background: `radial-gradient(ellipse at center, rgba(0,0,0,0) ${Math.round(62 - 22 * k)}%, rgba(0,0,0,${(0.8 * k).toFixed(3)}) 100%)` }} />;
  if (effect.id === "grain") return <div data-testid="fx-grain" aria-hidden style={{ ...FX_BASE, opacity: 0.4 * k, mixBlendMode: "overlay", backgroundImage: GRAIN_URL, backgroundSize: "160px 160px" }} />;
  if (effect.id === "glitch") return <div data-testid="fx-glitch" aria-hidden style={{ ...FX_BASE, opacity: 0.5 * k, mixBlendMode: "overlay", background: "repeating-linear-gradient(0deg, rgba(255,255,255,.14) 0 2px, rgba(0,0,0,0) 2px 5px)" }} />;
  return null;
}

/** Paints what sits behind letterboxed media: flat colour, gradient, or a softened cover-fill of the live clip. */
function BackgroundCanvas({ bg, video, w, h }: { bg: TBackgroundConfig; video?: HTMLVideoElement; w: number; h: number }) {
  const ref = useRef<HTMLCanvasElement>(null); const tiny = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    const c = ref.current; if (!c || bg.type === "black") return;
    const W = Math.max(1, Math.round(w)), H = Math.max(1, Math.round(h));
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const pw = Math.max(1, Math.round(W * dpr)), ph = Math.max(1, Math.round(H * dpr));
    if (c.width !== pw || c.height !== ph) { c.width = pw; c.height = ph; }
    const g = c.getContext("2d"); if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    if (bg.type === "color") { g.fillStyle = bg.color || "#0b0c16"; g.fillRect(0, 0, W, H); return; }
    if (bg.type === "gradient") {
      const gr = g.createLinearGradient(0, 0, W, H);
      gr.addColorStop(0, bg.gradient?.from || "#2e0854"); gr.addColorStop(1, bg.gradient?.to || "#0f051d");
      g.fillStyle = gr; g.fillRect(0, 0, W, H); return;
    }
    // blur: downscale the live frame, then scale it back up (soft focus without needing ctx.filter)
    const r = clamp(Math.round(bg.blurRadius ?? 25), 1, 100);
    const f = clamp(1 + r / 4, 3, 30);
    const tw = Math.max(1, Math.round(W / f)), th = Math.max(1, Math.round(H / f));
    if (!tiny.current) tiny.current = document.createElement("canvas");
    const tc = tiny.current; tc.width = tw; tc.height = th;
    const tg = tc.getContext("2d"); if (!tg) return;
    let drew = false;
    if (video && video.videoWidth > 0) {
      try {
        const s = Math.max(tw / video.videoWidth, th / video.videoHeight);
        const dw = video.videoWidth * s, dh = video.videoHeight * s;
        tg.clearRect(0, 0, tw, th); tg.drawImage(video, (tw - dw) / 2, (th - dh) / 2, dw, dh); drew = true;
      } catch { drew = false; }
    }
    if (!drew) { g.fillStyle = "#000"; g.fillRect(0, 0, W, H); return; }
    g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high";
    const s2 = Math.max(W / tw, H / th); const dw2 = tw * s2, dh2 = th * s2;
    g.drawImage(tc, (W - dw2) / 2, (H - dh2) / 2, dw2, dh2);
  });
  if (bg.type === "black") return null;
  return <canvas ref={ref} data-testid="bg-canvas" aria-hidden style={{ position: "absolute", inset: 0, width: "100%", height: "100%", zIndex: 0, pointerEvents: "none" }} />;
}

/** The caption showing at time `t` (or the one picked in the timeline, as a ghost), shaped like the export's subtitle styles. */
function SubtitleOverlay({ subs, t, frameW, selected, onSelect }: {
  subs: TSubtitlesConfig; t: number; frameW: number; selected?: string; onSelect: (id: string) => void;
}) {
  const live = subs.cues.find((c) => t >= c.start && t < c.end);
  const cue = live || (selected ? subs.cues.find((c) => c.id === selected) : undefined);
  if (!cue) return null;
  const k = frameW / 1080; const fs = (subs.size ?? 46) * k;
  const color = subs.color || "#ffffff"; const shadowColor = "rgba(0,0,0,.85)";
  const base: React.CSSProperties = {
    position: "absolute", left: "50%", top: `${(subs.y ?? 0.86) * 100}%`, transform: "translate(-50%, -50%)",
    zIndex: 16, maxWidth: "86%", textAlign: "center", whiteSpace: "pre-wrap", lineHeight: 1.25, opacity: live ? 1 : 0.75,
    fontFamily: `"${subs.font || "Poppins"}", system-ui, sans-serif`, fontSize: fs, color,
    pointerEvents: "auto", cursor: "pointer", userSelect: "none",
  };
  const style = subs.style || "classic";
  let box: React.CSSProperties;
  if (style === "tiktok") {
    box = { ...base, fontWeight: 800, background: subs.bg || "#000000", padding: `${0.16 * fs}px ${0.5 * fs}px`, borderRadius: 999, letterSpacing: "0.01em", textShadow: `0 0 ${0.25 * fs}px rgba(255,45,149,.55)` };
  } else if (style === "minimal") {
    box = { ...base, fontWeight: 400, background: subs.bg || "rgba(11,12,22,.72)", padding: `${0.14 * fs}px ${0.44 * fs}px`, borderRadius: 0.2 * fs };
  } else {
    box = { ...base, fontWeight: 700, background: subs.bg || "transparent", padding: subs.bg ? `${0.14 * fs}px ${0.44 * fs}px` : `0 ${0.3 * fs}px`, borderRadius: 0.18 * fs,
      textShadow: `0 ${0.04 * fs}px ${0.18 * fs}px ${shadowColor}, 0 0 ${0.22 * fs}px ${shadowColor}` };
  }
  return <div data-testid="subtitle-cue" style={box} onPointerDown={(e) => { e.stopPropagation(); onSelect(cue.id); }}>{cue.text}</div>;
}


/** Fraction of the 1080-wide design canvas: text size 56 is 56/1080 of the frame width (the export uses the same rule). */
export const textMetrics = (t: TText, frameW: number) => {
  const k = frameW / 1080; const fs = t.size * k;
  return {
    fs,
    style: {
      fontFamily: `"${t.font}", system-ui, sans-serif`, fontSize: fs, fontWeight: t.weight, fontStyle: t.italic ? "italic" : "normal", textDecoration: t.underline ? "underline" : "none",
      textTransform: t.caps ? "uppercase" : "none", color: t.color, background: t.bg ?? "transparent", padding: t.bg ? `${0.2 * fs}px ${0.4 * fs}px` : 0, borderRadius: 0.28 * fs,
      lineHeight: 1.3, whiteSpace: "pre", textAlign: t.align === "justify" ? "center" : t.align, opacity: t.opacity,
      textShadow: t.shadow.on ? `0 ${0.04 * fs}px ${(2 * t.shadow.blur * k) / 3}px ${t.shadow.color}` : "none",
    } as React.CSSProperties,
  };
};

function TextOverlay({ t, frameW, frame, selected, ghost, onSelect, onChange }: {
  t: TText; frameW: number; frame: React.RefObject<HTMLDivElement>; selected: boolean; ghost: boolean; onSelect: () => void; onChange: (p: Partial<TText>, key: string) => void;
}) {
  const { style } = textMetrics(t, frameW); const box = useRef<HTMLDivElement>(null);
  const drag = (e: React.PointerEvent) => {
    e.preventDefault(); e.stopPropagation(); onSelect();
    const r = frame.current!.getBoundingClientRect(); const x0 = e.clientX, y0 = e.clientY, bx = t.x, by = t.y;
    const mv = (ev: PointerEvent) => onChange({ x: clamp(bx + (ev.clientX - x0) / r.width, 0, 1), y: clamp(by + (ev.clientY - y0) / r.height, 0, 1) }, `move${t.id}`);
    const up = () => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); };
    addEventListener("pointermove", mv); addEventListener("pointerup", up);
  };
  const resize = (e: React.PointerEvent) => {
    e.preventDefault(); e.stopPropagation();
    const b = box.current!.getBoundingClientRect(); const cx = b.left + b.width / 2, cy = b.top + b.height / 2; const d0 = Math.hypot(e.clientX - cx, e.clientY - cy) || 1; const s0 = t.size;
    const mv = (ev: PointerEvent) => onChange({ size: Math.round(clamp((s0 * Math.hypot(ev.clientX - cx, ev.clientY - cy)) / d0, 8, 300)) }, `size${t.id}`);
    const up = () => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); };
    addEventListener("pointermove", mv); addEventListener("pointerup", up);
  };
  const H = [["0%", "0%"], ["50%", "0%"], ["100%", "0%"], ["0%", "50%"], ["100%", "50%"], ["0%", "100%"], ["50%", "100%"], ["100%", "100%"]];
  return (
    <div ref={box} data-testid={`overlay-${t.id}`} className={`re-overlay ${selected ? "is-sel" : ""}`} onPointerDown={drag}
      style={{ left: `${t.x * 100}%`, top: `${t.y * 100}%`, opacity: ghost ? 0.75 : 1, zIndex: selected ? 30 : 20 }}>
      <div style={style} data-testid="overlay-text">{t.caps ? t.text.toUpperCase() : t.text}</div>
      {selected && H.map(([l, tp], i) => <span key={i} className="re-handle" style={{ left: l, top: tp }} onPointerDown={resize} aria-hidden />)}
    </div>
  );
}

function ElementOverlay({ el, project, frameW, frame, selected, ghost, onSelect, onChange }: {
  el: TElement; project: string; frameW: number; frame: React.RefObject<HTMLDivElement>; selected: boolean; ghost: boolean; onSelect: () => void; onChange: (p: Partial<TElement>, key: string) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [loadError, setLoadError] = useState(false);
  const drag = (e: React.PointerEvent) => {
    e.preventDefault(); e.stopPropagation(); onSelect();
    const r = frame.current!.getBoundingClientRect(); const x0 = e.clientX, y0 = e.clientY, bx = el.x, by = el.y;
    const mv = (ev: PointerEvent) => onChange({ x: clamp(bx + (ev.clientX - x0) / r.width, 0, 1), y: clamp(by + (ev.clientY - y0) / r.height, 0, 1) }, `move${el.id}`);
    const up = () => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); };
    addEventListener("pointermove", mv); addEventListener("pointerup", up);
  };
  const resize = (e: React.PointerEvent) => {
    e.preventDefault(); e.stopPropagation();
    const b = box.current!.getBoundingClientRect(); const cx = b.left + b.width / 2, cy = b.top + b.height / 2;
    const d0 = Math.hypot(e.clientX - cx, e.clientY - cy) || 1; const s0 = el.scale;
    const mv = (ev: PointerEvent) => {
      const dist = Math.hypot(ev.clientX - cx, ev.clientY - cy);
      const newScale = clamp((s0 * dist) / d0, 0.05, 3.0);
      onChange({ scale: round2(newScale) }, `scale${el.id}`);
    };
    const up = () => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); };
    addEventListener("pointermove", mv); addEventListener("pointerup", up);
  };
  const H = [["0%", "0%"], ["50%", "0%"], ["100%", "0%"], ["0%", "50%"], ["100%", "50%"], ["0%", "100%"], ["50%", "100%"], ["100%", "100%"]];
  const curW = frame.current?.clientWidth || frameW || 360;
  const targetW = Math.max(24, Math.round(curW * (el.scale || 0.35)));
  const cleanSrc = el.src.replace(/^\/+/, "");
  const resolvedSrc = cleanSrc.startsWith("elements/") || cleanSrc.startsWith("stills/") ? cleanSrc : `elements/${cleanSrc}`;
  return (
    <div ref={box} data-testid={`overlay-el-${el.id}`} className={`re-overlay ${selected ? "is-sel" : ""}`} onPointerDown={drag}
      style={{ left: `${el.x * 100}%`, top: `${el.y * 100}%`, opacity: ghost ? 0.75 : (el.opacity ?? 1), zIndex: selected ? 30 : 20 }}>
      {!loadError ? (
        <img
          src={fileUrl(project, resolvedSrc)}
          alt={el.name || "element"}
          draggable={false}
          onError={() => setLoadError(true)}
          style={{ width: targetW, maxWidth: "none", height: "auto", display: "block", pointerEvents: "none", userSelect: "none" }}
        />
      ) : (
        <div style={{ width: targetW, minHeight: 48, background: "rgba(236,72,153,0.35)", border: "2px dashed #ec4899", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", padding: 8, color: "#fff", fontSize: 11, fontWeight: 700 }}>
          {el.name || "Element overlay"}
        </div>
      )}
      {selected && H.map(([l, tp], i) => <span key={i} className="re-handle" style={{ left: l, top: tp }} onPointerDown={resize} aria-hidden />)}
    </div>
  );
}

function getIncomingStyle(type: string, prog: number, dir?: string): React.CSSProperties {
  const zIndex = 3;
  if (type === "wipe" || type === "wiperight" || type === "wipeup" || type === "wipedown" || type === "wipetl") {
    let cp = `inset(0 0 0 ${(1 - prog) * 100}%)`;
    if (type === "wiperight" || dir === "right") cp = `inset(0 ${(1 - prog) * 100}% 0 0)`;
    else if (type === "wipeup" || dir === "up") cp = `inset(0 0 ${(1 - prog) * 100}% 0)`;
    else if (type === "wipedown" || dir === "down") cp = `inset(${(1 - prog) * 100}% 0 0 0)`;
    else if (type === "wipetl" || dir === "tl") cp = `polygon(0 0, ${prog * 200}% 0, 0 ${prog * 200}%)`;
    return { opacity: 1, clipPath: cp, zIndex };
  }
  if (type.startsWith("slide") || type.startsWith("smooth") || type.startsWith("cover")) {
    let tx = `${(1 - prog) * 100}%`, ty = "0%";
    if (type.includes("right") || dir === "right") tx = `${-(1 - prog) * 100}%`;
    else if (type.includes("up") || dir === "up") { tx = "0%"; ty = `${(1 - prog) * 100}%`; }
    else if (type.includes("down") || dir === "down") { tx = "0%"; ty = `${-(1 - prog) * 100}%`; }
    return { opacity: 1, transform: `translate3d(${tx}, ${ty}, 0)`, zIndex };
  }
  if (type.startsWith("reveal") || type === "circleclose") return { opacity: 1, zIndex: 1 };
  if (type === "circleopen") return { opacity: 1, clipPath: `circle(${prog * 75}% at 50% 50%)`, zIndex };
  if (type === "vertopen") return { opacity: 1, clipPath: `inset(0 ${(1 - prog) * 50}% 0 ${(1 - prog) * 50}%)`, zIndex };
  if (type === "horzopen") return { opacity: 1, clipPath: `inset(${(1 - prog) * 50}% 0 ${(1 - prog) * 50}% 0)`, zIndex };
  if (type === "diagtl") return { opacity: 1, clipPath: `polygon(0 0, ${prog * 200}% 0, 0 ${prog * 200}%)`, zIndex };
  if (type === "fade" || type === "fadefast" || type === "fadeslow") {
    return { opacity: prog < 0.5 ? 0 : (prog - 0.5) * 2, zIndex };
  }
  if (type === "fadewhite") {
    return { opacity: prog < 0.5 ? 0 : (prog - 0.5) * 2, filter: `brightness(${1 + (1 - Math.abs(prog - 0.5) * 2) * 3})`, zIndex };
  }
  if (type === "fadegrays") {
    return { opacity: prog < 0.5 ? 0 : (prog - 0.5) * 2, filter: `grayscale(${1 - Math.abs(prog - 0.5) * 2})`, zIndex };
  }
  if (type === "zoomin") return { opacity: prog, transform: `scale(${0.75 + 0.25 * prog})`, zIndex };
  return { opacity: prog, zIndex };
}

function getOutgoingStyle(type: string, prog: number, dir?: string): React.CSSProperties {
  const zIndex = 2;
  if (type.startsWith("slide") || type.startsWith("smooth")) {
    let tx = `${-prog * 100}%`, ty = "0%";
    if (type.includes("right") || dir === "right") tx = `${prog * 100}%`;
    else if (type.includes("up") || dir === "up") { tx = "0%"; ty = `${-prog * 100}%`; }
    else if (type.includes("down") || dir === "down") { tx = "0%"; ty = `${prog * 100}%`; }
    return { opacity: 1, transform: `translate3d(${tx}, ${ty}, 0)`, zIndex };
  }
  if (type.startsWith("cover") || type.startsWith("wipe") || type === "circleopen" || type === "vertopen" || type === "horzopen" || type === "diagtl") {
    return { opacity: 1, zIndex: 1 };
  }
  if (type.startsWith("reveal")) {
    let tx = `${-prog * 100}%`, ty = "0%";
    if (type.includes("right") || dir === "right") tx = `${prog * 100}%`;
    else if (type.includes("up") || dir === "up") { tx = "0%"; ty = `${-prog * 100}%`; }
    else if (type.includes("down") || dir === "down") { tx = "0%"; ty = `${prog * 100}%`; }
    return { opacity: 1, transform: `translate3d(${tx}, ${ty}, 0)`, zIndex: 3 };
  }
  if (type === "circleclose") return { opacity: 1, clipPath: `circle(${(1 - prog) * 75}% at 50% 50%)`, zIndex: 3 };
  if (type === "fade" || type === "fadefast" || type === "fadeslow") {
    return { opacity: prog < 0.5 ? 1 - prog * 2 : 0, zIndex };
  }
  if (type === "fadewhite") {
    return { opacity: prog < 0.5 ? 1 - prog * 2 : 0, filter: `brightness(${1 + (1 - Math.abs(prog - 0.5) * 2) * 3})`, zIndex };
  }
  if (type === "fadegrays") {
    return { opacity: prog < 0.5 ? 1 - prog * 2 : 0, filter: `grayscale(${1 - Math.abs(prog - 0.5) * 2})`, zIndex };
  }
  if (type === "zoomin") return { opacity: 1 - prog, transform: `scale(${1 + 0.2 * prog})`, zIndex };
  return { opacity: 1 - prog, zIndex };
}

function getClipVideoStyle(p: any, placed: any[], t: number, activeId?: string): React.CSSProperties {
  const idx = placed.findIndex((x) => x.clip.id === p.clip.id);
  const nextP = placed[idx + 1];
  if (p.td > 0 && t >= p.start && t < p.start + p.td) {
    const prog = clamp((t - p.start) / p.td, 0, 1);
    const tr = p.clip.transition;
    return getIncomingStyle(tr.type, prog, tr.direction);
  }
  if (nextP && nextP.td > 0 && t >= nextP.start && t < nextP.start + nextP.td) {
    const prog = clamp((t - nextP.start) / nextP.td, 0, 1);
    const tr = nextP.clip.transition;
    return getOutgoingStyle(tr.type, prog, tr.direction);
  }
  const isCurrent = activeId === p.clip.id;
  return { opacity: isCurrent ? 1 : 0, zIndex: isCurrent ? 2 : 1, pointerEvents: isCurrent ? "auto" : "none" };
}

/** The video frame: plays the clips in order with live transition crossfades, overlays, and audio. */
export default function Preview({ project, edit, t, playing, muted, sel, setSel, onText, onElement, fit }: {
  project: string; edit: Edit; t: number; playing: boolean; muted: boolean; sel: Sel; setSel: (s: Sel) => void;
  onText: (id: string, p: Partial<TText>, key: string) => void; onElement: (id: string, p: Partial<TElement>, key: string) => void; fit: "fit" | "fill";
}) {

  const frame = useRef<HTMLDivElement>(null); const [frameW, setFrameW] = useState(360); const [frameH, setFrameH] = useState(640);
  const vids = useRef(new Map<string, HTMLVideoElement>()); const auds = useRef(new Map<string, HTMLAudioElement>());
  useEffect(() => {
    const el = frame.current; if (!el) return;
    const read = () => { setFrameW(el.clientWidth || 360); setFrameH(el.clientHeight || 640); };
    const ro = new ResizeObserver(read); ro.observe(el); read(); return () => ro.disconnect();
  }, [edit.aspect]);

  const { placed, total } = layout(edit.tracks.video);
  let a = placed.findIndex((p, i) => t >= p.start - 1e-6 && (t < p.end - 1e-6 || i === placed.length - 1));
  for (let i = placed.length - 1; i >= 0; i--) if (t >= placed[i].start - 1e-6 && t < placed[i].end - 1e-6) { a = i; break; }
  if (t >= total && placed.length) a = placed.length - 1;
  const active = a >= 0 ? placed[a] : undefined;
  const win = placed.filter((_, i) => a >= 0 && i >= a - 1 && i <= a + 2);

  useEffect(() => {
    vids.current.forEach((v, id) => {
      const p = placed.find((x) => x.clip.id === id); if (!p) return;
      const idx = placed.findIndex((x) => x.clip.id === id);
      const nextP = placed[idx + 1];
      const inIncomingTrans = p.td > 0 && t >= p.start && t < p.start + p.td;
      const inOutgoingTrans = nextP && nextP.td > 0 && t >= nextP.start && t < nextP.start + nextP.td;
      const isActive = active?.clip.id === id || inIncomingTrans || inOutgoingTrans;

      v.muted = muted; v.volume = clamp(p.clip.volume, 0, 1);
      if (isActive) {
        const target = p.clip.in + clamp(t - p.start, 0, p.dur - 0.02);
        if (!playing || Math.abs(v.currentTime - target) > 0.3) { try { v.currentTime = target; } catch { /* not ready */ } }
        if (playing && t < total) v.play().catch(() => {}); else v.pause();
      } else { v.pause(); }
    });
    auds.current.forEach((el, id) => {
      const c = edit.tracks.audio.find((x) => x.id === id); if (!c) return;
      const d = c.out - c.in; const rel = t - c.start; const inside = rel >= 0 && rel < d;
      el.muted = muted;
      let vol = c.volume; if (inside) { if (c.fadeIn && rel < c.fadeIn) vol *= rel / c.fadeIn; if (c.fadeOut && rel > d - c.fadeOut) vol *= (d - rel) / c.fadeOut; }
      el.volume = clamp(vol, 0, 1);
      if (inside) {
        const target = c.in + rel;
        if (!playing || Math.abs(el.currentTime - target) > 0.3) { try { el.currentTime = target; } catch { /* not ready */ } }
        if (playing) el.play().catch(() => {}); else el.pause();
      } else el.pause();
    });
  });

  const ar = edit.aspect.replace(":", " / ");
  const grade = filterCss(edit.filter);
  const fx = edit.effect && edit.effect.id !== "none" && (edit.effect.intensity ?? 1) > 0 ? edit.effect : undefined;
  const fxBlur = fx?.id === "blur" ? ` blur(${(4 * clamp(fx.intensity ?? 1, 0, 1)).toFixed(2)}px)` : "";
  const videoFilter = (grade + fxBlur).trim() || undefined;
  const hasBg = !!edit.background && edit.background.type !== "black";
  const bgVideo = active ? vids.current.get(active.clip.id) : undefined;
  const cue = edit.tracks.subtitles?.cues.find((c) => t >= c.start && t < c.end);
  const selCue = sel?.kind === "subtitle" ? edit.tracks.subtitles?.cues.find((c) => c.id === sel.id) : undefined;
  return (
    <div className="re-stage" onPointerDown={() => setSel(null)}>
      <div ref={frame} className={`re-frame ${fit === "fill" ? "is-fill" : ""}`} style={{ aspectRatio: ar }} data-testid="preview-frame" data-aspect={edit.aspect}>
        {edit.background && hasBg && <BackgroundCanvas bg={edit.background} video={bgVideo} w={frameW} h={frameH} />}
        {win.map((p) => (
          <video key={p.clip.id} data-testid={`pv-${p.clip.id}`} ref={(el) => { if (el) vids.current.set(p.clip.id, el); else vids.current.delete(p.clip.id); }}
            src={fileUrl(project, p.clip.src)} preload="auto" playsInline className="re-video"
            style={{ ...getClipVideoStyle(p, placed, t, active?.clip.id), filter: videoFilter, ...(hasBg ? { background: "transparent" } : {}) }}
            onLoadedMetadata={(e) => { const v = e.currentTarget; rememberDuration(fileUrl(project, p.clip.src), v.duration); if (active?.clip.id !== p.clip.id) v.currentTime = p.clip.in; }} />
        ))}
        {!placed.length && <div className="re-empty">Add a clip from Media to start</div>}
        <EffectOverlay effect={fx} />
        {edit.tracks.subtitles && (cue || selCue) && (
          <SubtitleOverlay subs={edit.tracks.subtitles} t={t} frameW={frameW} selected={sel?.kind === "subtitle" ? sel.id : undefined}
            onSelect={(id) => setSel({ kind: "subtitle", id })} />
        )}
        {edit.tracks.audio.map((c) => (
          <audio key={c.id} preload="auto" ref={(el) => { if (el) auds.current.set(c.id, el); else auds.current.delete(c.id); }} src={fileUrl(project, c.src)} />
        ))}
        {(edit.tracks.elements || []).map((el) => {
          const on = t >= el.start && t < el.end; const isSel = sel?.kind === "element" && sel.id === el.id;
          if (!on && !isSel) return null;
          return <ElementOverlay key={el.id} el={el} project={project} frameW={frameW} frame={frame} selected={isSel} ghost={!on} onSelect={() => setSel({ kind: "element", id: el.id })} onChange={(p, key) => onElement(el.id, p, key)} />;
        })}
        {edit.tracks.text.map((tx) => {
          const on = t >= tx.start && t < tx.end; const isSel = sel?.kind === "text" && sel.id === tx.id;
          if (!on && !isSel) return null;
          return <TextOverlay key={tx.id} t={tx} frameW={frameW} frame={frame} selected={isSel} ghost={!on} onSelect={() => setSel({ kind: "text", id: tx.id })} onChange={(p, key) => onText(tx.id, p, key)} />;
        })}
      </div>
    </div>
  );
}
