/** Browser-side media helpers: durations, filmstrip thumbnails and waveform peaks.  Cached by URL; nothing here touches the server edit. */
const durCache = new Map<string, number>();
const durWait = new Map<string, Promise<number>>();
export const knownDuration = (url: string) => durCache.get(url);

export function duration(url: string, kind: "video" | "audio" = "video"): Promise<number> {
  const hit = durCache.get(url); if (hit !== undefined) return Promise.resolve(hit);
  let p = durWait.get(url);
  if (!p) {
    p = new Promise<number>((res, rej) => {
      const v = document.createElement(kind); v.preload = "metadata"; v.muted = true;
      v.onloadedmetadata = () => { const d = isFinite(v.duration) ? v.duration : 0; durCache.set(url, d); res(d); v.removeAttribute("src"); v.load(); };
      v.onerror = () => { durWait.delete(url); rej(new Error("cannot read media")); };
      v.src = url;
    });
    durWait.set(url, p);
  }
  return p;
}
export const rememberDuration = (url: string, d: number) => { if (isFinite(d) && d > 0) durCache.set(url, d); };

// ---- thumbnails (one at a time, so a long timeline never floods the browser)
const thumbCache = new Map<string, string[]>();
let chain: Promise<unknown> = Promise.resolve();
export function thumbs(url: string, from: number, to: number, n: number, h = 48): Promise<string[]> {
  const key = `${url}|${from.toFixed(1)}|${to.toFixed(1)}|${n}`;
  const hit = thumbCache.get(key); if (hit) return Promise.resolve(hit);
  const job = chain.then(() => new Promise<string[]>((res) => {
    const v = document.createElement("video"); v.muted = true; v.preload = "auto"; v.playsInline = true;
    const out: string[] = []; const c = document.createElement("canvas");
    const done = () => { thumbCache.set(key, out); v.removeAttribute("src"); v.load(); res(out); };
    v.onerror = done;
    v.onloadedmetadata = () => {
      c.height = h; c.width = Math.max(8, Math.round(h * (v.videoWidth / (v.videoHeight || 1))));
      let i = 0;
      const next = () => { if (i >= n) return done(); v.currentTime = from + ((i + 0.5) / n) * (to - from); };
      v.onseeked = () => { try { c.getContext("2d")!.drawImage(v, 0, 0, c.width, c.height); out.push(c.toDataURL("image/jpeg", 0.55)); } catch { /* tainted: skip */ } i++; next(); };
      next();
    };
    v.src = url;
  }));
  chain = job.catch(() => {});
  return job;
}

// ---- waveform
const peakCache = new Map<string, Promise<{ peaks: number[]; duration: number }>>();
export function peaks(url: string): Promise<{ peaks: number[]; duration: number }> {
  let p = peakCache.get(url);
  if (!p) {
    p = fetch(url).then((r) => r.arrayBuffer()).then((buf) => new OfflineAudioContext(1, 1, 44100).decodeAudioData(buf)).then((ab) => {
      const d = ab.getChannelData(0); const bins = Math.min(1200, Math.max(60, Math.round(ab.duration * 20))); const per = Math.max(1, Math.floor(d.length / bins));
      const out: number[] = [];
      for (let b = 0; b < bins; b++) { let m = 0; for (let i = b * per; i < Math.min(d.length, (b + 1) * per); i += 8) m = Math.max(m, Math.abs(d[i])); out.push(m); }
      return { peaks: out, duration: ab.duration };
    });
    peakCache.set(url, p); p.catch(() => peakCache.delete(url));
  }
  return p;
}
