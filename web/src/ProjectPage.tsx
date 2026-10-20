import { useEffect, useState } from "react";
import { api, fileUrl } from "./api";
import { Badge, Button, Card, Input, Select } from "./ui";
import { Spinner, type Running } from "./Proposal";
import { useToast } from "./toast";
import { confirmDialog } from "./dialogs";
import type { FoundStill, ImageSpec, Overview, Review } from "./types";

export const stem = (f: string) => f.replace(/\.[^.]+$/, "");

export const fmtDate = (v?: string) => {
  if (!v) return "";
  const d = new Date(v);
  return Number.isNaN(+d) ? v.slice(0, 16) : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
};

export function ReviewBadge({ r }: { r?: Review | null }) {
  if (!r) return null;
  return (
    <div className="mt-2 text-xs">
      <Badge tone={r.verdict === "pass" ? "green" : r.verdict === "warn" ? "amber" : "red"}>vision: {r.verdict}</Badge>
      <span className="ml-1 text-slate-400">{r.summary}</span>
      {r.findings.map((f, i) => (
        <div key={i} className="mt-1 text-red-400">
          frame {f.frame}: {f.issue} ({f.severity})
        </div>
      ))}
      <div className="mt-1 text-slate-400">Advisory only: you still check it and listen to the audio.</div>
    </div>
  );
}

export type TabProps = {
  o: Overview;
  name: string;
  load: () => void;
  start: (k: "image" | "clip" | "review", t: string) => void;
  running: Running;
  openBudget: () => void;
  todoNode: React.ReactNode;
  todosDone?: boolean;
};

export const KINDS = [
  { kind: "character", title: "Characters", sub: "Main people and subjects in your story.", hint: "One sheet per person: full-body views and expressions. Faces in later scenes are built from these.", idHint: "ramesh_sheet", icon: "characters" },
  { kind: "background", title: "Backgrounds", sub: "Places, locations and environments.", hint: "Each place, empty (no people). Make a busy and an empty version if the story contrasts them.", idHint: "shop_empty" },
  { kind: "frame", title: "Scene Frames", sub: "Reference frames for consistent visuals.", hint: "One per shot: a character in a background, vertical 9:16. Pick the character and background as references.", idHint: "s01" },
  { kind: "other", title: "Uploads", sub: "Files you keep with the project.", hint: "Files such as the logo for the editor. They are not used to generate video.", idHint: "logo" },
] as const;

export function ImportStills({ project, found, reload }: { project: string; found: FoundStill[]; reload: () => void }) {
  const toast = useToast();
  const [rows, setRows] = useState(() => found.map((f) => ({ ...f, id: f.suggested_id, kind: f.suggested_kind, on: true })));
  useEffect(() => {
    setRows(found.map((f) => ({ ...f, id: f.suggested_id, kind: f.suggested_kind, on: true })));
  }, [found]);
  const [busy, setBusy] = useState(false);
  const chosen = rows.filter((r) => r.on);
  const go = async () => {
    if (
      !(await confirmDialog(
        `Add ${chosen.length} image(s) to the asset list?\n\nEach file is renamed to its asset id (for example "Ramesh Shop.png" becomes "ramesh_shop.png") so the id and the file match. Nothing is deleted, and shots that use a renamed file are updated.`,
        { title: "Add images", ok: "Add" }
      ))
    )
      return;
    setBusy(true);
    try {
      await api("POST", `/api/projects/${project}/stills/import`, { items: chosen.map((r) => ({ file: r.file, id: r.id.trim(), kind: r.kind })) });
      toast("ok", `Added ${chosen.length} image(s) to the asset list.`);
      reload();
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card
      title={`Found ${found.length} image${found.length > 1 ? "s" : ""} in this project's stills folder that are not in the asset list`}
      className="!border-amber-400/60"
      right={
        <Button size="sm" onClick={go} disabled={busy || !chosen.length}>
          {busy ? <Spinner size={13} /> : null} Add {chosen.length} to the list
        </Button>
      }
    >
      <p className="mb-3 text-xs text-slate-400">These files exist on disk but the Assets list does not know about them. Check the suggested id and category, then add them.</p>
      <div className="mb-2 flex gap-3 text-xs">
        <button type="button" className="text-brand hover:underline" onClick={() => setRows(rows.map((r) => ({ ...r, on: true })))}>
          Select all
        </button>
        <button type="button" className="text-brand hover:underline" onClick={() => setRows(rows.map((r) => ({ ...r, on: false })))}>
          Select none
        </button>
      </div>
      <ul className="grid gap-2 md:grid-cols-2">
        {rows.map((r, i) => (
          <li key={r.file} className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-950/40 p-2">
            <input type="checkbox" checked={r.on} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, on: e.target.checked } : x)))} aria-label={`Add ${r.file}`} />
            <img src={fileUrl(project, `stills/${encodeURIComponent(r.file)}`)} className="h-16 w-12 shrink-0 rounded object-cover" alt="" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs text-slate-400" title={r.file}>
                {r.file}
                {r.used_by_shots ? " · used by a shot" : ""}
              </div>
              <div className="mt-1 flex gap-1">
                <Input
                  className="min-w-0 flex-1 !py-1 font-mono text-xs"
                  value={r.id}
                  onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, id: e.target.value } : x)))}
                  aria-label={`Asset id for ${r.file}`}
                />
                <Select
                  className="!w-auto !py-1 text-xs"
                  value={r.kind}
                  aria-label={`Category for ${r.file}`}
                  onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, kind: e.target.value as ImageSpec["kind"] } : x)))}
                >
                  <option value="character">character</option>
                  <option value="background">background</option>
                  <option value="frame">scene frame</option>
                  <option value="other">other</option>
                </Select>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export const ID_OK = /^[a-z0-9][a-z0-9_-]{0,40}$/;

// Re-export decoupled tabs
export { StoryTab, DocEditor, parseStory } from "./pages/Story";
export { CostsTab } from "./pages/Costs";
export { DiscardedTab } from "./pages/Discarded";
