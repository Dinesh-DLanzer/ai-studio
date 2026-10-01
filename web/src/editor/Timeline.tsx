import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Copy, Film, Maximize2, Music, Redo2, Scissors, Trash2, Type, Undo2, ZoomIn, ZoomOut } from "lucide-react";
import { fileUrl } from "../api";
import type { AClip, Edit, Sel, TText, VClip } from "./types";
import { audioSpan, clamp, editEnd, fileName, lanes, layout, mmssd, round2, textSpan } from "./time";
import { knownDuration, peaks, thumbs } from "./media";

const LABEL_W = 128, RULER_H = 34, LANE_H = 40, VIDEO_H = 58;

function Filmstrip({ url, from, to, w }: { url: string; from: number; to: number; w: number }) {
  const [imgs, setImgs] = useState<string[]>([]);
  const n = clamp(Math.ceil(w / 40), 1, 14);
  useEffect(() => {
    let live = true; const id = window.setTimeout(() => { thumbs(url, from, to, n).then((x) => live && setImgs(x)).catch(() => {}); }, 250);
    return () => { live = false; window.clearTimeout(id); };
  }, [url, from, to, n]);
  return <div className="re-film" aria-hidden>{imgs.map((s, i) => <img key={i} src={s} alt="" draggable={false} style={{ width: `${100 / imgs.length}%` }} />)}</div>;
}

function Wave({ url, from, to, w, h }: { url: string; from: number; to: number; w: number; h: number }) {
  const ref = useRef<HTMLCanvasElement>(null); const [pk, setPk] = useState<{ peaks: number[]; duration: number } | null>(null);
  useEffect(() => { let live = true; peaks(url).then((p) => live && setPk(p)).catch(() => {}); return () => { live = false; }; }, [url]);
  useLayoutEffect(() => {
    const c = ref.current; if (!c || !pk) return; const W = Math.max(1, Math.min(4000, Math.round(w))); c.width = W; c.height = h;
    const g = c.getContext("2d")!; g.clearRect(0, 0, W, h); g.fillStyle = "#34d399";
    const bars = Math.floor(W / 3);
    for (let i = 0; i < bars; i++) {
      const time = from + (i / bars) * (to - from); const idx = Math.min(pk.peaks.length - 1, Math.floor((time / pk.duration) * pk.peaks.length));
      const v = Math.max(0.04, Math.min(1, pk.peaks[idx] * 1.6)); g.fillRect(i * 3, (h - v * h) / 2, 2, v * h);
    }
  }, [pk, from, to, w, h]);
  return <canvas ref={ref} className="re-wave" aria-hidden />;
}

function useDrag() {
  return (e: React.PointerEvent, onMove: (dx: number) => void, onEnd?: (dx: number) => void) => {
    e.preventDefault(); e.stopPropagation(); const x0 = e.clientX;
    const mv = (ev: PointerEvent) => onMove(ev.clientX - x0);
    const up = (ev: PointerEvent) => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); onEnd?.(ev.clientX - x0); };
    addEventListener("pointermove", mv); addEventListener("pointerup", up);
  };
}

export interface TimelineProps {
  project: string; edit: Edit; set: (fn: (e: Edit) => Edit, key?: string) => void; t: number; setT: (t: number) => void; sel: Sel; setSel: (s: Sel) => void;
  undo: () => void; redo: () => void; canUndo: boolean; canRedo: boolean; split: () => void; remove: () => void; duplicate: () => void; playing: boolean;
}

export default function Timeline(p: TimelineProps) {
  const { project, edit, set, t, setT, sel, setSel } = p; const drag = useDrag();
  const area = useRef<HTMLDivElement>(null); const [areaW, setAreaW] = useState(900); const [zoom, setZoom] = useState(1);
  const [ghost, setGhost] = useState<{ id: string; dx: number } | null>(null);
  useEffect(() => {
    const el = area.current; if (!el) return; const ro = new ResizeObserver(() => setAreaW(el.clientWidth || 900)); ro.observe(el); setAreaW(el.clientWidth || 900); return () => ro.disconnect();
  }, []);
  const { placed, total } = layout(edit.tracks.video);
  const end = editEnd(edit); const span = Math.max(30, Math.ceil(end + 2));
  const pps = ((areaW - 24) / span) * zoom; const width = Math.max(areaW - 4, span * pps + 24);
  const tx = lanes(edit.tracks.text.map((x) => ({ ...textSpan(x), x }))); const ax = lanes(edit.tracks.audio.map((x) => ({ ...audioSpan(x), x })));
  const textLanes = Math.max(1, ...tx.map((l) => l.lane + 1)), audioLanes = Math.max(1, ...ax.map((l) => l.lane + 1));
  const textH = textLanes * LANE_H + 8, audioH = audioLanes * LANE_H + 8;
  const step = [0.5, 1, 2, 5, 10, 15, 30, 60].find((s) => s * pps >= 70) || 60;

  const seekFrom = (clientX: number) => { const r = area.current!.getBoundingClientRect(); setT(clamp((clientX - r.left + area.current!.scrollLeft - 12) / pps, 0, Math.max(total, end))); };
  const scrub = (e: React.PointerEvent) => { e.preventDefault(); seekFrom(e.clientX); const mv = (ev: PointerEvent) => seekFrom(ev.clientX); const up = () => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); }; addEventListener("pointermove", mv); addEventListener("pointerup", up); };

  useEffect(() => { // keep the playhead in view while playing
    const el = area.current; if (!el || !p.playing) return; const x = t * pps + 12;
    if (x > el.scrollLeft + el.clientWidth - 30 || x < el.scrollLeft) el.scrollLeft = Math.max(0, x - 60);
  }, [t, p.playing, pps]);
  useEffect(() => {
    const el = area.current; if (!el) return; const f = (e: WheelEvent) => { if (e.ctrlKey || e.metaKey) { e.preventDefault(); setZoom((z) => clamp(z * (e.deltaY < 0 ? 1.15 : 0.87), 0.25, 8)); } };
    el.addEventListener("wheel", f, { passive: false }); return () => el.removeEventListener("wheel", f);
  }, []);

  const upd = <K extends "video" | "text" | "audio">(kind: K, id: string, patch: Partial<Edit["tracks"][K][number]>, key: string) =>
    set((e) => ({ ...e, tracks: { ...e.tracks, [kind]: (e.tracks[kind] as any[]).map((x) => (x.id === id ? { ...x, ...patch } : x)) } as Edit["tracks"] }), key);

  // ---- video clip: drag to reorder, trim with the edge handles
  const clipDrag = (e: React.PointerEvent, c: VClip, idx: number) => {
    setSel({ kind: "video", id: c.id }); const p0 = placed[idx];
    drag(e, (dx) => setGhost({ id: c.id, dx }), (dx) => {
      setGhost(null); if (Math.abs(dx) < 4) return;
      const center = p0.start + p0.dur / 2 + dx / pps; const others = placed.filter((_, i) => i !== idx);
      const to = others.filter((o) => o.start + o.dur / 2 < center).length; if (to === idx) return;
      set((ed) => { const v = [...ed.tracks.video]; const [m] = v.splice(idx, 1); v.splice(to, 0, m); return { ...ed, tracks: { ...ed.tracks, video: v } }; });
    });
  };
  const trimV = (e: React.PointerEvent, c: VClip, side: "l" | "r") => {
    setSel({ kind: "video", id: c.id }); const base = { in: c.in, out: c.out }; const max = knownDuration(fileUrl(project, c.src)) ?? Infinity;
    drag(e, (dx) => {
      const d = dx / pps;
      upd("video", c.id, side === "l" ? { in: round2(clamp(base.in + d, 0, base.out - 0.3)) } : { out: round2(clamp(base.out + d, base.in + 0.3, max)) }, `trim${c.id}`);
    });
  };
  // ---- text / audio bars: move and trim
  const moveTA = (e: React.PointerEvent, kind: "text" | "audio", id: string, s0: number, e0: number) => {
    setSel({ kind, id }); const len = e0 - s0;
    drag(e, (dx) => { const s = round2(Math.max(0, s0 + dx / pps)); upd(kind, id, kind === "text" ? { start: s, end: round2(s + len) } as Partial<TText> : { start: s } as Partial<AClip>, `mv${id}`); });
  };
  const trimT = (e: React.PointerEvent, x: TText, side: "l" | "r") => {
    setSel({ kind: "text", id: x.id });
    drag(e, (dx) => { const d = dx / pps; upd("text", x.id, side === "l" ? { start: round2(clamp(x.start + d, 0, x.end - 0.3)) } : { end: round2(Math.max(x.start + 0.3, x.end + d)) }, `tt${x.id}`); });
  };
  const trimA = (e: React.PointerEvent, a: AClip, side: "l" | "r") => {
    setSel({ kind: "audio", id: a.id }); const max = knownDuration(fileUrl(project, a.src)) ?? Infinity;
    drag(e, (dx) => {
      const d = dx / pps;
      if (side === "l") { const nd = clamp(d, -Math.min(a.in, a.start), a.out - a.in - 0.3); upd("audio", a.id, { in: round2(a.in + nd), start: round2(a.start + nd) }, `ta${a.id}`); }
      else upd("audio", a.id, { out: round2(clamp(a.out + d, a.in + 0.3, max)) }, `ta${a.id}`);
    });
  };

  const tools = [
    { icon: Undo2, label: "Undo", on: p.undo, dis: !p.canUndo }, { icon: Redo2, label: "Redo", on: p.redo, dis: !p.canRedo },
  ];
  const Tb = ({ icon: I, label, on, dis }: { icon: typeof Undo2; label: string; on: () => void; dis?: boolean }) =>
    <button type="button" className="re-tb" aria-label={label} title={label} onClick={on} disabled={dis}><I size={17} /></button>;

  return (
    <section className="re-card re-timeline" aria-label="Timeline" data-testid="timeline">
      <div className="re-tl-bar">
        {tools.map((x) => <Tb key={x.label} icon={x.icon} label={x.label} on={x.on} dis={x.dis} />)}
        <span className="re-tl-sep" />
        <Tb icon={Scissors} label="Split at playhead" on={p.split} />
        <Tb icon={Trash2} label="Delete selected" on={p.remove} dis={!sel} />
        <Tb icon={Copy} label="Duplicate selected" on={p.duplicate} dis={!sel} />
        <span className="ml-auto flex items-center gap-1">
          <Tb icon={ZoomOut} label="Zoom out" on={() => setZoom((z) => clamp(z / 1.3, 0.25, 8))} />
          <Tb icon={Maximize2} label="Fit timeline to width" on={() => setZoom(1)} />
          <Tb icon={ZoomIn} label="Zoom in" on={() => setZoom((z) => clamp(z * 1.3, 0.25, 8))} />
        </span>
      </div>
      <div className="re-tl-body">
        <div className="re-tl-labels" style={{ width: LABEL_W, paddingTop: RULER_H }}>
          <div className="re-tl-label" style={{ height: textH }}><Type size={16} />Text</div>
          <div className="re-tl-label" style={{ height: VIDEO_H + 8 }}><Film size={16} />Video</div>
          <div className="re-tl-label" style={{ height: audioH }}><Music size={16} />Audio</div>
        </div>
        <div ref={area} className="re-tl-area" role="region" aria-label="Timeline tracks" tabIndex={0} onPointerDown={scrub}>
          <div style={{ width, position: "relative", paddingLeft: 12 }}>
            <div className="re-ruler" style={{ height: RULER_H }}>
              {Array.from({ length: Math.floor(span / step) + 1 }, (_, i) => i * step).map((s) => (
                <span key={s} className="re-tick" style={{ left: s * pps }}>{Number.isInteger(s) ? `${s}s` : `${s}s`}</span>
              ))}
            </div>
            {/* Text track */}
            <div className="re-row" style={{ height: textH }} data-testid="track-text">
              {tx.map(({ item, lane }) => {
                const x = item.x; const w = (x.end - x.start) * pps; const isSel = sel?.kind === "text" && sel.id === x.id;
                return (
                  <div key={x.id} data-testid={`tbar-${x.id}`} className={`re-bar re-bar-text ${isSel ? "is-sel" : ""}`} style={{ left: x.start * pps, width: w, top: 4 + lane * LANE_H, height: LANE_H - 4 }}
                    onPointerDown={(e) => moveTA(e, "text", x.id, x.start, x.end)}>
                    <span className="re-grip l" onPointerDown={(e) => trimT(e, x, "l")} /><span className="truncate">{x.text.replace(/\n/g, " ")}</span><span className="re-grip r" onPointerDown={(e) => trimT(e, x, "r")} />
                  </div>
                );
              })}
            </div>
            {/* Video track */}
            <div className="re-row" style={{ height: VIDEO_H + 8 }} data-testid="track-video">
              {placed.map((pl, i) => {
                const c = pl.clip; const w = pl.dur * pps; const isSel = sel?.kind === "video" && sel.id === c.id; const g = ghost?.id === c.id ? ghost.dx : 0;
                return (
                  <div key={c.id} data-testid={`vbar-${c.id}`} className={`re-bar re-bar-video ${isSel ? "is-sel" : ""}`}
                    style={{ left: pl.start * pps + g, width: w, top: 4, height: VIDEO_H, zIndex: g ? 5 : 1, opacity: g ? 0.85 : 1 }} onPointerDown={(e) => clipDrag(e, c, i)} title={`${fileName(c.src)} (${(pl.dur).toFixed(1)}s)`}>
                    <Filmstrip url={fileUrl(project, c.src)} from={c.in} to={c.out} w={w} />
                    {pl.td > 0 && <span className="re-trans" style={{ width: pl.td * pps }} aria-hidden />}
                    <span className="re-grip l" onPointerDown={(e) => trimV(e, c, "l")} /><span className="re-grip r" onPointerDown={(e) => trimV(e, c, "r")} />
                  </div>
                );
              })}
            </div>
            {/* Audio track */}
            <div className="re-row" style={{ height: audioH }} data-testid="track-audio">
              {ax.map(({ item, lane }) => {
                const a = item.x; const w = (a.out - a.in) * pps; const isSel = sel?.kind === "audio" && sel.id === a.id;
                return (
                  <div key={a.id} data-testid={`abar-${a.id}`} className={`re-bar re-bar-audio ${isSel ? "is-sel" : ""}`} style={{ left: a.start * pps, width: w, top: 4 + lane * LANE_H, height: LANE_H - 4 }}
                    onPointerDown={(e) => moveTA(e, "audio", a.id, a.start, a.start + a.out - a.in)}>
                    <Wave url={fileUrl(project, a.src)} from={a.in} to={a.out} w={w} h={LANE_H - 6} />
                    <span className="re-bar-label"><Music size={12} />{a.name || fileName(a.src)}</span>
                    <span className="re-grip l" onPointerDown={(e) => trimA(e, a, "l")} /><span className="re-grip r" onPointerDown={(e) => trimA(e, a, "r")} />
                  </div>
                );
              })}
            </div>
            <div className="re-playhead" data-testid="playhead" style={{ left: 12 + t * pps }}>
              <span className="re-flag" >{mmssd(t)}</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
