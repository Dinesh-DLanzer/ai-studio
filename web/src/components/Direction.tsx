import { useEffect, useState } from "react";
import { AlertTriangle, Plus, X } from "lucide-react";
import { api, fileUrl } from "../api";
import { Button, Input, Label, Select } from "../ui";
import { settingsApi } from "../settings/client";
import type { CapabilityModel, CapabilityProfile } from "../settings/types";
import type { Direction as Dir, Shot } from "../types";

export const MOVEMENTS = ["static", "pan-left", "pan-right", "tilt-up", "tilt-down", "dolly-in", "dolly-out", "truck-left", "truck-right", "pedestal-up", "pedestal-down", "orbit-left", "orbit-right", "crane-up", "crane-down", "zoom-in", "zoom-out", "handheld", "tracking", "fpv", "dolly-zoom"];
export const FRAMINGS = ["extreme-wide", "wide", "medium-wide", "medium", "medium-close", "close-up", "extreme-close-up", "over-shoulder", "pov", "insert"];
export const ANGLES = ["eye-level", "low", "high", "dutch", "overhead", "ground"];
const SPEEDS = ["slow", "medium", "fast"];
const nice = (s: string) => s.replace(/-/g, " ");

interface Preset { id: string; name: string; direction: Dir; description: string }
interface SpecView { profile: CapabilityProfile; camera: { prompt_text?: string; native?: Record<string, string> }; warnings: string[]; model: string }

/** Native (sent as an API parameter) or Via prompt (written into the prompt): text plus an icon-free label, never colour alone. */
export const ModeChip = ({ native }: { native: boolean }) =>
  <span className={`tag ${native ? "tag-emerald" : "tag-sky"} !px-1.5 !py-0.5 !text-[0.65rem]`} data-testid={native ? "chip-native" : "chip-prompt"}>{native ? "Native" : "Via prompt"}</span>;

const isNative = (p: CapabilityProfile | undefined, movement?: string) =>
  !!p && !!movement && p.camera.mode === "native" && p.camera.native.includes(movement.replace(/-/g, "_"));

/** The Shots inspector "Direction" section. Edits go into the unsaved shot (Save writes shots.json); the Native / Via prompt chips come from the saved shot's spec. */
export default function DirectionSection({ project, shot, stills, savedKey, onChange }: {
  project: string; shot: Shot; stills: string[]; savedKey: string; onChange: (patch: Partial<Shot>) => void;
}) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [spec, setSpec] = useState<SpecView | null>(null); const [specErr, setSpecErr] = useState("");
  const [models, setModels] = useState<CapabilityModel[]>([]);
  useEffect(() => { api<{ presets: Preset[] }>("GET", "/api/camera-presets").then((r) => setPresets(r.presets)).catch(() => {}); }, []);
  useEffect(() => { settingsApi.capabilities("video").then((r) => setModels(r.models)).catch(() => {}); }, []);
  useEffect(() => {
    let live = true; setSpecErr("");
    api<SpecView>("GET", `/api/projects/${encodeURIComponent(project)}/spec/clip/${encodeURIComponent(shot.id)}`)
      .then((r) => live && setSpec(r)).catch((e: Error) => { if (live) { setSpec(null); setSpecErr(e.message); } });
    return () => { live = false; };
  }, [project, shot.id, savedKey]);

  const d: Dir = shot.direction || {};
  const profile = spec?.profile;
  const set = (patch: Partial<Dir>) => {
    const next: Record<string, unknown> = { ...d, ...patch };
    for (const k of Object.keys(next)) if (next[k] === "" || next[k] === undefined || (typeof next[k] === "number" && Number.isNaN(next[k]))) delete next[k];
    onChange({ direction: Object.keys(next).length ? (next as Dir) : undefined });
  };
  const camera = profile?.camera.mode !== "none";
  const canEnd = !profile || profile.frames.end;
  const kfMax = profile ? profile.frames.keyframes : 0;
  const suggest = (ok: (p: CapabilityProfile) => boolean) => models.find((m) => ok(m.profile))?.id;
  const cameraHint = suggest((p) => p.camera.mode !== "none"), endHint = suggest((p) => p.frames.end), kfHint = suggest((p) => p.frames.keyframes > 0);
  const keyframes = shot.keyframes || [];
  const stillOptions = stills.map((f) => <option key={f} value={`stills/${f}`}>{f}</option>);
  const pickPreset = (id: string) => { const pr = presets.find((x) => x.id === id); onChange({ direction: pr ? { ...pr.direction, preset: pr.id } : undefined }); };
  const moveNative = isNative(profile, d.movement);

  return (
    <div className="space-y-3 text-sm" data-testid="direction">
      {specErr && <p role="note" className="text-xs text-slate-400">Model details unavailable: {specErr}</p>}
      {shot.camera && <p role="note" className="text-xs text-amber-300"><b>Note:</b> this shot has a free-text camera note. It wins over the Direction below.</p>}
      {profile && (
        <div className="flex flex-wrap gap-1.5" aria-label="Model capabilities" data-testid="cap-chips">
          <span className="tag">Model {spec!.model.split("/").pop()}</span>
          <span className="tag">{profile.frames.end ? "End frame supported" : "No end frame"}</span>
          <span className="tag">{profile.frames.keyframes ? `${profile.frames.keyframes} keyframe(s)` : "No keyframes"}</span>
          <span className="tag">References max {profile.references.max}</span>
          <span className="tag">Durations {profile.durations.length ? profile.durations.join(", ") + "s" : "any"}</span>
          <span className="tag">Camera: {profile.camera.mode}</span>
        </div>
      )}
      {spec && spec.warnings.length > 0 && (
        <ul className="space-y-1 text-xs text-amber-300" aria-label="Spec warnings" data-testid="spec-warnings">
          {spec.warnings.map((w, i) => <li key={i} className="flex items-start gap-2"><AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden /><span><b>Warning:</b> {w}</span></li>)}
        </ul>
      )}

      {camera ? (
        <>
          <div>
            <Label hint={<ModeChip native={false} />}>Camera preset</Label>
            <Select aria-label="Camera preset" value={d.preset || ""} onChange={(e) => pickPreset(e.target.value)}>
              <option value="">none</option>
              {presets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </Select>
            {d.preset && <p className="mt-1 text-xs text-slate-400">{presets.find((p) => p.id === d.preset)?.description}</p>}
          </div>
          <div>
            <Label hint={d.movement ? <ModeChip native={moveNative} /> : undefined}>Movement</Label>
            <Select aria-label="Camera movement" value={d.movement || ""} onChange={(e) => set({ movement: e.target.value })}>
              <option value="">none</option>
              {MOVEMENTS.map((m) => <option key={m} value={m}>{nice(m)}{isNative(profile, m) ? " (native)" : ""}</option>)}
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div><Label hint={d.framing ? <ModeChip native={false} /> : undefined}>Framing</Label>
              <Select aria-label="Framing" value={d.framing || ""} onChange={(e) => set({ framing: e.target.value })}><option value="">none</option>{FRAMINGS.map((m) => <option key={m} value={m}>{nice(m)}</option>)}</Select></div>
            <div><Label hint={d.angle ? <ModeChip native={false} /> : undefined}>Angle</Label>
              <Select aria-label="Angle" value={d.angle || ""} onChange={(e) => set({ angle: e.target.value })}><option value="">none</option>{ANGLES.map((m) => <option key={m} value={m}>{nice(m)}</option>)}</Select></div>
            <div><Label hint={d.lens_mm ? <ModeChip native={false} /> : undefined}>Lens (mm)</Label>
              <Input aria-label="Lens in millimetres" type="number" min={1} value={d.lens_mm ?? ""} onChange={(e) => set({ lens_mm: e.target.value === "" ? undefined : Number(e.target.value) })} /></div>
            <div><Label hint={d.aperture ? <ModeChip native={false} /> : undefined}>Aperture</Label>
              <Input aria-label="Aperture" placeholder="f/2.0" value={d.aperture || ""} onChange={(e) => set({ aperture: e.target.value })} /></div>
            <div><Label hint={d.speed ? <ModeChip native={false} /> : undefined}>Speed</Label>
              <Select aria-label="Camera speed" value={d.speed || ""} onChange={(e) => set({ speed: e.target.value })}><option value="">none</option>{SPEEDS.map((m) => <option key={m} value={m}>{m}</option>)}</Select></div>
            <div><Label hint={d.motion ? <ModeChip native={false} /> : undefined}>Subject motion (1-10)</Label>
              <Input aria-label="Subject motion from 1 to 10" type="number" min={1} max={10} value={d.motion ?? ""} onChange={(e) => set({ motion: e.target.value === "" ? undefined : Math.min(10, Math.max(1, Math.round(Number(e.target.value)))) })} /></div>
          </div>
          <div><Label hint={d.focus ? <ModeChip native={false} /> : undefined}>Focus</Label>
            <Input aria-label="Focus" placeholder="rack to background at 2s" value={d.focus || ""} onChange={(e) => set({ focus: e.target.value })} /></div>
          <div><Label hint={d.lighting ? <ModeChip native={false} /> : undefined}>Lighting</Label>
            <Input aria-label="Lighting" placeholder="golden hour, soft key from left" value={d.lighting || ""} onChange={(e) => set({ lighting: e.target.value })} /></div>
          {shot.direction && <Button variant="outline" size="sm" onClick={() => onChange({ direction: undefined })}><X size={13} />Clear direction</Button>}
        </>
      ) : (
        <p className="text-xs text-slate-400" data-testid="camera-hidden">This model has no camera control, so the camera options are hidden.{cameraHint ? <> A model that has it: <span className="font-mono">{cameraHint}</span>.</> : null}</p>
      )}

      {canEnd ? (
        <div>
          <Label hint={shot.end_frame ? <ModeChip native /> : undefined}>End frame</Label>
          <Select aria-label="End frame image" value={shot.end_frame || ""} onChange={(e) => onChange({ end_frame: e.target.value || undefined })}>
            <option value="">none</option>{stillOptions}
          </Select>
          {shot.end_frame && stills.includes(shot.end_frame.replace("stills/", "")) && <img src={fileUrl(project, shot.end_frame)} alt={`End frame ${shot.end_frame}`} className="mt-2 h-20 rounded-lg border border-slate-800" />}
        </div>
      ) : (
        <p className="text-xs text-slate-400" data-testid="endframe-hidden">This model cannot use an end frame.{endHint ? <> A model that can: <span className="font-mono">{endHint}</span>.</> : null}</p>
      )}

      {kfMax > 0 ? (
        <div>
          <Label hint={`up to ${kfMax}`}>Keyframes</Label>
          <ul className="space-y-2">
            {keyframes.map((k, i) => (
              <li key={i} className="flex items-center gap-2">
                <Input aria-label={`Keyframe ${i + 1} time in seconds`} className="!w-20" type="number" min={0} step="0.1" value={k.at} onChange={(e) => onChange({ keyframes: keyframes.map((x, j) => (j === i ? { ...x, at: Number(e.target.value) } : x)) })} />
                <Select aria-label={`Keyframe ${i + 1} image`} value={k.image} onChange={(e) => onChange({ keyframes: keyframes.map((x, j) => (j === i ? { ...x, image: e.target.value } : x)) })}>
                  <option value="">choose</option>{stillOptions}
                </Select>
                <button type="button" className="icon-btn !h-8 !w-8" aria-label={`Remove keyframe ${i + 1}`} onClick={() => onChange({ keyframes: keyframes.filter((_, j) => j !== i).length ? keyframes.filter((_, j) => j !== i) : undefined })}><X size={14} /></button>
              </li>
            ))}
          </ul>
          {keyframes.length < kfMax && <Button variant="outline" size="sm" className="mt-2" onClick={() => onChange({ keyframes: [...keyframes, { at: 0.5, image: "" }] })}><Plus size={13} />Add keyframe</Button>}
        </div>
      ) : profile ? (
        <p className="text-xs text-slate-400" data-testid="keyframes-hidden">This model cannot use middle keyframes.{kfHint ? <> A model that can: <span className="font-mono">{kfHint}</span>.</> : null}</p>
      ) : null}
      <p className="text-[0.7rem] text-slate-400">Native: sent to the model as a parameter. Via prompt: written into the prompt as a camera sentence. Save the shot to refresh what the model supports.</p>
    </div>
  );
}
