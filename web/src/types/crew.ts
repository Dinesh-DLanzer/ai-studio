// Types for the crew API (server/app.py crew routes; aistudio/crew/{agents,runtime,stages}.py). Fields match the backend JSON.
export type Autonomy = "assist" | "copilot";
export interface CrewLimits { max_steps: number; max_tokens: number; max_llm_usd: number }
export interface CrewAgent {
  id: string; name: string; version: string | number; role: string; tools: string[]; engine?: string;
  prompt: string; limits: CrewLimits; overridden: string[];
}
export interface CrewAgents { agents: CrewAgent[]; hard_limits: CrewLimits }

export interface PlanItem { kind: "image" | "clip"; target: string; label: string; model: string; price: number | null; error?: string }
export interface PlanStage {
  stage: string; label: string; agents: { id: string; version: string | number }[]; prerequisites_missing: string[]; checkpoint: boolean;
  free: boolean; paid_items: PlanItem[]; paid_total: number; unpriced: number; llm_max_usd: number;
}
export interface RunPlan {
  project: string; stages: PlanStage[]; autonomy: Autonomy; paid_total: number; llm: { max_usd: number; ai_cap_usd: number };
  note: string; plan_hash: string;
}

export interface RunStep { n: number; tool: string | null; args: unknown; why: string; status: string; result: string; tokens: number; cost: number }
export interface RunProposal { id: string; kind: string; shot: string; model: string; price: number | null; status: string; hash?: string }
export interface RunChange { doc: string; diff: string }
export interface SuggestedChange { tool: string; args: unknown; why: string; applied: boolean; diff: string }
export interface RunBatch { id?: string; total?: number; status?: string; error?: string; note?: string }

/** One agent working on one task (also what a stage step produces). While the job is queued the server only has a ledger stub. */
export interface AgentRun {
  id: string; project: string; kind?: undefined; agent?: { id: string; version: string | number }; task?: string; autonomy?: Autonomy;
  status: string; started?: number; finished?: number | null; steps: RunStep[]; proposals?: RunProposal[]; suggested_changes?: SuggestedChange[];
  changes?: RunChange[]; batch?: RunBatch | null; llm_usd?: number; tokens?: number; limits?: CrewLimits; summary?: string; error?: string;
  undone?: number | null;
}

export type Decision = "approve_continue" | "edit_continue" | "stop";
export interface CheckpointCard {
  title: string; stage: string; summary: { agent: string; summary: string; status: string }[]; changes: RunChange[];
  suggested_changes: SuggestedChange[]; proposals: RunProposal[]; batch: RunBatch | null; proposed_total: number;
  options: { id: Decision; label: string }[];
}
export interface StageResult { stage: string; status: string; runs: string[]; summary?: { agent: string; summary: string; status: string }[]; card?: CheckpointCard; blocked_by?: string[] }
export interface StageRun {
  id: string; kind: "stage_run"; project: string; stages: string[]; autonomy: Autonomy; checkpoints: Record<string, boolean>; status: string;
  next: number; results: StageResult[]; decisions: { stage: string; decision: Decision; note: string; at: number; after: string }[];
  started: number; finished: number | null; llm_usd: number; error: string;
}
export type CrewRun = AgentRun | StageRun;
export const isStageRun = (r: CrewRun): r is StageRun => r.kind === "stage_run";
export interface RunListItem {
  id: string; agent?: { id: string }; task?: string; autonomy?: Autonomy; status: string; started?: number; finished?: number | null;
  llm_usd?: number; kind?: string; stages?: string[]; steps: number;
}
export interface UndoResult { ok: boolean; restored: string[]; skipped_edited_since: string[]; run: string }

export const ACTIVE = ["running", "queued"];
export const STAGE_BUTTONS = [
  { stage: "write_storyboard", label: "Write storyboard" }, { stage: "cast_and_design", label: "Cast and design" },
  { stage: "create_scenes", label: "Create scenes" }, { stage: "generate_images", label: "Generate images" },
  { stage: "generate_clips", label: "Generate clips" }, { stage: "assemble_edit", label: "Assemble edit" }, { stage: "qa", label: "QA" },
];
