import type { VClip, Edit, TText, AClip } from "./types";

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
export const round1 = (n: number) => Math.round(n * 10) / 10;
export const round2 = (n: number) => Math.round(n * 100) / 100;

/** 00:08 style (seconds) */
export const mmss = (s: number) => { const t = Math.max(0, Math.floor(s + 1e-6)); return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`; };
/** 00:08.0 style (the playhead flag) */
export const mmssd = (s: number) => `${mmss(s)}.${Math.floor((Math.max(0, s) % 1) * 10 + 1e-6)}`;

let counter = 0;
export const nid = (p: string) => `${p}${Date.now().toString(36)}${(counter++).toString(36)}${Math.floor(Math.random() * 1296).toString(36)}`;

/** Transition length that is really used into a clip (same rule as the server: never longer than either side; 0 = hard cut). */
export function usedTransition(c: VClip, curLen: number, d: number) {
  if (c.transition.type === "cut") return 0;
  const td = Math.min(c.transition.dur, curLen - 0.05, d - 0.05);
  return td >= 0.1 ? td : 0;
}

export interface Placed { clip: VClip; start: number; end: number; dur: number; td: number; }
/** Where each clip sits on the timeline (transitions overlap the previous clip). */
export function layout(video: VClip[]): { placed: Placed[]; total: number } {
  const placed: Placed[] = []; let total = 0;
  video.forEach((clip, i) => {
    const dur = clip.out - clip.in;
    const td = i === 0 ? 0 : usedTransition(clip, total, dur);
    const start = total - td;
    placed.push({ clip, start, end: start + dur, dur, td });
    total = start + dur;
  });
  return { placed, total };
}

export const editEnd = (e: Edit) => Math.max(layout(e.tracks.video).total, ...e.tracks.text.map((t) => t.end), ...e.tracks.audio.map((a) => a.start + a.out - a.in), 0);

/** Greedy lane assignment so overlapping items sit on separate rows. */
export function lanes<T extends { s: number; e: number }>(items: T[]): { item: T; lane: number }[] {
  const ends: number[] = []; const out: { item: T; lane: number }[] = [];
  [...items].sort((a, b) => a.s - b.s).forEach((item) => {
    let l = ends.findIndex((e) => e <= item.s + 1e-6);
    if (l < 0) { l = ends.length; ends.push(0); }
    ends[l] = item.e; out.push({ item, lane: l });
  });
  return out;
}

export const textSpan = (t: TText) => ({ s: t.start, e: t.end });
export const audioSpan = (a: AClip) => ({ s: a.start, e: a.start + a.out - a.in });

export const fileName = (rel: string) => rel.split("/").pop() || rel;
