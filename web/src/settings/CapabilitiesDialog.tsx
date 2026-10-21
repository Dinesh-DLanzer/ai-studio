import { useEffect, useState } from "react";
import { Button, Input, Label, Modal, Select } from "../ui";
import { useToast } from "../toast";
import { settingsApi } from "./client";
import type { Capability, CapabilityModel, CapabilityProfile, Task } from "./types";

export interface CapTarget { provider: string; provider_label?: string; model: string; capability: Capability; }

const SOURCE: Record<CapabilityProfile["source"], string> = { user: "Your override", provider_api: "Provider API (cached)", builtin: "Built-in catalog", default: "Default (nobody described this model)" };
const TASKS: Record<string, Task[]> = {
  video: ["text_to_video", "image_to_video", "video_extend", "video_to_video", "upscale", "reframe", "motion_transfer", "lipsync"],
  image: ["text_to_image", "image_edit", "upscale"],
};
const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** View where a model's capabilities come from and override them (saved to settings/models.json "capabilities"; the server validates the profile). Nothing here spends money. */
export default function CapabilitiesDialog({ target, onClose, onSaved }: { target: CapTarget | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [m, setM] = useState<CapabilityModel | null>(null); const [loadErr, setLoadErr] = useState("");
  const [tasks, setTasks] = useState<string[]>([]); const [durations, setDurations] = useState(""); const [resolutions, setResolutions] = useState("");
  const [ratios, setRatios] = useState(""); const [audio, setAudio] = useState<CapabilityProfile["audio"]>("none");
  const [start, setStart] = useState(true); const [end, setEnd] = useState(false); const [keyframes, setKeyframes] = useState("0");
  const [refMax, setRefMax] = useState("0"); const [camMode, setCamMode] = useState<CapabilityProfile["camera"]["mode"]>("prompt");
  const [native, setNative] = useState(""); const [param, setParam] = useState("");
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);

  const fill = (p: CapabilityProfile) => {
    setTasks(p.tasks); setDurations(p.durations.join(", ")); setResolutions(p.resolutions.join(", ")); setRatios(p.aspect_ratios.join(", ")); setAudio(p.audio);
    setStart(p.frames.start); setEnd(p.frames.end); setKeyframes(String(p.frames.keyframes)); setRefMax(String(p.references.max));
    setCamMode(p.camera.mode); setNative(p.camera.native.join(", ")); setParam(p.camera.param || "");
  };
  useEffect(() => {
    setM(null); setErr(""); setLoadErr("");
    if (!target) return;
    let live = true;
    settingsApi.capabilities(target.capability).then((r) => {
      if (!live) return;
      const found = r.models.find((x) => x.provider === target.provider && x.id === target.model);
      if (found) { setM(found); fill(found.profile); } else setLoadErr("This model is not listed by its provider yet, so its profile cannot be shown.");
    }).catch((e: Error) => live && setLoadErr(e.message));
    return () => { live = false; };
  }, [target]);

  const flip = (t: string) => setTasks((a) => (a.includes(t) ? a.filter((x) => x !== t) : [...a, t]));

  const save = async () => {
    if (!m || !target) return;
    const p = m.profile, nums = list(durations).map(Number);
    if (nums.some((n) => !Number.isInteger(n) || n <= 0)) return setErr("Durations are whole seconds, separated by commas.");
    const kf = Number(keyframes), rm = Number(refMax);
    if (!Number.isInteger(kf) || kf < 0 || !Number.isInteger(rm) || rm < 0) return setErr("Keyframes and the reference maximum are whole numbers, 0 or more.");
    const next = {
      tasks, durations: nums, resolutions: list(resolutions), aspect_ratios: list(ratios), audio,
      frames: { start, end, keyframes: kf }, references: { max: rm, roles: p.references.roles },
      camera: { mode: camMode, native: list(native), param: param.trim() || null },
    };
    const cur = p as unknown as Record<string, unknown>;
    const changed = Object.fromEntries(Object.entries(next).filter(([k, v]) => !same(v, cur[k]))) as Partial<CapabilityProfile>;
    if (!Object.keys(changed).length) return setErr("Nothing changed.");
    setErr(""); setBusy(true);
    try { await settingsApi.putCapability(target.provider, target.model, { ...(m.override || {}), ...changed }); toast("ok", `Saved capabilities for ${target.model}`); onSaved(); onClose(); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };
  const reset = async () => {
    if (!target) return;
    setBusy(true);
    try { await settingsApi.deleteCapability(target.provider, target.model); toast("ok", `Removed your override for ${target.model}`); onSaved(); onClose(); }
    catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <Modal open={!!target} onClose={onClose} title="Model capabilities">
      {target && (
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void save(); }} data-testid="cap-dialog">
          <p className="text-sm text-slate-300">What <span className="font-mono text-slate-100">{target.model}</span>{target.provider_label ? <> on {target.provider_label}</> : null} can do. This decides which options appear on a shot and what a request is refused for.</p>
          {loadErr && <p role="alert" className="text-sm text-red-300">{loadErr}</p>}
          {m && (
            <>
              <p className="text-xs text-slate-400" data-testid="cap-source">Source: <b>{SOURCE[m.profile.source]}</b>{m.profile.verified_at ? `, verified ${m.profile.verified_at}` : ""}{m.profile.note ? `. ${m.profile.note}` : ""}</p>
              <fieldset><legend className="mb-1 text-xs font-semibold text-slate-300">Tasks</legend>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-300">
                  {(TASKS[target.capability] || []).map((t) => <label key={t} className="flex items-center gap-2"><input type="checkbox" checked={tasks.includes(t)} onChange={() => flip(t)} /> {t.replace(/_/g, " ")}</label>)}
                </div></fieldset>
              <div className="grid gap-3 sm:grid-cols-3">
                <div><Label>Durations (s)</Label><Input aria-label="Durations in seconds" placeholder="4, 6, 8" value={durations} onChange={(e) => setDurations(e.target.value)} /></div>
                <div><Label>Resolutions</Label><Input aria-label="Resolutions" placeholder="720p, 1080p" value={resolutions} onChange={(e) => setResolutions(e.target.value)} /></div>
                <div><Label>Aspect ratios</Label><Input aria-label="Aspect ratios" placeholder="16:9, 9:16" value={ratios} onChange={(e) => setRatios(e.target.value)} /></div>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <div><Label>Audio</Label><Select aria-label="Audio support" value={audio} onChange={(e) => setAudio(e.target.value as CapabilityProfile["audio"])}><option value="none">none</option><option value="optional">optional</option><option value="always">always</option></Select></div>
                <div><Label>Reference images (max)</Label><Input aria-label="Reference images maximum" type="number" min={0} value={refMax} onChange={(e) => setRefMax(e.target.value)} /></div>
                <div><Label>Middle keyframes (max)</Label><Input aria-label="Keyframes maximum" type="number" min={0} value={keyframes} onChange={(e) => setKeyframes(e.target.value)} /></div>
              </div>
              <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-slate-300">
                <label className="flex items-center gap-2"><input type="checkbox" checked={start} onChange={(e) => setStart(e.target.checked)} /> Start frame</label>
                <label className="flex items-center gap-2"><input type="checkbox" checked={end} onChange={(e) => setEnd(e.target.checked)} /> End frame</label>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <div><Label>Camera control</Label><Select aria-label="Camera control mode" value={camMode} onChange={(e) => setCamMode(e.target.value as CapabilityProfile["camera"]["mode"])}><option value="native">native (API parameter)</option><option value="prompt">via prompt</option><option value="none">none</option></Select></div>
                <div><Label>Native moves</Label><Input aria-label="Native camera moves" placeholder="dolly_in, pan_left" value={native} onChange={(e) => setNative(e.target.value)} disabled={camMode !== "native"} /></div>
                <div><Label>API parameter</Label><Input aria-label="Camera API parameter" placeholder="camera_control" value={param} onChange={(e) => setParam(e.target.value)} disabled={camMode !== "native"} /></div>
              </div>
              <p className="text-xs text-slate-400">Only the fields you change are saved as your override. An override never lets a request skip a spend approval.</p>
            </>
          )}
          {err && <p role="alert" className="text-sm text-red-300">{err}</p>}
          <div className="flex flex-wrap justify-end gap-2">
            {m?.override && <Button variant="outline" className="mr-auto" disabled={busy} onClick={() => void reset()}>Reset my override</Button>}
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button variant="primary" type="submit" disabled={busy || !m}>{busy ? "Saving..." : "Save capabilities"}</Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
