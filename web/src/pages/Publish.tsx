import { useEffect, useState } from "react";
import { Download, Send } from "lucide-react";
import { api, fileUrl } from "../api";
import { Badge, Button, Card, Field, Input, Label, PageHeader, Select } from "../ui";
import { PageBody } from "../app/Shell";
import type { TabProps } from "../ProjectPage";

type Metadata = { title?: string; description?: string; hashtags?: string[] | string; chapters?: { time?: number; title?: string }[] | string; platform?: string; preset?: string; thumbnail?: string; [key: string]: any };
export default function PublishPage({ name, o }: Pick<TabProps, "name" | "o">) {
  const [meta, setMeta] = useState<Metadata>({}); const [presets, setPresets] = useState<any[]>([]); const [clips, setClips] = useState<string[]>([]);
  const [draft, setDraft] = useState(false); const [busy, setBusy] = useState(""); const [result, setResult] = useState<any>(null); const [error, setError] = useState(""); const [frame, setFrame] = useState(0);
  const base = `/api/projects/${name}/publish`;
  const load = async () => { const [m, p] = await Promise.all([api<Metadata>("GET", base), api<{ presets: any[] }>("GET", "/api/delivery/presets")]); setMeta({ ...m, hashtags: Array.isArray(m.hashtags) ? m.hashtags.join(" ") : m.hashtags || "", chapters: Array.isArray(m.chapters) ? m.chapters.map((c) => `${c.time ?? 0} ${c.title || ""}`).join("\n") : m.chapters || "" }); setPresets(p.presets || []); };
  useEffect(() => { load().catch((e) => setError(e.message)); setClips(o.files?.clips || []); }, [name, o]);
  const update = (key: string, value: any) => setMeta((m) => ({ ...m, [key]: value }));
  const save = async () => { setBusy("save"); setError(""); try { await api("PUT", base, { ...meta, hashtags: String(meta.hashtags || "").split(/[\s,]+/).filter(Boolean), chapters: String(meta.chapters || "").split("\n").filter(Boolean).map((line) => { const [time, ...rest] = line.trim().split(/\s+/); return { time: Number(time) || 0, title: rest.join(" ") }; }) }); setError("Metadata saved."); } catch (e: any) { setError(e.message); } finally { setBusy(""); } };
  const runDraft = async () => { setBusy("draft"); try { const d = await api<Metadata>("POST", `${base}/draft`, { platform: meta.platform || "youtube" }); setMeta((m) => ({ ...m, ...d, hashtags: Array.isArray(d.hashtags) ? d.hashtags.join(" ") : d.hashtags || m.hashtags, chapters: Array.isArray(d.chapters) ? d.chapters.map((c) => `${c.time ?? 0} ${c.title || ""}`).join("\n") : d.chapters || m.chapters })); setDraft(true); setError("AI draft loaded for editing. It has not been saved."); } catch (e: any) { setError(e.message); } finally { setBusy(""); } };
  const exportLocal = async () => { setBusy("export"); setResult(null); try { setResult(await api("POST", `${base}/export`, { preset: meta.preset || "" })); } catch (e: any) { setError(e.message); } finally { setBusy(""); } };
  const chooseFrame = async () => { const source = clips[0]; if (!source) return; setBusy("thumbnail"); try { const r = await api<{ thumbnail: string }>("POST", `${base}/thumbnail`, { source, time: frame }); update("thumbnail", r.thumbnail); setError(`Thumbnail frame saved locally: ${r.thumbnail}`); } catch (e: any) { setError(e.message); } finally { setBusy(""); } };
  const findings = result?.preflight || result?.findings || [];
  return <PageBody><div className="space-y-4">
    <PageHeader title="Publish" accent="Details" icon={<Send size={24} />} sub="Prepare metadata and export a local delivery package." />
    <p role="note" className="rounded-xl border border-sky/30 bg-sky/5 p-3 text-sm text-sky-100">Nothing is uploaded or posted. Export creates files on this computer only.</p>
    {error && <p role="status" className="text-sm text-slate-300">{error}</p>}
    <Card title="Publishing metadata" right={<Button variant="outline" onClick={runDraft} disabled={!!busy}>{busy === "draft" ? "Drafting…" : "Draft with AI"}</Button>}>
      {draft && <p className="mb-3 text-xs text-amber-200">Unsaved AI draft. Review and edit it, then choose Save metadata.</p>}
      <div className="grid gap-3 md:grid-cols-2"><div><Label>Title</Label><Input aria-label="Title" value={meta.title || ""} onChange={(e) => update("title", e.target.value)} /></div>
        <div><Label>Platform</Label><Select aria-label="Platform" value={meta.platform || "youtube"} onChange={(e) => update("platform", e.target.value)}>{["youtube", "instagram", "tiktok", "facebook", "other"].map((x) => <option key={x}>{x}</option>)}</Select></div>
        <div className="md:col-span-2"><Label>Description</Label><Field aria-label="Description" rows={4} value={meta.description || ""} onChange={(e) => update("description", e.target.value)} /></div>
        <div><Label>Hashtags</Label><Input aria-label="Hashtags" value={String(meta.hashtags || "")} onChange={(e) => update("hashtags", e.target.value)} placeholder="#brand #story" /></div>
        <div><Label>Chapters (one per line: seconds, title)</Label><Field aria-label="Chapters" rows={3} value={String(meta.chapters || "")} onChange={(e) => update("chapters", e.target.value)} placeholder="0 Opening\n12 The reveal" /></div>
        <div><Label>Delivery preset</Label><Select aria-label="Delivery preset" value={meta.preset || ""} onChange={(e) => update("preset", e.target.value)}><option value="">Choose a preset</option>{presets.map((p) => <option key={p.id || p.name} value={p.id || p.name}>{p.label || p.name || p.id}</option>)}</Select></div>
      </div><div className="mt-3 flex gap-2"><Button onClick={save} disabled={!!busy}>{busy === "save" ? "Saving…" : "Save metadata"}</Button><Button variant="pink" onClick={exportLocal} disabled={!!busy || !meta.preset}><Download size={14} />{busy === "export" ? "Exporting…" : "Export locally"}</Button></div>
    </Card>
    <Card title="Thumbnail frame" sub="Choose a frame from the first available clip. The image stays in project exports.">
      <div className="flex flex-wrap items-end gap-3"><div><Label>Frame time in seconds</Label><Input aria-label="Frame time in seconds" type="number" min="0" step="0.1" value={frame} onChange={(e) => setFrame(Number(e.target.value))} /></div><Button variant="outline" disabled={!clips.length || !!busy} onClick={chooseFrame}>Save thumbnail frame</Button>{meta.thumbnail && <Badge tone="sky">{meta.thumbnail}</Badge>}</div>
      {clips[0] && <video className="mt-3 max-h-52 rounded-xl border border-slate-800" controls src={fileUrl(name, clips[0])} aria-label="Available clip for thumbnail selection" />}
    </Card>
    {result && <Card title="Local export result"><p className="mb-2 text-sm">{result.file || result.path || result.message || "Export finished."}</p>{findings.length > 0 && <ul className="space-y-1">{findings.map((f: any, i: number) => <li key={i} role={f.level === "error" || f.severity === "error" ? "alert" : "status"} className="text-sm">{f.level || f.severity || "Finding"}: {f.message || f.text || JSON.stringify(f)}</li>)}</ul>}</Card>}
  </div></PageBody>;
}
