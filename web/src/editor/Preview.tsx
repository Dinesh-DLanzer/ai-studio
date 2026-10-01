import { useEffect, useRef, useState } from "react";
import { fileUrl } from "../api";
import type { Edit, Sel, TText } from "./types";
import { layout, clamp } from "./time";
import { rememberDuration } from "./media";

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
      style={{ left: `${t.x * 100}%`, top: `${t.y * 100}%`, opacity: ghost ? 0.35 : 1 }}>
      <div style={style} data-testid="overlay-text">{t.caps ? t.text.toUpperCase() : t.text}</div>
      {selected && H.map(([l, tp], i) => <span key={i} className="re-handle" style={{ left: l, top: tp }} onPointerDown={resize} aria-hidden />)}
    </div>
  );
}

/** The video frame: plays the clips in order (a hard cut at each boundary; transitions appear in the export), the music, and the text overlays. */
export default function Preview({ project, edit, t, playing, muted, sel, setSel, onText, fit }: {
  project: string; edit: Edit; t: number; playing: boolean; muted: boolean; sel: Sel; setSel: (s: Sel) => void;
  onText: (id: string, p: Partial<TText>, key: string) => void; fit: "fit" | "fill";
}) {
  const frame = useRef<HTMLDivElement>(null); const [frameW, setFrameW] = useState(360);
  const vids = useRef(new Map<string, HTMLVideoElement>()); const auds = useRef(new Map<string, HTMLAudioElement>());
  useEffect(() => {
    const el = frame.current; if (!el) return;
    const ro = new ResizeObserver(() => setFrameW(el.clientWidth || 360)); ro.observe(el); setFrameW(el.clientWidth || 360); return () => ro.disconnect();
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
      const isActive = active?.clip.id === id;
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
  return (
    <div className="re-stage" onPointerDown={() => setSel(null)}>
      <div ref={frame} className={`re-frame ${fit === "fill" ? "is-fill" : ""}`} style={{ aspectRatio: ar }} data-testid="preview-frame" data-aspect={edit.aspect}>
        {win.map((p) => (
          <video key={p.clip.id} data-testid={`pv-${p.clip.id}`} ref={(el) => { if (el) vids.current.set(p.clip.id, el); else vids.current.delete(p.clip.id); }}
            src={fileUrl(project, p.clip.src)} preload="auto" playsInline className="re-video" style={{ opacity: active?.clip.id === p.clip.id ? 1 : 0 }}
            onLoadedMetadata={(e) => { const v = e.currentTarget; rememberDuration(fileUrl(project, p.clip.src), v.duration); if (active?.clip.id !== p.clip.id) v.currentTime = p.clip.in; }} />
        ))}
        {!placed.length && <div className="re-empty">Add a clip from Media to start</div>}
        {edit.tracks.audio.map((c) => (
          <audio key={c.id} preload="auto" ref={(el) => { if (el) auds.current.set(c.id, el); else auds.current.delete(c.id); }} src={fileUrl(project, c.src)} />
        ))}
        {edit.tracks.text.map((tx) => {
          const on = t >= tx.start && t < tx.end; const isSel = sel?.kind === "text" && sel.id === tx.id;
          if (!on && !isSel) return null;
          return <TextOverlay key={tx.id} t={tx} frameW={frameW} frame={frame} selected={isSel} ghost={!on} onSelect={() => setSel({ kind: "text", id: tx.id })} onChange={(p, key) => onText(tx.id, p, key)} />;
        })}
      </div>
    </div>
  );
}
