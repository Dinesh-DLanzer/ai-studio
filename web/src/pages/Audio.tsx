import { useEffect, useId, useState } from "react";
import {
  FileText,
  Languages,
  Mic,
  Music,
  Play,
  Save,
  Sliders,
  Sparkles,
  Subtitles,
  Volume2,
  Wand2,
  Waves,
} from "lucide-react";
import { api } from "../api";
import { Badge, Button, Card, IconTile, Input, Label, PageHeader, Select } from "../ui";
import { useToast } from "../toast";
import BatchPlanModal from "../components/BatchPlanModal";
import { useBatchPipeline, type Plan } from "../hooks/useBatchPipeline";
import type { TabProps } from "../ProjectPage";
import type { Proposal } from "../types";

interface Voice {
  id: string;
  name: string;
  provider?: string;
  gender?: string;
  language?: string;
}

interface CaptionCue {
  text: string;
  start: number;
  end: number;
}

interface CaptionPreviewResult {
  shot: string;
  script: string;
  source: string;
  duration: number;
  cues: CaptionCue[];
}

const DEFAULT_VOICES: Voice[] = [
  { id: "alloy", name: "Alloy (Neutral)", provider: "openai", gender: "neutral" },
  { id: "echo", name: "Echo (Warm)", provider: "openai", gender: "male" },
  { id: "fable", name: "Fable (Expressive)", provider: "openai", gender: "male" },
  { id: "onyx", name: "Onyx (Deep)", provider: "openai", gender: "male" },
  { id: "nova", name: "Nova (Energetic)", provider: "openai", gender: "female" },
  { id: "shimmer", name: "Shimmer (Clear)", provider: "openai", gender: "female" },
  { id: "21m00Tcm4TlvDq8ikWAM", name: "Rachel (Calm)", provider: "elevenlabs", gender: "female" },
  { id: "AZnzlk1XvdvUeBnXmlld", name: "Domi (Strong)", provider: "elevenlabs", gender: "female" },
  { id: "EXAVITQu4vr4xnSDxMaL", name: "Bella (Soft)", provider: "elevenlabs", gender: "female" },
  { id: "ErXwobaYiN019PkySvjV", name: "Antoni (Smooth)", provider: "elevenlabs", gender: "male" },
  { id: "ananya", name: "Ananya (Tamil & Indian English)", provider: "sarvam", language: "ta-IN" },
  { id: "aravind", name: "Aravind (Tamil & Indian English)", provider: "sarvam", language: "ta-IN" },
];

export function AudioTab({ o, name, load, openProposal, running }: TabProps) {
  const toast = useToast();
  const pipe = useBatchPipeline({
    project: name,
    running,
    reloadAll: load,
    load: async () => { await load(); },
  });

  // Voice picker state
  const [voices, setVoices] = useState<Voice[]>(DEFAULT_VOICES);
  const [selectedVoice, setSelectedVoice] = useState<string>("alloy");
  const [customVoiceId, setCustomVoiceId] = useState<string>("");
  const [isCloned, setIsCloned] = useState<boolean>(false);
  const [cloneSubject, setCloneSubject] = useState<string>("");
  const [savingVoice, setSavingVoice] = useState<boolean>(false);

  // Active audio tool tab
  const [activeTool, setActiveTool] = useState<"music" | "sfx" | "lipsync" | "transcribe">("music");

  // Tool form inputs
  const [musicPrompt, setMusicPrompt] = useState<string>("Cinematic ambient acoustic backdrop, gentle tempo");
  const [musicSeconds, setMusicSeconds] = useState<number>(30);

  const [sfxTarget, setSfxTarget] = useState<string>(o.shots.shots[0]?.id || "s01");
  const [sfxPrompt, setSfxPrompt] = useState<string>("Gentle footsteps on wood and atmospheric breeze");
  const [sfxSeconds, setSfxSeconds] = useState<number>(3);

  const [lipsyncTarget, setLipsyncTarget] = useState<string>(o.shots.shots[0]?.id || "s01");
  const [lipsyncVideo, setLipsyncVideo] = useState<string>(`clips/${o.shots.shots[0]?.id || "s01"}.mp4`);
  const [lipsyncAudio, setLipsyncAudio] = useState<string>(`audio/vo/${o.shots.shots[0]?.id || "s01"}.mp3`);

  const [transcribeSource, setTranscribeSource] = useState<string>(`audio/vo/${o.shots.shots[0]?.id || "s01"}.mp3`);

  // Captions preview state
  const [captionShot, setCaptionShot] = useState<string>(o.shots.shots[0]?.id || "s01");
  const [captionDuration, setCaptionDuration] = useState<number>(4);
  const [captionData, setCaptionData] = useState<CaptionPreviewResult | null>(null);
  const [captionLoading, setCaptionLoading] = useState<boolean>(false);

  // Loudness / Ducking mix options from edit.json
  const [loudness, setLoudness] = useState<number | null>(-14);
  const [duck, setDuck] = useState<boolean>(true);
  const [denoise, setDenoise] = useState<boolean>(false);
  const [savingMix, setSavingMix] = useState<boolean>(false);

  // Accessible IDs
  const voiceSelectId = useId();
  const customVoiceIdField = useId();
  const cloneSubjectId = useId();
  const musicPromptId = useId();
  const musicSecondsId = useId();
  const sfxTargetId = useId();
  const sfxPromptId = useId();
  const sfxSecondsId = useId();
  const lipsyncTargetId = useId();
  const lipsyncVideoId = useId();
  const lipsyncAudioId = useId();
  const transcribeSourceId = useId();
  const captionShotId = useId();
  const captionDurationId = useId();
  const loudnessId = useId();

  // Load voices and initial settings
  useEffect(() => {
    let alive = true;
    api<{ voices: Voice[] }>("GET", "/api/voices")
      .then((r) => {
        if (alive && r.voices && r.voices.length > 0) {
          setVoices(r.voices);
        }
      })
      .catch(() => {
        // Fallback to presets if /api/voices is not reachable
      });

    // Load brief for project default voice
    api<any>("GET", `/api/projects/${name}/brief`)
      .then((b) => {
        if (alive && b?.voice) {
          const v = b.voice;
          if (typeof v === "string") {
            setSelectedVoice(v);
          } else if (v.voice_id) {
            setSelectedVoice(v.voice_id);
            if (v.cloned) setIsCloned(true);
            if (v.subject) setCloneSubject(v.subject);
          }
        }
      })
      .catch(() => {});

    // Load edit.json for loudness & ducking settings
    api<any>("GET", `/api/projects/${name}/edit`)
      .then((ed) => {
        if (alive && ed?.edit) {
          const m = ed.edit.audio || ed.edit.mix || {};
          if (m.loudness !== undefined) setLoudness(m.loudness);
          if (m.duck !== undefined) setDuck(Boolean(m.duck));
          if (m.denoise !== undefined) setDenoise(Boolean(m.denoise));
        }
      })
      .catch(() => {});

    return () => { alive = false; };
  }, [name]);

  // Load caption preview when target shot changes
  const fetchCaptionPreview = async (shotId: string, dur: number) => {
    setCaptionLoading(true);
    try {
      const res = await api<CaptionPreviewResult>(
        "GET",
        `/api/projects/${name}/captions/preview?shot=${encodeURIComponent(shotId)}&duration=${dur}`
      );
      setCaptionData(res);
    } catch (e: any) {
      setCaptionData(null);
      toast("error", e.message || "Failed to load caption preview");
    } finally {
      setCaptionLoading(false);
    }
  };

  useEffect(() => {
    if (captionShot) {
      const sh = o.shots.shots.find((s) => s.id === captionShot);
      const d = sh?.seconds || 4;
      setCaptionDuration(d);
      void fetchCaptionPreview(captionShot, d);
    }
  }, [captionShot, o.shots.shots]);

  const activeVoiceId = customVoiceId.trim() || selectedVoice;

  // Save project voice in brief.json
  const saveProjectVoice = async () => {
    setSavingVoice(true);
    try {
      const existing = await api<any>("GET", `/api/projects/${name}/brief`).catch(() => ({}));
      const updated = {
        ...existing,
        voice: {
          voice_id: activeVoiceId,
          provider: voices.find((v) => v.id === activeVoiceId)?.provider || "openai",
          cloned: isCloned,
          subject: isCloned ? cloneSubject.trim() : undefined,
        },
      };
      await api("PUT", `/api/projects/${name}/brief`, updated);
      toast("ok", `Project voice saved: ${activeVoiceId}`);
      await load();
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setSavingVoice(false);
    }
  };

  // Plan Voiceover Batch
  const planVoiceover = async () => {
    try {
      const plan = await api<Plan>("POST", `/api/projects/${name}/voiceover/plan`, {
        voice: {
          voice_id: activeVoiceId,
          cloned: isCloned,
          subject: isCloned ? cloneSubject.trim() : activeVoiceId,
        },
      });
      pipe.setPlan(plan);
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  // Create single tool proposal and forward to existing shared approve dialog
  const proposeTool = async (task: "tts" | "music" | "sfx" | "lipsync" | "transcribe", target: string, options: Record<string, any>) => {
    try {
      const prop = await api<Proposal>("POST", `/api/projects/${name}/audio/tool`, {
        task,
        target,
        options,
      });
      if (openProposal) {
        openProposal(prop);
      } else {
        toast("ok", `Proposal created for ${task}. Review and approve it in the costs tab.`);
      }
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  // Save export mix settings (loudness and ducking)
  const saveMixSettings = async () => {
    setSavingMix(true);
    try {
      const res = await api<any>("GET", `/api/projects/${name}/edit`);
      const editDoc = res.edit || {};
      const nextAudio = {
        ...(editDoc.audio || {}),
        loudness: loudness !== null ? loudness : undefined,
        duck: duck ? true : undefined,
        denoise: denoise ? true : undefined,
      };
      await api("PUT", `/api/projects/${name}/edit`, {
        ...editDoc,
        audio: nextAudio,
      });
      toast("ok", "Export mix settings saved.");
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setSavingMix(false);
    }
  };

  const voicedShots = o.shots.shots.filter(
    (s) => (s.voice_line || "").trim() && s.voice_mode !== "silent"
  );

  return (
    <div className="space-y-6 animate-fade-up" data-testid="audio-page">
      <PageHeader
        title="Audio Studio"
        accent="Voiceover & Sound"
        sub="Plan voiceover per shot, add lip sync and music beds, preview timed captions, and configure loudness export."
        icon={<Volume2 size={24} />}
        right={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="pink"
              onClick={planVoiceover}
              data-testid="voiceover-plan-btn"
              disabled={voicedShots.length === 0}
              aria-label="Plan voiceover batch for voiced shots"
            >
              <Wand2 size={15} />
              Plan Voiceover Batch ({voicedShots.length} shots)
            </Button>
          </div>
        }
      />

      {/* Voice Picker Card */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <IconTile tone="pink"><Mic size={15} /></IconTile>
            Voice Selection &amp; Profile
          </span>
        }
        sub="Choose the speaker voice used for shot voiceovers and dialogue."
      >
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <Label hint={<span className="text-slate-400 font-mono text-[11px]">{activeVoiceId}</span>}>
              Preset Voice
            </Label>
            <Select
              id={voiceSelectId}
              aria-label="Preset Voice selection"
              value={selectedVoice}
              onChange={(e) => {
                setSelectedVoice(e.target.value);
                setCustomVoiceId("");
              }}
            >
              {voices.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name} ({v.provider || "standard"}) {v.language ? `· ${v.language}` : ""}
                </option>
              ))}
            </Select>
          </div>

          <div>
            <Label hint={<span className="text-slate-400">Optional custom provider voice ID</span>}>
              Custom Voice ID
            </Label>
            <Input
              id={customVoiceIdField}
              aria-label="Custom Voice ID"
              placeholder="e.g. 21m00Tcm4TlvDq8ikWAM or custom_speaker"
              value={customVoiceId}
              onChange={(e) => setCustomVoiceId(e.target.value)}
            />
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-800/80 pt-4">
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                aria-label="Voice clone checkbox"
                checked={isCloned}
                onChange={(e) => setIsCloned(e.target.checked)}
                className="rounded border-slate-700 bg-slate-900"
              />
              <span className="text-slate-200">Cloned voice</span>
            </label>

            {isCloned && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400">Subject:</span>
                <Input
                  id={cloneSubjectId}
                  aria-label="Cloned voice subject name"
                  placeholder="Subject name"
                  className="!w-44 !py-1 !text-xs"
                  value={cloneSubject}
                  onChange={(e) => setCloneSubject(e.target.value)}
                />
              </div>
            )}
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={saveProjectVoice}
            disabled={savingVoice}
            aria-label="Save as default project voice"
          >
            <Save size={13} />
            {savingVoice ? "Saving..." : "Set as Project Voice"}
          </Button>
        </div>
      </Card>

      {/* Per-Shot Voice Line Preview */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <IconTile tone="lime"><FileText size={15} /></IconTile>
            Per-Shot Voice Lines &amp; Cost Hints
          </span>
        }
        sub="Each on-camera and off-camera shot voice line with character count and estimated generation price."
      >
        {o.shots.shots.length === 0 ? (
          <p className="text-sm text-slate-400 py-4 text-center">
            No shots in this project yet. Add scenes and shots in Storyboard first.
          </p>
        ) : (
          <div className="divide-y divide-slate-800/80 overflow-x-auto" data-testid="shot-voice-list">
            {o.shots.shots.map((s) => {
              const line = (s.voice_line || "").trim();
              const chars = line.length;
              const estPrice = chars > 0 ? (chars * 0.000015).toFixed(4) : "0.000";
              const mode = s.voice_mode || (line ? "off-camera" : "silent");
              const isSilent = mode === "silent" || !line;

              return (
                <div
                  key={s.id}
                  className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm"
                  data-testid={`shot-voice-row-${s.id}`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-slate-200">{s.id}</span>
                      <Badge
                        tone={
                          mode === "on-camera" ? "lime" : mode === "off-camera" ? "sky" : "slate"
                        }
                      >
                        {mode}
                      </Badge>
                      <span className="text-xs text-slate-400">
                        {s.seconds || 4}s duration
                      </span>
                    </div>

                    <p className={`mt-1 text-sm ${isSilent ? "italic text-slate-500" : "text-slate-200"}`}>
                      {line ? `"${line}"` : "Silent (no voice line)"}
                    </p>
                  </div>

                  <div className="flex items-center gap-3">
                    <div className="text-right">
                      <span className="block text-xs font-semibold text-slate-300">
                        {chars} chars
                      </span>
                      <span
                        className="block font-mono text-[11px] text-slate-400"
                        title="Estimated TTS cost (~$0.015 per 1,000 characters)"
                      >
                        est. ${estPrice}
                      </span>
                    </div>

                    <Button
                      variant="outline"
                      size="sm"
                      disabled={!line}
                      aria-label={`Test TTS voiceover proposal for shot ${s.id}`}
                      onClick={() =>
                        proposeTool("tts", s.id, {
                          text: line,
                          voice_id: activeVoiceId,
                          cloned: isCloned,
                          voice_subject: isCloned ? cloneSubject : activeVoiceId,
                        })
                      }
                    >
                      <Play size={12} /> Propose VO
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* Audio Tools: Music / SFX / Lip Sync / Transcribe */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <IconTile tone="violet"><Sparkles size={15} /></IconTile>
            Audio Generation Proposals
          </span>
        }
        sub="Create paid proposals for Music, SFX, Lip Sync, or Speech Transcription. Exact price is shown in the approval modal; nothing runs without approval."
      >
        <div className="flex flex-wrap gap-2 border-b border-slate-800 pb-3" role="tablist" aria-label="Audio tools">
          <Button
            variant={activeTool === "music" ? "pink" : "outline"}
            size="sm"
            role="tab"
            aria-selected={activeTool === "music"}
            aria-label="Music Bed proposal form"
            onClick={() => setActiveTool("music")}
          >
            <Music size={13} /> Music Bed
          </Button>
          <Button
            variant={activeTool === "sfx" ? "pink" : "outline"}
            size="sm"
            role="tab"
            aria-selected={activeTool === "sfx"}
            aria-label="Sound Effects SFX proposal form"
            onClick={() => setActiveTool("sfx")}
          >
            <Waves size={13} /> Sound Effects (SFX)
          </Button>
          <Button
            variant={activeTool === "lipsync" ? "pink" : "outline"}
            size="sm"
            role="tab"
            aria-selected={activeTool === "lipsync"}
            aria-label="Lip Sync proposal form"
            onClick={() => setActiveTool("lipsync")}
          >
            <Languages size={13} /> Lip Sync
          </Button>
          <Button
            variant={activeTool === "transcribe" ? "pink" : "outline"}
            size="sm"
            role="tab"
            aria-selected={activeTool === "transcribe"}
            aria-label="Transcription proposal form"
            onClick={() => setActiveTool("transcribe")}
          >
            <Subtitles size={13} /> Transcribe
          </Button>
        </div>

        <div className="mt-4">
          {activeTool === "music" && (
            <div className="space-y-4" data-testid="form-music">
              <p className="text-xs text-slate-400">
                Generate a full background music bed aligned to the mood and rhythm of your video.
              </p>
              <div className="grid gap-3 sm:grid-cols-4">
                <div className="sm:col-span-3">
                  <Label>Music Prompt / Mood</Label>
                  <Input
                    id={musicPromptId}
                    aria-label="Music prompt description"
                    placeholder="e.g. Cinematic orchestral strings building up to an inspiring climax"
                    value={musicPrompt}
                    onChange={(e) => setMusicPrompt(e.target.value)}
                  />
                </div>
                <div>
                  <Label>Duration (seconds)</Label>
                  <Input
                    id={musicSecondsId}
                    aria-label="Music duration in seconds"
                    type="number"
                    min={1}
                    max={300}
                    value={musicSeconds}
                    onChange={(e) => setMusicSeconds(Number(e.target.value) || 10)}
                  />
                </div>
              </div>
              <div className="flex justify-end">
                <Button
                  variant="pink"
                  data-testid="propose-music-btn"
                  aria-label="Propose Music Generation"
                  onClick={() =>
                    proposeTool("music", "music", {
                      prompt: musicPrompt.trim(),
                      requested_seconds: musicSeconds,
                    })
                  }
                >
                  <Sparkles size={14} /> Propose Music
                </Button>
              </div>
            </div>
          )}

          {activeTool === "sfx" && (
            <div className="space-y-4" data-testid="form-sfx">
              <p className="text-xs text-slate-400">
                Create sound effects synchronized with scene action or transitions.
              </p>
              <div className="grid gap-3 sm:grid-cols-4">
                <div>
                  <Label>Target Shot</Label>
                  <Select
                    id={sfxTargetId}
                    aria-label="SFX target shot"
                    value={sfxTarget}
                    onChange={(e) => setSfxTarget(e.target.value)}
                  >
                    {o.shots.shots.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.id} ({s.seconds || 4}s)
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="sm:col-span-2">
                  <Label>SFX Sound Description</Label>
                  <Input
                    id={sfxPromptId}
                    aria-label="SFX sound prompt"
                    placeholder="e.g. Footsteps on autumn leaves, car engine revving"
                    value={sfxPrompt}
                    onChange={(e) => setSfxPrompt(e.target.value)}
                  />
                </div>
                <div>
                  <Label>Duration (seconds)</Label>
                  <Input
                    id={sfxSecondsId}
                    aria-label="SFX duration in seconds"
                    type="number"
                    min={1}
                    max={30}
                    value={sfxSeconds}
                    onChange={(e) => setSfxSeconds(Number(e.target.value) || 2)}
                  />
                </div>
              </div>
              <div className="flex justify-end">
                <Button
                  variant="pink"
                  data-testid="propose-sfx-btn"
                  aria-label="Propose SFX Generation"
                  onClick={() =>
                    proposeTool("sfx", sfxTarget, {
                      prompt: sfxPrompt.trim(),
                      requested_seconds: sfxSeconds,
                    })
                  }
                >
                  <Sparkles size={14} /> Propose SFX
                </Button>
              </div>
            </div>
          )}

          {activeTool === "lipsync" && (
            <div className="space-y-4" data-testid="form-lipsync">
              <p className="text-xs text-slate-400">
                Synchronize on-camera character lips to a generated or uploaded voice track.
              </p>
              <div className="grid gap-3 sm:grid-cols-3">
                <div>
                  <Label>Target On-Camera Shot</Label>
                  <Select
                    id={lipsyncTargetId}
                    aria-label="Lip sync target shot"
                    value={lipsyncTarget}
                    onChange={(e) => {
                      setLipsyncTarget(e.target.value);
                      setLipsyncVideo(`clips/${e.target.value}.mp4`);
                      setLipsyncAudio(`audio/vo/${e.target.value}.mp3`);
                    }}
                  >
                    {o.shots.shots.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.id} ({s.voice_mode || "mode"})
                      </option>
                    ))}
                  </Select>
                </div>
                <div>
                  <Label>Video File</Label>
                  <Input
                    id={lipsyncVideoId}
                    aria-label="Lip sync video file path"
                    value={lipsyncVideo}
                    onChange={(e) => setLipsyncVideo(e.target.value)}
                  />
                </div>
                <div>
                  <Label>Voiceover Audio File</Label>
                  <Input
                    id={lipsyncAudioId}
                    aria-label="Lip sync voiceover audio file path"
                    value={lipsyncAudio}
                    onChange={(e) => setLipsyncAudio(e.target.value)}
                  />
                </div>
              </div>
              <div className="flex justify-end">
                <Button
                  variant="pink"
                  data-testid="propose-lipsync-btn"
                  aria-label="Propose Lip Sync"
                  onClick={() =>
                    proposeTool("lipsync", lipsyncTarget, {
                      video: lipsyncVideo.trim(),
                      audio: lipsyncAudio.trim(),
                    })
                  }
                >
                  <Sparkles size={14} /> Propose Lip Sync
                </Button>
              </div>
            </div>
          )}

          {activeTool === "transcribe" && (
            <div className="space-y-4" data-testid="form-transcribe">
              <p className="text-xs text-slate-400">
                Transcribe dialogue from an audio clip to generate timestamped word-level captions.
              </p>
              <div>
                <Label>Source Audio File</Label>
                <Input
                  id={transcribeSourceId}
                  aria-label="Transcribe source audio file path"
                  placeholder="e.g. audio/vo/s01.mp3 or audio/interview.mp3"
                  value={transcribeSource}
                  onChange={(e) => setTranscribeSource(e.target.value)}
                />
              </div>
              <div className="flex justify-end">
                <Button
                  variant="pink"
                  data-testid="propose-transcribe-btn"
                  aria-label="Propose Transcription"
                  onClick={() =>
                    proposeTool("transcribe", "dialogue", {
                      source: transcribeSource.trim(),
                    })
                  }
                >
                  <Sparkles size={14} /> Propose Transcription
                </Button>
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Caption Preview */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <IconTile tone="sky"><Subtitles size={15} /></IconTile>
            Caption Preview
          </span>
        }
        sub="Read-only cue timing preview: see how the shot voice line is split and paced across the duration."
      >
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <Label>Select Shot</Label>
            <Select
              id={captionShotId}
              aria-label="Select shot for caption preview"
              value={captionShot}
              onChange={(e) => setCaptionShot(e.target.value)}
            >
              {o.shots.shots.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.id} {s.voice_line ? `("${s.voice_line.slice(0, 20)}...")` : "(no voice line)"}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label>Simulated Duration (s)</Label>
            <Input
              id={captionDurationId}
              aria-label="Caption duration in seconds"
              type="number"
              min={1}
              max={60}
              value={captionDuration}
              onChange={(e) => setCaptionDuration(Number(e.target.value) || 4)}
            />
          </div>
          <div className="flex items-end">
            <Button
              variant="outline"
              aria-label="Refresh caption preview"
              onClick={() => fetchCaptionPreview(captionShot, captionDuration)}
              disabled={captionLoading}
            >
              {captionLoading ? "Loading..." : "Update Preview"}
            </Button>
          </div>
        </div>

        <div className="mt-4" data-testid="caption-preview-box">
          {captionData ? (
            <div className="space-y-3 rounded-xl border border-slate-800 bg-slate-950/60 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
                <span>
                  Source: <b>{captionData.source}</b> · Total: <b>{captionData.duration}s</b>
                </span>
                <span>{captionData.cues.length} cue segment(s)</span>
              </div>

              <div className="text-sm font-semibold text-slate-100">
                Full Script: <span className="font-normal text-slate-300">"{captionData.script}"</span>
              </div>

              <div className="mt-2 space-y-1.5">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Timed Subtitle Cues
                </span>
                <ul className="divide-y divide-slate-800/80 rounded-lg border border-slate-800 bg-slate-900/50">
                  {captionData.cues.map((cue, idx) => (
                    <li key={idx} className="flex items-center justify-between gap-3 px-3 py-2 text-xs">
                      <span className="text-slate-200">"{cue.text}"</span>
                      <span className="font-mono text-slate-400">
                        {cue.start.toFixed(2)}s &rarr; {cue.end.toFixed(2)}s
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : (
            <p className="text-xs text-slate-400 italic py-2">
              Select a shot with dialogue or voice line to preview timed caption cues.
            </p>
          )}
        </div>
      </Card>

      {/* Export Mix Options: Loudness & Ducking */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <IconTile tone="lime"><Sliders size={15} /></IconTile>
            Export Mix: Loudness Normalisation &amp; Ducking
          </span>
        }
        sub="Standard two-pass loudness normalisation and music ducking applied locally via ffmpeg during final video export."
      >
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label hint={<span className="text-slate-400">Integrated LUFS target</span>}>
                Loudness Normalisation
              </Label>
              <Select
                id={loudnessId}
                aria-label="Loudness target standard selection"
                value={loudness === null ? "off" : String(loudness)}
                onChange={(e) => {
                  const v = e.target.value;
                  setLoudness(v === "off" ? null : Number(v));
                }}
              >
                <option value="-14">-14 LUFS (Social: YouTube, TikTok, Instagram)</option>
                <option value="-16">-16 LUFS (Podcasts &amp; Web dialogue)</option>
                <option value="-23">-23 LUFS (Broadcast: EBU R128 / TV)</option>
                <option value="off">Off (Keep original mix loudness)</option>
              </Select>
            </div>

            <div className="flex flex-col justify-end gap-2 text-sm">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  aria-label="Duck background music under dialogue"
                  checked={duck}
                  onChange={(e) => setDuck(e.target.checked)}
                  className="rounded border-slate-700 bg-slate-900"
                />
                <span className="text-slate-200">
                  <b>Duck background music</b> under voiceover clips
                </span>
              </label>

              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  aria-label="Apply dialogue noise reduction"
                  checked={denoise}
                  onChange={(e) => setDenoise(e.target.checked)}
                  className="rounded border-slate-700 bg-slate-900"
                />
                <span className="text-slate-200">
                  Dialogue noise reduction (<code className="text-xs">afftdn</code> filter)
                </span>
              </label>
            </div>
          </div>

          <div className="flex items-center justify-between border-t border-slate-800/80 pt-3">
            <span className="text-xs text-slate-400">
              Free and local: executed during the final ffmpeg render pass.
            </span>
            <Button
              variant="outline"
              size="sm"
              aria-label="Save export mix settings"
              onClick={saveMixSettings}
              disabled={savingMix}
            >
              <Save size={13} />
              {savingMix ? "Saving..." : "Save Mix Settings"}
            </Button>
          </div>
        </div>
      </Card>

      {/* The existing shared batch approval dialog */}
      <BatchPlanModal
        plan={pipe.plan}
        mode={o.mode}
        title="Approve Voiceover Batch?"
        onClose={() => pipe.setPlan(null)}
        onApprove={pipe.runAll}
      />
    </div>
  );
}
