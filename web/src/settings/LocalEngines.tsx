import { useEffect, useId, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Cpu,
  FileCode,
  HardDrive,
  Layers,
  Plus,
  RefreshCw,
  Sliders,
  Trash2,
  Upload,
} from "lucide-react";
import { api } from "../api";
import { Badge, Button, Card, IconTile, Input, Label, Select } from "../ui";
import { useToast } from "../toast";
import { confirmDialog } from "../dialogs";

export interface WorkflowItem {
  id: string;
  task: string;
  inputs: Record<string, any>;
  profile: {
    durations?: number[];
    resolutions?: string[];
    frames?: { start?: boolean; end?: boolean };
    camera?: { mode?: string };
    [key: string]: any;
  };
  dir?: string;
}

interface ParsedNode {
  nodeId: string;
  classType: string;
  inputs: string[];
}

export default function LocalEnginesSection() {
  const toast = useToast();

  const [workflows, setWorkflows] = useState<WorkflowItem[]>([]);
  const [loading, setLoading] = useState(true);

  // Workflow registration form state
  const [isAdding, setIsAdding] = useState(false);
  const [workflowId, setWorkflowId] = useState("");
  const [task, setTask] = useState("image_to_video");
  const [workflowJsonRaw, setWorkflowJsonRaw] = useState("");
  const [workflowJson, setWorkflowJson] = useState<Record<string, any> | null>(null);
  const [parsedNodes, setParsedNodes] = useState<ParsedNode[]>([]);

  // Field mappings: { [inputName: string]: [nodeId, inputName, transform?] }
  const [promptNode, setPromptNode] = useState("");
  const [promptField, setPromptField] = useState("");

  const [seedNode, setSeedNode] = useState("");
  const [seedField, setSeedField] = useState("");

  const [startFrameNode, setStartFrameNode] = useState("");
  const [startFrameField, setStartFrameField] = useState("");

  const [secondsNode, setSecondsNode] = useState("");
  const [secondsField, setSecondsField] = useState("");
  const [secondsTransform, setSecondsTransform] = useState("frames@16");

  // Profile fields
  const [durationsStr, setDurationsStr] = useState("3, 5");
  const [resolutionsStr, setResolutionsStr] = useState("480p, 720p");
  const [framesStart, setFramesStart] = useState(true);
  const [framesEnd, setFramesEnd] = useState(false);
  const [cameraMode, setCameraMode] = useState("prompt");

  // Validation state
  const [validating, setValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<any | null>(null);
  const [validationError, setValidationError] = useState("");

  // Allowed desktop apps state
  const [allowedApps, setAllowedApps] = useState<string[]>([]);
  const [newAppName, setNewAppName] = useState("");
  const [savingApps, setSavingApps] = useState(false);

  // Accessible IDs
  const wfIdInputId = useId();
  const taskSelectId = useId();
  const jsonUploadId = useId();
  const durationsInputId = useId();
  const resolutionsInputId = useId();
  const cameraModeSelectId = useId();
  const newAppInputId = useId();

  const loadWorkflows = async () => {
    setLoading(true);
    try {
      const res = await api<{ workflows: WorkflowItem[] }>("GET", "/api/comfy/workflows");
      setWorkflows(res.workflows || []);
    } catch (e: any) {
      toast("error", e.message || "Failed to load ComfyUI workflows");
    } finally {
      setLoading(false);
    }
  };

  const loadAllowedApps = async () => {
    try {
      const res = await api<{ apps: string[] }>("GET", "/api/external-apps");
      setAllowedApps(res.apps || []);
    } catch {
      // not available yet
    }
  };

  useEffect(() => {
    void loadWorkflows();
    void loadAllowedApps();
  }, []);

  // Parse uploaded / pasted workflow_api.json
  const handleWorkflowJsonChange = (raw: string) => {
    setWorkflowJsonRaw(raw);
    setValidationResult(null);
    setValidationError("");
    if (!raw.trim()) {
      setWorkflowJson(null);
      setParsedNodes([]);
      return;
    }
    try {
      const parsed = JSON.parse(raw);
      if (typeof parsed !== "object" || parsed === null) {
        throw new Error("Workflow must be an object of nodes");
      }
      setWorkflowJson(parsed);

      const nodes: ParsedNode[] = Object.entries(parsed).map(([nodeId, val]: [string, any]) => ({
        nodeId,
        classType: val?.class_type || "Node",
        inputs: val?.inputs && typeof val.inputs === "object" ? Object.keys(val.inputs) : [],
      }));
      setParsedNodes(nodes);

      // Auto-detect common nodes
      const textNode = nodes.find((n) => /cliptext|prompt|text/i.test(n.classType) && n.inputs.includes("text"));
      if (textNode) {
        setPromptNode(textNode.nodeId);
        setPromptField("text");
      }
      const ksampler = nodes.find((n) => /ksampler|sampler/i.test(n.classType) && n.inputs.includes("seed"));
      if (ksampler) {
        setSeedNode(ksampler.nodeId);
        setSeedField("seed");
      }
      const imgNode = nodes.find((n) => /loadimage|image/i.test(n.classType) && n.inputs.includes("image"));
      if (imgNode) {
        setStartFrameNode(imgNode.nodeId);
        setStartFrameField("image");
      }
    } catch (e: any) {
      setWorkflowJson(null);
      setParsedNodes([]);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      handleWorkflowJsonChange(String(evt.target?.result || ""));
    };
    reader.readAsText(file);
  };

  // Build manifest object from current form state
  const buildManifest = () => {
    const inputs: Record<string, any> = {};
    if (promptNode && promptField) {
      inputs.prompt = [promptNode, promptField];
    }
    if (seedNode && seedField) {
      inputs.seed = [seedNode, seedField];
    }
    if (task.includes("image") && startFrameNode && startFrameField) {
      inputs.start_frame = [startFrameNode, startFrameField];
    }
    if (secondsNode && secondsField) {
      inputs.seconds = secondsTransform
        ? [secondsNode, secondsField, secondsTransform]
        : [secondsNode, secondsField];
    }

    const durations = durationsStr
      .split(",")
      .map((d) => Number(d.trim()))
      .filter((n) => !isNaN(n) && n > 0);

    const resolutions = resolutionsStr
      .split(",")
      .map((r) => r.trim())
      .filter(Boolean);

    const profile = {
      durations: durations.length > 0 ? durations : [3, 5],
      resolutions: resolutions.length > 0 ? resolutions : ["480p", "720p"],
      frames: { start: framesStart, end: framesEnd },
      camera: { mode: cameraMode },
    };

    return {
      id: workflowId.trim().toLowerCase().replace(/[^a-z0-9-]+/g, "-"),
      task,
      inputs,
      profile,
    };
  };

  // Dry-run validate
  const validateWorkflow = async () => {
    if (!workflowJson) {
      toast("error", "Provide valid workflow_api.json before validating.");
      return;
    }
    if (!workflowId.trim()) {
      toast("error", "Workflow ID is required.");
      return;
    }
    setValidating(true);
    setValidationResult(null);
    setValidationError("");
    try {
      const manifest = buildManifest();
      const res = await api<any>("POST", "/api/comfy/workflows/validate", {
        workflow: workflowJson,
        manifest,
      });
      setValidationResult(res);
      toast("ok", "Workflow and manifest mapping validated successfully!");
    } catch (e: any) {
      setValidationError(e.message || "Validation failed");
      toast("error", e.message || "Validation failed");
    } finally {
      setValidating(false);
    }
  };

  // Register workflow
  const registerWorkflow = async () => {
    if (!workflowJson) {
      toast("error", "Provide workflow_api.json.");
      return;
    }
    if (!workflowId.trim()) {
      toast("error", "Workflow ID is required.");
      return;
    }
    try {
      const manifest = buildManifest();
      await api("POST", "/api/comfy/workflows", {
        workflow: workflowJson,
        manifest,
      });
      toast("ok", `Workflow "${manifest.id}" registered successfully.`);
      setIsAdding(false);
      setWorkflowJsonRaw("");
      setWorkflowJson(null);
      setWorkflowId("");
      await loadWorkflows();
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  // Delete workflow
  const deleteWorkflow = async (wf: WorkflowItem) => {
    if (
      !(await confirmDialog(
        `Move ComfyUI workflow "${wf.id}" to trash? It can be restored manually from the trash folder.`,
        { title: "Delete Workflow", ok: "Move to Trash", danger: true }
      ))
    )
      return;
    try {
      await api("DELETE", `/api/comfy/workflows/${encodeURIComponent(wf.id)}`);
      toast("ok", `Workflow "${wf.id}" deleted.`);
      await loadWorkflows();
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  // Save allowed desktop apps
  const addApp = async () => {
    const clean = newAppName.trim();
    if (!clean) return;
    if (clean.length > 100 || clean.includes("/") || clean.includes("\\")) {
      toast("error", "Application name must be under 100 characters and contain no path slashes.");
      return;
    }
    if (allowedApps.includes(clean)) {
      toast("info", "Application is already in the allowed list.");
      return;
    }
    const next = [...allowedApps, clean].sort();
    setSavingApps(true);
    try {
      const res = await api<{ apps: string[] }>("PUT", "/api/external-apps", { apps: next });
      setAllowedApps(res.apps);
      setNewAppName("");
      toast("ok", `Added "${clean}" to allowed desktop apps.`);
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setSavingApps(false);
    }
  };

  const removeApp = async (appToRemove: string) => {
    const next = allowedApps.filter((a) => a !== appToRemove);
    setSavingApps(true);
    try {
      const res = await api<{ apps: string[] }>("PUT", "/api/external-apps", { apps: next });
      setAllowedApps(res.apps);
      toast("ok", `Removed "${appToRemove}".`);
    } catch (e: any) {
      toast("error", e.message);
    } finally {
      setSavingApps(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="local-engines-section">
      {/* ComfyUI Workflows Card */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <IconTile tone="violet"><HardDrive size={15} /></IconTile>
            Local Engines: ComfyUI Workflows
          </span>
        }
        sub="Register local ComfyUI workflow templates with API node mappings and inspect their derived capability profiles."
        right={
          <Button
            variant="pink"
            size="sm"
            data-testid="add-workflow-btn"
            aria-label="Add new ComfyUI workflow"
            onClick={() => setIsAdding(!isAdding)}
          >
            <Plus size={14} /> {isAdding ? "Close Form" : "Add Workflow"}
          </Button>
        }
      >
        {/* Register Workflow Form */}
        {isAdding && (
          <div className="mb-6 rounded-2xl border border-pink/30 bg-pink/5 p-4 space-y-4" data-testid="add-workflow-form">
            <div className="flex items-center justify-between border-b border-pink/20 pb-3">
              <h4 className="text-sm font-bold text-slate-100 flex items-center gap-2">
                <FileCode size={16} className="text-pink" /> Register ComfyUI Workflow Template
              </h4>
              <Badge tone="pink">API JSON + Manifest</Badge>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label hint={<span className="text-slate-400">Lowercase slug</span>}>
                  Workflow Identifier (ID)
                </Label>
                <Input
                  id={wfIdInputId}
                  aria-label="Workflow ID slug"
                  placeholder="e.g. wan-i2v or sd-turbo"
                  value={workflowId}
                  onChange={(e) => setWorkflowId(e.target.value)}
                />
              </div>

              <div>
                <Label>Generation Task</Label>
                <Select
                  id={taskSelectId}
                  aria-label="Workflow generation task"
                  value={task}
                  onChange={(e) => setTask(e.target.value)}
                >
                  <option value="image_to_video">image_to_video (Image + Prompt &rarr; Video)</option>
                  <option value="text_to_video">text_to_video (Prompt &rarr; Video)</option>
                  <option value="text_to_image">text_to_image (Prompt &rarr; Image)</option>
                  <option value="image_to_image">image_to_image (Image &rarr; Image Edit)</option>
                </Select>
              </div>
            </div>

            {/* Workflow JSON Upload */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <Label hint={<span className="text-slate-400">Exported from ComfyUI with "Save (API)"</span>}>
                  workflow_api.json
                </Label>
                <label className="cursor-pointer text-xs font-semibold text-pink hover:underline inline-flex items-center gap-1">
                  <Upload size={13} /> Upload JSON file
                  <input
                    id={jsonUploadId}
                    type="file"
                    accept=".json"
                    className="hidden"
                    aria-label="Upload ComfyUI workflow JSON"
                    onChange={handleFileUpload}
                  />
                </label>
              </div>
              <textarea
                rows={4}
                aria-label="Paste workflow API JSON content"
                placeholder='{"3": {"class_type": "KSampler", "inputs": {...}}, ...}'
                className="field font-mono text-xs w-full"
                value={workflowJsonRaw}
                onChange={(e) => handleWorkflowJsonChange(e.target.value)}
              />
              {parsedNodes.length > 0 && (
                <p className="mt-1 text-xs text-emerald-400">
                  Detected {parsedNodes.length} nodes in API JSON. Configure field mappings below.
                </p>
              )}
            </div>

            {/* Field Mappings Dropdowns */}
            {parsedNodes.length > 0 && (
              <div className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-3.5">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-300 block">
                  Field Mappings to ComfyUI Nodes
                </span>

                <div className="grid gap-3 sm:grid-cols-2">
                  {/* Prompt mapping */}
                  <div>
                    <Label hint={<span className="text-slate-400">Text input node</span>}>
                      Prompt Mapping
                    </Label>
                    <div className="flex gap-2">
                      <Select
                        aria-label="Prompt node selector"
                        value={promptNode}
                        onChange={(e) => {
                          setPromptNode(e.target.value);
                          const node = parsedNodes.find((n) => n.nodeId === e.target.value);
                          if (node && node.inputs.length > 0 && !node.inputs.includes(promptField)) {
                            setPromptField(node.inputs[0]);
                          }
                        }}
                      >
                        <option value="">Select node...</option>
                        {parsedNodes.map((n) => (
                          <option key={n.nodeId} value={n.nodeId}>
                            Node {n.nodeId} ({n.classType})
                          </option>
                        ))}
                      </Select>
                      <Select
                        aria-label="Prompt input field selector"
                        value={promptField}
                        onChange={(e) => setPromptField(e.target.value)}
                      >
                        <option value="">Field...</option>
                        {parsedNodes
                          .find((n) => n.nodeId === promptNode)
                          ?.inputs.map((f) => (
                            <option key={f} value={f}>
                              {f}
                            </option>
                          ))}
                      </Select>
                    </div>
                  </div>

                  {/* Seed mapping */}
                  <div>
                    <Label hint={<span className="text-slate-400">Random seed</span>}>
                      Seed Mapping
                    </Label>
                    <div className="flex gap-2">
                      <Select
                        aria-label="Seed node selector"
                        value={seedNode}
                        onChange={(e) => {
                          setSeedNode(e.target.value);
                          const node = parsedNodes.find((n) => n.nodeId === e.target.value);
                          if (node && node.inputs.length > 0 && !node.inputs.includes(seedField)) {
                            setSeedField(node.inputs[0]);
                          }
                        }}
                      >
                        <option value="">Select node...</option>
                        {parsedNodes.map((n) => (
                          <option key={n.nodeId} value={n.nodeId}>
                            Node {n.nodeId} ({n.classType})
                          </option>
                        ))}
                      </Select>
                      <Select
                        aria-label="Seed input field selector"
                        value={seedField}
                        onChange={(e) => setSeedField(e.target.value)}
                      >
                        <option value="">Field...</option>
                        {parsedNodes
                          .find((n) => n.nodeId === seedNode)
                          ?.inputs.map((f) => (
                            <option key={f} value={f}>
                              {f}
                            </option>
                          ))}
                      </Select>
                    </div>
                  </div>

                  {/* Start Frame mapping */}
                  {task.includes("image") && (
                    <div>
                      <Label hint={<span className="text-slate-400">Initial image</span>}>
                        Start Frame Mapping
                      </Label>
                      <div className="flex gap-2">
                        <Select
                          aria-label="Start frame node selector"
                          value={startFrameNode}
                          onChange={(e) => {
                            setStartFrameNode(e.target.value);
                            const node = parsedNodes.find((n) => n.nodeId === e.target.value);
                            if (node && node.inputs.length > 0 && !node.inputs.includes(startFrameField)) {
                              setStartFrameField(node.inputs[0]);
                            }
                          }}
                        >
                          <option value="">Select node...</option>
                          {parsedNodes.map((n) => (
                            <option key={n.nodeId} value={n.nodeId}>
                              Node {n.nodeId} ({n.classType})
                            </option>
                          ))}
                        </Select>
                        <Select
                          aria-label="Start frame input field selector"
                          value={startFrameField}
                          onChange={(e) => setStartFrameField(e.target.value)}
                        >
                          <option value="">Field...</option>
                          {parsedNodes
                            .find((n) => n.nodeId === startFrameNode)
                            ?.inputs.map((f) => (
                              <option key={f} value={f}>
                                {f}
                              </option>
                            ))}
                        </Select>
                      </div>
                    </div>
                  )}

                  {/* Seconds / Frames mapping */}
                  {task.includes("video") && (
                    <div>
                      <Label hint={<span className="text-slate-400">Length / frame count</span>}>
                        Duration Mapping &amp; Transform
                      </Label>
                      <div className="flex gap-2">
                        <Select
                          aria-label="Duration node selector"
                          value={secondsNode}
                          onChange={(e) => {
                            setSecondsNode(e.target.value);
                            const node = parsedNodes.find((n) => n.nodeId === e.target.value);
                            if (node && node.inputs.length > 0 && !node.inputs.includes(secondsField)) {
                              setSecondsField(node.inputs[0]);
                            }
                          }}
                        >
                          <option value="">Select node...</option>
                          {parsedNodes.map((n) => (
                            <option key={n.nodeId} value={n.nodeId}>
                              Node {n.nodeId} ({n.classType})
                            </option>
                          ))}
                        </Select>
                        <Select
                          aria-label="Duration input field selector"
                          value={secondsField}
                          onChange={(e) => setSecondsField(e.target.value)}
                        >
                          <option value="">Field...</option>
                          {parsedNodes
                            .find((n) => n.nodeId === secondsNode)
                            ?.inputs.map((f) => (
                              <option key={f} value={f}>
                                {f}
                              </option>
                            ))}
                        </Select>
                        <Select
                          aria-label="Duration transform function"
                          value={secondsTransform}
                          onChange={(e) => setSecondsTransform(e.target.value)}
                        >
                          <option value="frames@16">frames@16</option>
                          <option value="frames">frames</option>
                          <option value="int">int</option>
                          <option value="">none</option>
                        </Select>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Capability Profile Configuration */}
            <div className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-3.5">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-300 block">
                Capability Profile
              </span>
              <div className="grid gap-3 sm:grid-cols-3">
                <div>
                  <Label>Supported Durations (s)</Label>
                  <Input
                    id={durationsInputId}
                    aria-label="Supported durations separated by commas"
                    placeholder="3, 5"
                    value={durationsStr}
                    onChange={(e) => setDurationsStr(e.target.value)}
                  />
                </div>
                <div>
                  <Label>Supported Resolutions</Label>
                  <Input
                    id={resolutionsInputId}
                    aria-label="Supported resolutions separated by commas"
                    placeholder="480p, 720p"
                    value={resolutionsStr}
                    onChange={(e) => setResolutionsStr(e.target.value)}
                  />
                </div>
                <div>
                  <Label>Camera Control Mode</Label>
                  <Select
                    id={cameraModeSelectId}
                    aria-label="Camera mode capability"
                    value={cameraMode}
                    onChange={(e) => setCameraMode(e.target.value)}
                  >
                    <option value="prompt">prompt (in prompt text)</option>
                    <option value="motion">motion (numerical vector)</option>
                    <option value="none">none (fixed camera)</option>
                  </Select>
                </div>
              </div>

              <div className="flex gap-4 pt-1 text-sm">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    aria-label="Start frame supported"
                    checked={framesStart}
                    onChange={(e) => setFramesStart(e.target.checked)}
                  />
                  <span>Start frame supported</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    aria-label="End frame supported"
                    checked={framesEnd}
                    onChange={(e) => setFramesEnd(e.target.checked)}
                  />
                  <span>End frame supported</span>
                </label>
              </div>
            </div>

            {/* Validation Feedback */}
            {validationResult && (
              <div
                className="flex items-start gap-2 rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-3 text-xs text-emerald-300"
                data-testid="validation-success-chip"
              >
                <CheckCircle2 size={16} className="shrink-0 mt-0.5 text-emerald-400" />
                <div>
                  <b>Dry-Run Validation Passed:</b> Valid mapping verified for workflow "{validationResult.id}".
                  Capability profile resolved: durations [{(validationResult.profile?.durations || []).join(", ")}], resolutions [{(validationResult.profile?.resolutions || []).join(", ")}].
                </div>
              </div>
            )}
            {validationError && (
              <div
                className="flex items-start gap-2 rounded-xl border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-300"
                data-testid="validation-error-chip"
              >
                <AlertCircle size={16} className="shrink-0 mt-0.5 text-red-400" />
                <span>{validationError}</span>
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
              <Button
                variant="outline"
                size="sm"
                data-testid="validate-dry-run-btn"
                aria-label="Validate dry-run workflow mapping"
                disabled={validating || !workflowJson}
                onClick={validateWorkflow}
              >
                <RefreshCw size={13} className={validating ? "animate-spin" : ""} />
                {validating ? "Validating..." : "Validate (Dry Run)"}
              </Button>
              <Button
                variant="pink"
                size="sm"
                data-testid="register-workflow-btn"
                aria-label="Register ComfyUI workflow"
                disabled={!workflowJson || !workflowId.trim()}
                onClick={registerWorkflow}
              >
                <CheckCircle2 size={13} /> Register Workflow
              </Button>
            </div>
          </div>
        )}

        {/* Workflow List */}
        {loading ? (
          <p className="text-sm text-slate-400 py-4 text-center">Loading workflows...</p>
        ) : workflows.length === 0 ? (
          <p className="rounded-xl border border-dashed border-slate-800 p-6 text-center text-sm text-slate-400">
            No local ComfyUI workflows registered yet. Click "Add Workflow" to register an API JSON and manifest mapping.
          </p>
        ) : (
          <div className="divide-y divide-slate-800" data-testid="comfy-workflow-list">
            {workflows.map((wf) => (
              <div
                key={wf.id}
                className="flex flex-wrap items-start justify-between gap-4 py-4 text-sm"
                data-testid={`workflow-row-${wf.id}`}
              >
                <div className="min-w-0 space-y-1.5 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-base text-slate-100">{wf.id}</span>
                    <Badge tone="violet">{wf.task}</Badge>
                  </div>

                  {/* Capability profile derived from manifest */}
                  <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400">
                    {wf.profile?.durations && (
                      <span>
                        Durations: <b className="text-slate-200">{wf.profile.durations.join(", ")}s</b>
                      </span>
                    )}
                    {wf.profile?.resolutions && (
                      <span>
                        Resolutions: <b className="text-slate-200">{wf.profile.resolutions.join(", ")}</b>
                      </span>
                    )}
                    {wf.profile?.camera?.mode && (
                      <span>
                        Camera: <b className="text-slate-200">{wf.profile.camera.mode}</b>
                      </span>
                    )}
                    {wf.profile?.frames && (
                      <span>
                        Start Frame: <b className="text-slate-200">{wf.profile.frames.start ? "Yes" : "No"}</b>
                      </span>
                    )}
                  </div>

                  {/* Input mapping preview */}
                  <div className="text-xs text-slate-400 font-mono">
                    Mappings: {Object.entries(wf.inputs || {}).map(([k, v]) => `${k} &rarr; [${Array.isArray(v) ? v.join(", ") : v}]`).join(" | ")}
                  </div>
                </div>

                <Button
                  variant="outline"
                  size="sm"
                  aria-label={`Delete workflow ${wf.id}`}
                  data-testid={`delete-workflow-${wf.id}`}
                  onClick={() => deleteWorkflow(wf)}
                >
                  <Trash2 size={13} /> Delete
                </Button>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Allowed Desktop Applications Card */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <IconTile tone="lime"><Sliders size={15} /></IconTile>
            Approved Desktop Applications
          </span>
        }
        sub="Applications permitted for the 'Edit externally' workflow (Photoshop, DaVinci Resolve, Audacity, GIMP, Blender)."
      >
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2" data-testid="allowed-apps-list">
            {allowedApps.length === 0 ? (
              <span className="text-xs text-slate-400 italic">No specific applications restricted; default system apps apply.</span>
            ) : (
              allowedApps.map((app) => (
                <span
                  key={app}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-xs font-semibold text-slate-200"
                  data-testid={`allowed-app-chip-${app}`}
                >
                  {app}
                  <button
                    type="button"
                    aria-label={`Remove application ${app}`}
                    className="text-slate-400 hover:text-red-400 ml-1"
                    onClick={() => removeApp(app)}
                  >
                    &times;
                  </button>
                </span>
              ))
            )}
          </div>

          <div className="flex gap-2">
            <Input
              id={newAppInputId}
              aria-label="New application name"
              placeholder="e.g. Photoshop or DaVinci Resolve"
              className="flex-1"
              value={newAppName}
              onChange={(e) => setNewAppName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addApp()}
            />
            <Button
              variant="primary"
              size="sm"
              data-testid="add-allowed-app-btn"
              aria-label="Add allowed application"
              disabled={savingApps || !newAppName.trim()}
              onClick={addApp}
            >
              <Plus size={13} /> Add Application
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
