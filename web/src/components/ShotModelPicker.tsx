import { useEffect, useState } from "react";
import { Select } from "../ui";
import { settingsApi } from "../settings/client";
import type { CapabilityModel } from "../settings/types";

export const capChips = (m: CapabilityModel) => {
  const p = m.profile;
  return [
    p.frames.end ? "End frame" : "No end frame",
    `Refs ${p.references.max}`,
    p.durations.length ? `${p.durations.join("/")}s` : "Any duration",
    `Camera ${p.camera.mode}`,
    p.audio === "none" ? "No audio" : p.audio === "always" ? "Audio always" : "Audio optional",
  ];
};

/** Pick the model a shot uses: only enabled video models whose tasks fit the shot, each with its price and capability chips. The choice is saved with the shot (Save), and every price is still quoted and approved by a human. */
export default function ShotModelPicker({ current, imageToVideo, onPick }: { current: string; imageToVideo: boolean; onPick: (ref: string) => void }) {
  const [models, setModels] = useState<CapabilityModel[] | null>(null);
  useEffect(() => { settingsApi.capabilities("video").then((r) => setModels(r.models)).catch(() => setModels([])); }, []);
  const task = imageToVideo ? "image_to_video" : "text_to_video";
  const fits = (models || []).filter((m) => !m.profile.tasks.length || m.profile.tasks.includes(task));
  const sel = fits.find((m) => current === m.id || current === `${m.provider}|${m.id}`);
  const value = sel ? `${sel.provider}|${sel.id}` : "";
  return (
    <div data-testid="shot-model-picker">
      <label className="mb-1 block text-xs font-semibold text-slate-300" htmlFor="shot-model">Model</label>
      <Select id="shot-model" value={value} onChange={(e) => e.target.value && onPick(e.target.value)} aria-label="Model for this shot">
        {!sel && <option value="">{current ? `${current.split("/").pop()} (not in your enabled models)` : "choose a model"}</option>}
        {fits.map((m) => <option key={`${m.provider}|${m.id}`} value={`${m.provider}|${m.id}`}>{m.name} - {m.price ?? "no price"}</option>)}
      </Select>
      {models && !fits.length && <p className="mt-1 text-xs text-slate-400">No enabled video model supports {task.replace(/_/g, " ")}. Add one in Settings.</p>}
      {sel && <div className="mt-1.5 flex flex-wrap gap-1" aria-label="Model capabilities">{capChips(sel).map((c) => <span key={c} className="tag !px-1.5 !py-0.5 !text-[0.65rem]">{c}</span>)}</div>}
    </div>
  );
}
