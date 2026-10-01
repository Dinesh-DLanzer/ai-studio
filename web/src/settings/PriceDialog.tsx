import { useEffect, useState } from "react";
import { Button, Input, Label, Modal } from "../ui";
import { useToast } from "../toast";
import { settingsApi } from "./client";
import type { Capability, ModelInfo, PriceCard } from "./types";

export interface PriceTarget { provider: string; provider_label?: string; model: string; capability: Capability; suggest?: PriceCard | null; }

const num = (s: string) => (s.trim() === "" ? NaN : Number(s));
const bad = (n: number) => !Number.isFinite(n) || n < 0;

function describe(c: PriceCard): string {
  if (c.kind === "image") return `$${c.per_image ?? "?"} per image`;
  if (c.kind === "video") {
    const e = Object.entries(c.per_second || {})[0];
    if (!e) return "per-second price";
    const v = e[1] as unknown;
    if (v && typeof v === "object") { const o = v as { audio?: number; no_audio?: number }; return `$${o.no_audio ?? "?"}/s without audio, $${o.audio ?? "?"}/s with audio (${e[0]})`; }
    return `$${v}/s (${e[0]})`;
  }
  if (c.free) return "free";
  return `$${c.input_per_1m ?? "?"} in / $${c.output_per_1m ?? "?"} out per 1M tokens`;
}

export default function PriceDialog({ target, onClose, onSaved }: { target: PriceTarget | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [suggest, setSuggest] = useState<PriceCard | null>(null);
  const [perSec, setPerSec] = useState(""); const [diff, setDiff] = useState(false);
  const [withAudio, setWithAudio] = useState(""); const [noAudio, setNoAudio] = useState("");
  const [perImage, setPerImage] = useState("");
  const [free, setFree] = useState(false); const [inp, setInp] = useState(""); const [out, setOut] = useState("");
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);

  useEffect(() => {
    setPerSec(""); setDiff(false); setWithAudio(""); setNoAudio(""); setPerImage(""); setFree(false); setInp(""); setOut(""); setErr(""); setBusy(false);
    setSuggest(target?.suggest ?? null);
    if (!target || target.suggest !== undefined) return;
    let live = true;
    settingsApi.models(target.capability).then((r) => {
      if (!live) return;
      const m: ModelInfo | undefined = r.models.find((x) => x.provider === target.provider && x.id === target.model);
      setSuggest(m?.suggest ?? null);
    }).catch(() => {});
    return () => { live = false; };
  }, [target]);

  if (!target) return <Modal open={false} onClose={onClose} title="Set price"><span /></Modal>;
  const kind = target.capability === "video" ? "video" : target.capability === "image" ? "image" : "text";

  const apply = (c: PriceCard) => {
    setErr("");
    if (c.kind === "video") {
      const e = Object.entries(c.per_second || {})[0];
      const v = e?.[1] as unknown;
      if (v && typeof v === "object") { const o = v as { audio?: number; no_audio?: number }; setDiff(true); setWithAudio(String(o.audio ?? "")); setNoAudio(String(o.no_audio ?? "")); }
      else if (v !== undefined) { setDiff(false); setPerSec(String(v)); }
    } else if (c.kind === "image") setPerImage(String(c.per_image ?? ""));
    else if (c.free) setFree(true);
    else { setFree(false); setInp(String(c.input_per_1m ?? "")); setOut(String(c.output_per_1m ?? "")); }
  };

  const save = async () => {
    let card: PriceCard;
    if (kind === "video") {
      if (diff) {
        const a = num(withAudio), n = num(noAudio);
        if (bad(a) || bad(n)) return setErr("Enter both prices as numbers, 0 or more.");
        card = { kind: "video", per_second: { "720p": { audio: a, no_audio: n } } };
      } else {
        const p = num(perSec);
        if (bad(p)) return setErr("Enter the price per second as a number, 0 or more.");
        card = { kind: "video", per_second: { "720p": p } };
      }
    } else if (kind === "image") {
      const p = num(perImage);
      if (bad(p)) return setErr("Enter the price per image as a number, 0 or more.");
      card = { kind: "image", per_image: p };
    } else if (free) card = { kind: "text", free: true };
    else {
      const i = num(inp), o = num(out);
      if (bad(i) || bad(o)) return setErr("Enter both token prices as numbers, 0 or more.");
      card = { kind: "text", input_per_1m: i, output_per_1m: o };
    }
    setErr(""); setBusy(true);
    try { await settingsApi.putPrice(target.provider, target.model, card); toast("ok", `Saved price for ${target.model}`); onSaved(); onClose(); }
    catch (e) { setErr((e as Error).message); toast("error", `Could not save price: ${(e as Error).message}`); }
    finally { setBusy(false); }
  };

  return (
    <Modal open onClose={onClose} title="Set price">
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void save(); }}>
        <p className="text-sm text-slate-300">Price for <span className="font-mono text-slate-100">{target.model}</span>{target.provider_label ? <> on {target.provider_label}</> : null}. Used for cost estimates and the budget.</p>
        {suggest && (
          <div className="panel-quiet flex flex-wrap items-center justify-between gap-2 p-3 text-sm" role="note">
            <span>Similar model priced at {describe(suggest)}{suggest.from ? <> (from <span className="font-mono">{suggest.from}</span>)</> : null}.</span>
            <Button variant="soft" size="sm" onClick={() => apply(suggest)}>Use this price</Button>
          </div>
        )}
        {kind === "video" && (
          <div className="space-y-3">
            <label className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={diff} onChange={(e) => setDiff(e.target.checked)} /> Price differs with audio</label>
            {diff ? (
              <div className="grid grid-cols-2 gap-3">
                <div><Label>$ per second, with audio</Label><Input aria-label="Dollars per second with audio" type="number" min={0} step="any" value={withAudio} onChange={(e) => setWithAudio(e.target.value)} autoFocus /></div>
                <div><Label>$ per second, without audio</Label><Input aria-label="Dollars per second without audio" type="number" min={0} step="any" value={noAudio} onChange={(e) => setNoAudio(e.target.value)} /></div>
              </div>
            ) : (
              <div><Label>$ per second (720p)</Label><Input aria-label="Dollars per second (720p)" type="number" min={0} step="any" value={perSec} onChange={(e) => setPerSec(e.target.value)} autoFocus /></div>
            )}
          </div>
        )}
        {kind === "image" && <div><Label>$ per image</Label><Input aria-label="Dollars per image" type="number" min={0} step="any" value={perImage} onChange={(e) => setPerImage(e.target.value)} autoFocus /></div>}
        {kind === "text" && (
          <fieldset className="space-y-3">
            <legend className="sr-only">Pricing type</legend>
            <div className="flex gap-4 text-sm text-slate-300">
              <label className="flex items-center gap-2"><input type="radio" name="ptype" checked={free} onChange={() => setFree(true)} /> Free</label>
              <label className="flex items-center gap-2"><input type="radio" name="ptype" checked={!free} onChange={() => setFree(false)} /> Pay per token</label>
            </div>
            {!free && (
              <div className="grid grid-cols-2 gap-3">
                <div><Label>$ per 1M input tokens</Label><Input aria-label="Dollars per million input tokens" type="number" min={0} step="any" value={inp} onChange={(e) => setInp(e.target.value)} autoFocus /></div>
                <div><Label>$ per 1M output tokens</Label><Input aria-label="Dollars per million output tokens" type="number" min={0} step="any" value={out} onChange={(e) => setOut(e.target.value)} /></div>
              </div>
            )}
          </fieldset>
        )}
        {err && <p role="alert" className="text-sm text-red-300">{err}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" disabled={busy}>{busy ? "Saving..." : "Save price"}</Button>
        </div>
      </form>
    </Modal>
  );
}
