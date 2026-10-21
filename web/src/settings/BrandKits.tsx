import { useCallback, useEffect, useState } from "react";
import { Palette, Plus, Trash2 } from "lucide-react";
import { api, getToken } from "../api";
import { Button, Card, IconTile, Input, Label, Select } from "../ui";
import { useToast } from "../toast";
import { confirmDialog } from "../dialogs";

export interface BrandKit {
  id: string; name: string; logo: string | null; palette: string[]; fonts: { heading?: string | null; body?: string | null };
  caption: { font?: string; size?: number; weight?: number; y?: number; bg?: string };
  watermark: { pos?: string; opacity?: number }; end_card: { text?: string; seconds?: number }; voice: { provider?: string; voice_id?: string };
  style_words: string; avoid: string[];
}
const POSITIONS = ["top-left", "top-right", "bottom-left", "bottom-right", "center"];
const HEX = /^#[0-9a-fA-F]{6}$/;
const toB64 = (f: File) => new Promise<string>((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1] || ""); r.onerror = () => rej(new Error("could not read the file")); r.readAsDataURL(f); });

function KitEditor({ kit, fonts, reload }: { kit: BrandKit; fonts: string[]; reload: () => void }) {
  const toast = useToast();
  const [k, setK] = useState(kit); const [palette, setPalette] = useState(kit.palette.join(", ")); const [avoid, setAvoid] = useState(kit.avoid.join(", "));
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { setK(kit); setPalette(kit.palette.join(", ")); setAvoid(kit.avoid.join(", ")); }, [kit]);
  const colors = palette.split(",").map((c) => c.trim()).filter(Boolean);
  const sub = <T extends keyof BrandKit>(key: T, patch: Partial<BrandKit[T]>) => setK({ ...k, [key]: { ...(k[key] as object), ...patch } });
  const fontSel = (label: string, value: string | null | undefined, on: (v: string) => void) => (
    <div><Label>{label}</Label><Select aria-label={`${kit.name} ${label}`} value={value || ""} onChange={(e) => on(e.target.value)}><option value="">default</option>{fonts.map((f) => <option key={f} value={f}>{f}</option>)}</Select></div>
  );
  const save = async () => {
    if (colors.some((c) => !HEX.test(c))) return setErr("Palette colours look like #F97316, separated by commas.");
    setErr(""); setBusy(true);
    try {
      await api("PUT", `/api/brand-kits/${kit.id}`, { name: k.name, palette: colors, fonts: { heading: k.fonts.heading || null, body: k.fonts.body || null }, caption: k.caption, watermark: k.watermark,
        end_card: k.end_card, voice: k.voice, style_words: k.style_words, avoid: avoid.split(",").map((a) => a.trim()).filter(Boolean) });
      toast("ok", `${k.name} saved. Projects already using it keep their own copy.`); reload();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const remove = async () => {
    if (!(await confirmDialog(`Move the brand kit "${kit.name}" to the trash? Projects that already use it keep their own copy.`, { title: "Delete brand kit?", ok: "Move to trash", danger: true }))) return;
    try { await api("DELETE", `/api/brand-kits/${kit.id}`); toast("ok", `${kit.name} moved to brand_kits/_trash.`); reload(); } catch (e) { toast("error", (e as Error).message); }
  };
  return (
    <details className="rounded-xl border border-slate-800 p-3" data-testid={`kit-${kit.id}`}>
      <summary className="flex cursor-pointer flex-wrap items-center gap-3">
        {kit.logo && <img src={`/api/brand-kits/${kit.id}/logo?token=${encodeURIComponent(getToken())}`} alt={`${kit.name} logo`} className="h-8 w-8 rounded bg-white/5 object-contain" />}
        <b>{kit.name}</b>
        <span className="flex gap-1" aria-label={`${kit.name} palette`}>{kit.palette.map((c) => <span key={c} className="inline-block h-4 w-4 rounded-full border border-slate-600" style={{ background: c }} title={c} />)}</span>
        <span className="text-xs text-slate-400">{kit.palette.join(" ")}</span>
      </summary>
      <div className="mt-3 space-y-3 text-sm">
        <div className="grid gap-3 sm:grid-cols-2">
          <div><Label>Name</Label><Input aria-label="Kit name" value={k.name} onChange={(e) => setK({ ...k, name: e.target.value })} /></div>
          <div><Label hint="comma separated, e.g. #0F172A, #F97316">Palette</Label><Input aria-label={`${kit.name} palette colours`} value={palette} onChange={(e) => setPalette(e.target.value)} /></div>
          {fontSel("Heading font", k.fonts.heading, (v) => sub("fonts", { heading: v }))}
          {fontSel("Body font", k.fonts.body, (v) => sub("fonts", { body: v }))}
        </div>
        <fieldset className="grid gap-3 sm:grid-cols-4"><legend className="mb-1 text-xs font-semibold text-slate-300">Captions</legend>
          {fontSel("Caption font", k.caption.font, (v) => sub("caption", { font: v || undefined }))}
          <div><Label>Size</Label><Input aria-label="Caption size" type="number" min={8} value={k.caption.size ?? ""} onChange={(e) => sub("caption", { size: Number(e.target.value) })} /></div>
          <div><Label>Height (0 to 1)</Label><Input aria-label="Caption height" type="number" min={0} max={1} step={0.01} value={k.caption.y ?? ""} onChange={(e) => sub("caption", { y: Number(e.target.value) })} /></div>
          <div><Label>Background</Label><Input aria-label="Caption background" placeholder="#000000AA" value={k.caption.bg ?? ""} onChange={(e) => sub("caption", { bg: e.target.value })} /></div>
        </fieldset>
        <fieldset className="grid gap-3 sm:grid-cols-4"><legend className="mb-1 text-xs font-semibold text-slate-300">Watermark and end card</legend>
          <div><Label>Watermark position</Label><Select aria-label="Watermark position" value={k.watermark.pos ?? "bottom-right"} onChange={(e) => sub("watermark", { pos: e.target.value })}>{POSITIONS.map((p) => <option key={p} value={p}>{p}</option>)}</Select></div>
          <div><Label>Watermark opacity</Label><Input aria-label="Watermark opacity" type="number" min={0} max={1} step={0.1} value={k.watermark.opacity ?? 0.8} onChange={(e) => sub("watermark", { opacity: Number(e.target.value) })} /></div>
          <div><Label>End card text</Label><Input aria-label="End card text" value={k.end_card.text ?? ""} onChange={(e) => sub("end_card", { text: e.target.value })} /></div>
          <div><Label>End card seconds</Label><Input aria-label="End card seconds" type="number" min={0} step={0.5} value={k.end_card.seconds ?? 2} onChange={(e) => sub("end_card", { seconds: Number(e.target.value) })} /></div>
        </fieldset>
        <div className="grid gap-3 sm:grid-cols-2">
          <div><Label>Style words</Label><Input aria-label="Style words" placeholder="clean, bright, product-first" value={k.style_words} onChange={(e) => setK({ ...k, style_words: e.target.value })} /></div>
          <div><Label hint="comma separated">Avoid (claims checked by Verify)</Label><Input aria-label="Words to avoid" placeholder="absolute claims" value={avoid} onChange={(e) => setAvoid(e.target.value)} /></div>
        </div>
        {err && <p role="alert" className="text-red-300">{err}</p>}
        <div className="flex gap-2">
          <Button size="sm" variant="pink" disabled={busy} onClick={() => void save()}>Save kit</Button>
          <Button size="sm" variant="danger" onClick={() => void remove()} aria-label={`Delete ${kit.name}`}><Trash2 size={13} />Delete</Button>
        </div>
      </div>
    </details>
  );
}

/** Settings > Brand kits: workspace-level looks (logo palette, fonts, captions, watermark, end card). A project gets its own COPY when it is created with a kit. */
export default function BrandKitsSection() {
  const toast = useToast();
  const [kits, setKits] = useState<BrandKit[] | null>(null); const [fonts, setFonts] = useState<string[]>([]);
  const [name, setName] = useState(""); const [logo, setLogo] = useState<File | null>(null); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const load = useCallback(() => api<{ kits: BrandKit[]; fonts: string[] }>("GET", "/api/brand-kits").then((r) => { setKits(r.kits); setFonts(r.fonts); }).catch((e: Error) => toast("error", e.message)), [toast]);
  useEffect(() => { void load(); }, [load]);
  const create = async () => {
    if (!name.trim() || busy) return;
    setBusy(true); setErr("");
    try {
      await api("POST", "/api/brand-kits", { name: name.trim(), ...(logo ? { logo_b64: await toB64(logo) } : {}) });
      toast("ok", logo ? `Brand kit ${name.trim()} created; its palette came from the logo.` : `Brand kit ${name.trim()} created.`);
      setName(""); setLogo(null); await load();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Card title={<span className="flex items-center gap-2"><IconTile tone="violet"><Palette size={15} /></IconTile> Brand kits</span>}
      sub="A logo, palette, fonts, captions, watermark and end card you can start any new project with.">
      <form className="mb-4 grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end" onSubmit={(e) => { e.preventDefault(); void create(); }}>
        <div><Label>New kit name</Label><Input aria-label="New brand kit name" placeholder="Acme" value={name} onChange={(e) => { setName(e.target.value); setErr(""); }} /></div>
        <div><Label hint="PNG, JPEG or WebP, up to 5 MB">Logo (gives the palette)</Label><input aria-label="Brand kit logo" type="file" accept="image/png,image/jpeg,image/webp" className="field !py-1.5 text-sm" onChange={(e) => setLogo(e.target.files?.[0] ?? null)} /></div>
        <Button type="submit" variant="pink" disabled={!name.trim() || busy}><Plus size={15} />Create kit</Button>
      </form>
      {err && <p role="alert" className="mb-3 text-sm text-red-300">{err}</p>}
      <div className="space-y-2">
        {kits === null && <p className="text-sm text-slate-400">Loading...</p>}
        {kits?.length === 0 && <p className="text-sm text-slate-400">No brand kits yet. Name one above, add your logo, and pick it when you create a project.</p>}
        {kits?.map((k) => <KitEditor key={k.id} kit={k} fonts={fonts} reload={load} />)}
      </div>
    </Card>
  );
}
