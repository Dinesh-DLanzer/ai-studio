import { useEffect, useId, useState } from "react";
import {
  AlertCircle,
  ArrowLeftRight,
  CheckCircle2,
  Clock,
  Download,
  ExternalLink,
  FileCode,
  Film,
  FolderArchive,
  Image as ImageIcon,
  Layers,
  Music,
  Play,
  RefreshCw,
  Sliders,
  Square,
  Subtitles,
  Upload,
} from "lucide-react";
import { api, getToken } from "../api";
import { Badge, Button, Card, IconTile, Input, Label, PageHeader, Select } from "../ui";
import { useToast } from "../toast";
import type { TabProps } from "../ProjectPage";

interface ExportOption {
  key: string;
  label: string;
  sublabel: string;
  format: string;
  tag: string;
  tone: "lime" | "sky" | "pink" | "amber" | "violet" | "slate";
  icon: any;
  filename: (name: string) => string;
  route: (name: string) => string;
}

const EXPORT_OPTIONS: ExportOption[] = [
  {
    key: "otio",
    label: "OpenTimelineIO (.otio)",
    sublabel: "Studio interchange standard schema across animation and VFX suites",
    format: "otio",
    tag: "OTIO",
    tone: "violet",
    icon: FileCode,
    filename: (name) => `${name}.otio`,
    route: (name) => `/api/projects/${encodeURIComponent(name)}/export/otio`,
  },
  {
    key: "otioz",
    label: "OpenTimelineIO Bundle (.otioz)",
    sublabel: "Self-contained zip archive containing OTIO timeline and project media",
    format: "otioz",
    tag: "OTIOZ",
    tone: "violet",
    icon: FolderArchive,
    filename: (name) => `${name}.otioz`,
    route: (name) => `/api/projects/${encodeURIComponent(name)}/export/otioz`,
  },
  {
    key: "xmeml",
    label: "Final Cut Pro 7 XML (.xml)",
    sublabel: "Classic interchange XML supported by Adobe Premiere Pro and DaVinci Resolve",
    format: "xmeml",
    tag: "FCP7 XML",
    tone: "sky",
    icon: Layers,
    filename: (name) => `${name}.xml`,
    route: (name) => `/api/projects/${encodeURIComponent(name)}/export/xmeml`,
  },
  {
    key: "fcpxml",
    label: "Final Cut Pro X XML (.fcpxml)",
    sublabel: "Native FCPXML timeline with cuts, dissolves, audio tracks, and sync",
    format: "fcpxml",
    tag: "FCPXML",
    tone: "lime",
    icon: Layers,
    filename: (name) => `${name}.fcpxml`,
    route: (name) => `/api/projects/${encodeURIComponent(name)}/export/fcpxml`,
  },
  {
    key: "edl",
    label: "CMX 3600 EDL (.edl)",
    sublabel: "Edit Decision List for color grading in DaVinci Resolve and Avid Media Composer",
    format: "edl",
    tag: "EDL",
    tone: "amber",
    icon: Film,
    filename: (name) => `${name}.edl`,
    route: (name) => `/api/projects/${encodeURIComponent(name)}/export/edl`,
  },
  {
    key: "srt",
    label: "SubRip Subtitles (.srt)",
    sublabel: "Universal sidecar caption format for YouTube, Vimeo, and social platforms",
    format: "srt",
    tag: "SRT",
    tone: "slate",
    icon: Subtitles,
    filename: (name) => `${name}.srt`,
    route: (name) => `/api/projects/${encodeURIComponent(name)}/export/srt`,
  },
  {
    key: "vtt",
    label: "WebVTT Captions (.vtt)",
    sublabel: "HTML5 web video text track standard for streaming and browser players",
    format: "vtt",
    tag: "VTT",
    tone: "slate",
    icon: Subtitles,
    filename: (name) => `${name}.vtt`,
    route: (name) => `/api/projects/${encodeURIComponent(name)}/export/vtt`,
  },
  {
    key: "bundle",
    label: "Canva & Google Vids Bundle (.zip)",
    sublabel: "Complete pack: timeline media, captions (SRT/VTT), FCPXML, EDL, and summary",
    format: "bundle",
    tag: "BUNDLE",
    tone: "pink",
    icon: FolderArchive,
    filename: (name) => `${name}-edit-bundle.zip`,
    route: (name) => `/api/projects/${encodeURIComponent(name)}/export/bundle`,
  },
  {
    key: "jsx",
    label: "After Effects ExtendScript (.jsx)",
    sublabel: "Script that auto-imports media and builds comp layers in Adobe After Effects",
    format: "aftereffects.jsx",
    tag: "AE JSX",
    tone: "sky",
    icon: FileCode,
    filename: (name) => `${name}.jsx`,
    route: (name) => `/api/projects/${encodeURIComponent(name)}/export/aftereffects.jsx`,
  },
];

interface ExternalSession {
  file: string;
  app?: string;
  status: string;
}

interface OtioDiff {
  before: any[];
  after: any[];
}

interface OtioImportResponse {
  edit: any;
  ignored: string[];
  diff: OtioDiff;
}

export function InterchangeTab({ o, name, load }: TabProps) {
  const toast = useToast();
  const tok = getToken();

  // External edit state
  const [activeSession, setActiveSession] = useState<ExternalSession | null>(null);
  const [allowedApps, setAllowedApps] = useState<string[]>([]);
  const [selectedApp, setSelectedApp] = useState<string>("");
  const [selectedFile, setSelectedFile] = useState<string>("");
  const [activeCategory, setActiveCategory] = useState<"stills" | "clips" | "audio">("clips");
  const [stopping, setStopping] = useState<boolean>(false);

  // OTIO import state
  const [otioText, setOtioText] = useState<string>("");
  const [previewing, setPreviewing] = useState<boolean>(false);
  const [importResult, setImportResult] = useState<OtioImportResponse | null>(null);
  const [applying, setApplying] = useState<boolean>(false);

  // Load allowed apps and active external session
  const refreshSession = async () => {
    try {
      const res = await api<{ sessions: ExternalSession[] }>("GET", `/api/projects/${name}/external-edit`);
      if (res.sessions && res.sessions.length > 0) {
        setActiveSession(res.sessions[0]);
      } else {
        setActiveSession(null);
      }
    } catch {
      setActiveSession(null);
    }
  };

  useEffect(() => {
    let alive = true;
    api<{ apps: string[] }>("GET", "/api/external-apps")
      .then((r) => {
        if (alive && r.apps) {
          setAllowedApps(r.apps);
          if (r.apps.length > 0 && !selectedApp) {
            setSelectedApp(r.apps[0]);
          }
        }
      })
      .catch(() => {});

    void refreshSession();
    const interval = window.setInterval(() => void refreshSession(), 3000);
    return () => {
      alive = false;
      window.clearInterval(interval);
    };
  }, [name]);

  // Download export format file directly
  const triggerDownload = (opt: ExportOption) => {
    const url = `${opt.route(name)}?token=${encodeURIComponent(tok)}`;
    const a = document.createElement("a");
    a.href = url;
    a.download = opt.filename(name);
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast("ok", `Downloading ${opt.label}...`);
  };

  // Start external edit
  const startExternalEdit = async (file: string) => {
    try {
      await api("POST", `/api/projects/${name}/external-edit`, {
        file,
        app: selectedApp || undefined,
      });
      toast("info", `Opened ${file} for external editing.`);
      await refreshSession();
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  // Stop external edit
  const stopExternalEdit = async () => {
    setStopping(true);
    try {
      await api("POST", `/api/projects/${name}/external-edit/stop`);
      toast("ok", "External editing session stopped.");
      setActiveSession(null);
      await refreshSession();
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setStopping(false);
    }
  };

  // Preview OTIO import
  const previewOtio = async () => {
    if (!otioText.trim()) {
      toast("error", "Paste or upload an OTIO JSON document first.");
      return;
    }
    setPreviewing(true);
    try {
      const res = await api<OtioImportResponse>("POST", `/api/projects/${name}/edit/import-otio`, {
        otio: otioText,
      });
      setImportResult(res);
      toast("ok", "OTIO import preview generated. Review the diff below.");
    } catch (e: any) {
      toast("error", e.message);
      setImportResult(null);
    } finally {
      setPreviewing(false);
    }
  };

  // Handle OTIO file upload
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const content = String(event.target?.result || "");
      setOtioText(content);
    };
    reader.readAsText(file);
  };

  // Confirm and apply OTIO import
  const applyOtioChanges = async () => {
    if (!importResult?.edit) return;
    setApplying(true);
    try {
      await api("PUT", `/api/projects/${name}/edit`, importResult.edit);
      toast("ok", "Timeline successfully updated from OTIO import!");
      setImportResult(null);
      setOtioText("");
      await load();
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setApplying(false);
    }
  };

  // Media items list
  const stills: string[] = o.files.stills || [];
  const clips: string[] = o.files.clips || [];
  const audioFiles: string[] = o.files.audio || [];
  const currentList: string[] = activeCategory === "stills" ? stills : activeCategory === "clips" ? clips : audioFiles;

  const appSelectId = useId();
  const otioFileInputId = useId();
  const otioTextareaId = useId();

  return (
    <div className="space-y-6 animate-fade-up" data-testid="interchange-page">
      <PageHeader
        title="Interchange &amp; Pro Export"
        accent="NLE Workflows"
        sub="Export timeline and cuts to professional NLEs, edit assets externally in desktop apps, and round-trip OpenTimelineIO."
        icon={<ArrowLeftRight size={24} />}
      />

      {/* Active external edit session notification bar */}
      {activeSession && (
        <div
          role="status"
          aria-live="polite"
          className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-sky-500/40 bg-sky-950/40 p-4 text-sm text-sky-200"
          data-testid="external-edit-banner"
        >
          <div className="flex items-center gap-3">
            <span
              className="inline-flex items-center gap-1.5 rounded-full bg-sky-500/20 px-3 py-1 font-mono text-xs font-bold uppercase tracking-wider text-sky-300"
              data-testid="external-edit-status"
            >
              <Clock size={12} className="animate-spin" />
              Waiting for save
            </span>
            <span>
              Editing <code className="rounded bg-sky-900/60 px-1.5 py-0.5 text-white">{activeSession.file}</code>
              {activeSession.app ? ` in ${activeSession.app}` : " in default application"}
            </span>
          </div>

          <Button
            variant="outline"
            size="sm"
            data-testid="stop-external-edit"
            aria-label="Stop external edit session"
            disabled={stopping}
            onClick={stopExternalEdit}
          >
            <Square size={13} /> {stopping ? "Stopping..." : "Stop Session"}
          </Button>
        </div>
      )}

      {/* "Export for…" Hub */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <IconTile tone="lime"><Download size={15} /></IconTile>
            Export for Editing Tools &amp; NLEs
          </span>
        }
        sub="Download timelines, cut points, subtitles, or media packs formatted for Premiere, Resolve, Final Cut, Avid, Canva, and After Effects."
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="export-options-grid">
          {EXPORT_OPTIONS.map((opt) => {
            const Icon = opt.icon;
            return (
              <div
                key={opt.key}
                className="flex flex-col justify-between rounded-xl border border-slate-800 bg-slate-900/50 p-3.5 transition hover:border-slate-700"
                data-testid={`export-card-${opt.key}`}
              >
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <Badge tone={opt.tone}>{opt.tag}</Badge>
                    <Icon size={16} className="text-slate-400" />
                  </div>
                  <h4 className="mt-2 text-sm font-bold text-slate-100">{opt.label}</h4>
                  <p className="mt-1 text-xs text-slate-400 leading-relaxed">{opt.sublabel}</p>
                </div>

                <div className="mt-4 pt-3 border-t border-slate-800/60 flex justify-end">
                  <Button
                    variant="outline"
                    size="sm"
                    aria-label={`Download ${opt.label}`}
                    onClick={() => triggerDownload(opt)}
                  >
                    <Download size={13} /> Download
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      {/* "Edit Externally" on Stills / Clips / Audio */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <IconTile tone="sky"><ExternalLink size={15} /></IconTile>
            Edit Media Externally
          </span>
        }
        sub="Open a project media file in your local desktop editor (Photoshop, Resolve, Audacity, GIMP). AI Studio monitors the file and imports saved versions automatically."
      >
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
          <div className="flex gap-2" role="tablist" aria-label="Media categories">
            <Button
              variant={activeCategory === "clips" ? "pink" : "outline"}
              size="sm"
              role="tab"
              aria-selected={activeCategory === "clips"}
              aria-label="View video clips"
              onClick={() => setActiveCategory("clips")}
            >
              <Film size={13} /> Clips ({clips.length})
            </Button>
            <Button
              variant={activeCategory === "stills" ? "pink" : "outline"}
              size="sm"
              role="tab"
              aria-selected={activeCategory === "stills"}
              aria-label="View image stills"
              onClick={() => setActiveCategory("stills")}
            >
              <ImageIcon size={13} /> Stills ({stills.length})
            </Button>
            <Button
              variant={activeCategory === "audio" ? "pink" : "outline"}
              size="sm"
              role="tab"
              aria-selected={activeCategory === "audio"}
              aria-label="View audio tracks"
              onClick={() => setActiveCategory("audio")}
            >
              <Music size={13} /> Audio ({audioFiles.length})
            </Button>
          </div>

          <div className="flex items-center gap-2">
            <Label hint={<span className="text-slate-400 text-xs">Target App</span>}>
              App:
            </Label>
            <Select
              id={appSelectId}
              aria-label="Select desktop application for external edit"
              className="!w-44 !py-1 !text-xs"
              value={selectedApp}
              onChange={(e) => setSelectedApp(e.target.value)}
            >
              <option value="">Default App</option>
              {allowedApps.map((app) => (
                <option key={app} value={app}>
                  {app}
                </option>
              ))}
            </Select>
          </div>
        </div>

        <div className="mt-4">
          {currentList.length === 0 ? (
            <p className="text-sm text-slate-400 py-6 text-center italic">
              No {activeCategory} found in this project folder yet.
            </p>
          ) : (
            <div className="divide-y divide-slate-800" data-testid="media-external-list">
              {currentList.map((file) => {
                const isEditing = activeSession?.file === file;
                return (
                  <div
                    key={file}
                    className="flex flex-wrap items-center justify-between gap-3 py-2.5 text-sm"
                    data-testid={`media-row-${file.replace(/[/.]/g, "-")}`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <span className="font-mono text-xs text-slate-200 truncate">{file}</span>
                      {isEditing && (
                        <span
                          className="inline-flex items-center gap-1 rounded bg-sky-500/20 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-sky-300"
                          data-testid="status-waiting-for-save"
                        >
                          <Clock size={10} className="animate-spin" /> Waiting for save
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-2">
                      {isEditing ? (
                        <Button
                          variant="danger"
                          size="sm"
                          aria-label={`Stop editing ${file}`}
                          onClick={stopExternalEdit}
                        >
                          <Square size={12} /> Stop
                        </Button>
                      ) : (
                        <Button
                          variant="outline"
                          size="sm"
                          data-testid={`edit-ext-${file.replace(/[/.]/g, "-")}`}
                          aria-label={`Edit ${file} externally`}
                          onClick={() => startExternalEdit(file)}
                        >
                          <ExternalLink size={12} /> Edit Externally
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </Card>

      {/* OTIO Import & Round-Trip Diff Preview */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <IconTile tone="violet"><FileCode size={15} /></IconTile>
            OpenTimelineIO (.otio) Import &amp; Diff Preview
          </span>
        }
        sub="Paste or upload an OTIO timeline exported from an external NLE. Preview changes safely before applying to the project timeline."
      >
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <label className="inline-flex items-center gap-2 cursor-pointer text-xs font-semibold text-slate-300 hover:text-white">
              <Upload size={14} /> Upload .otio file
              <input
                id={otioFileInputId}
                type="file"
                accept=".otio,.json"
                className="hidden"
                aria-label="Upload OTIO file"
                onChange={handleFileUpload}
              />
            </label>
            <span className="text-xs text-slate-400">Preview changes diff-only without saving</span>
          </div>

          <div>
            <Label>OTIO Document JSON</Label>
            <textarea
              id={otioTextareaId}
              aria-label="OTIO JSON document content"
              rows={5}
              placeholder="Paste OTIO JSON here or upload a file..."
              className="field font-mono text-xs w-full"
              value={otioText}
              onChange={(e) => setOtioText(e.target.value)}
            />
          </div>

          <div className="flex justify-end">
            <Button
              variant="pink"
              data-testid="preview-otio-btn"
              aria-label="Preview OTIO import diff"
              disabled={previewing || !otioText.trim()}
              onClick={previewOtio}
            >
              <RefreshCw size={14} className={previewing ? "animate-spin" : ""} />
              {previewing ? "Parsing..." : "Preview OTIO Import"}
            </Button>
          </div>

          {/* Diff View */}
          {importResult && (
            <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 p-4 space-y-4" data-testid="otio-diff-view">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <CheckCircle2 size={16} className="text-emerald-400" />
                  <span className="font-bold text-sm text-slate-100">OTIO Diff Preview</span>
                </div>
                <Badge tone="lime">Validated</Badge>
              </div>

              {importResult.ignored && importResult.ignored.length > 0 && (
                <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-200">
                  <AlertCircle size={14} className="shrink-0 mt-0.5" />
                  <span>
                    Ignored references not found in project: {importResult.ignored.join(", ")}
                  </span>
                </div>
              )}

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <span className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">
                    Current Timeline ({importResult.diff.before.length} clips)
                  </span>
                  <ul className="space-y-1 rounded-lg border border-slate-800 bg-slate-900/60 p-2 text-xs font-mono">
                    {importResult.diff.before.map((clip, i) => (
                      <li key={i} className="flex justify-between text-slate-400">
                        <span>{clip.src || clip.id}</span>
                        <span>
                          {clip.in?.toFixed(1) || 0}s &rarr; {clip.out?.toFixed(1) || 0}s
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>

                <div>
                  <span className="block text-xs font-semibold uppercase tracking-wider text-brand mb-1.5">
                    Imported Timeline ({importResult.diff.after.length} clips)
                  </span>
                  <ul className="space-y-1 rounded-lg border border-brand/30 bg-brand/5 p-2 text-xs font-mono">
                    {importResult.diff.after.map((clip, i) => (
                      <li key={i} className="flex justify-between text-slate-200">
                        <span>{clip.src || clip.id}</span>
                        <span>
                          {clip.in?.toFixed(1) || 0}s &rarr; {clip.out?.toFixed(1) || 0}s
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t border-slate-800/80">
                <Button variant="outline" onClick={() => setImportResult(null)}>
                  Discard Preview
                </Button>
                <Button
                  variant="primary"
                  data-testid="apply-otio-btn"
                  aria-label="Confirm and apply imported timeline changes"
                  disabled={applying}
                  onClick={applyOtioChanges}
                >
                  <CheckCircle2 size={14} />
                  {applying ? "Applying..." : "Confirm & Apply to Timeline"}
                </Button>
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
