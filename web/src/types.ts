export interface Shot {
  id: string; model: string; seconds: number; prompt: string; resolution?: string; audio?: boolean;
  first_frame?: string; note?: string; final_ok?: boolean; final_clip?: string;
}
export interface ImageSpec { id: string; kind: "character" | "background" | "frame" | "other"; out: string; prompt: string; refs: string[]; aspect_ratio?: string; }
export interface Review { verdict: "pass" | "warn" | "fail"; findings: { frame: number; issue: string; severity: string }[]; summary: string; cost?: number; model?: string; advisory?: string; }
export interface ProposalSummary { provider?: string | null; prompt?: string; seconds?: number | null; audio?: boolean | null; first_frame?: string | null; refs?: string[]; file?: string | null; }
export interface Proposal { id: string; kind: string; shot: string; model: string; price: number; status: string; code?: string; expires: number; summary?: ProposalSummary; }
export interface Overview {
  name: string; mode: "test" | "real"; test_pipeline?: boolean; is_test?: boolean;
  shots: { aspect_ratio?: string; audio?: boolean; shots: Shot[] };
  images: { style?: string; images: ImageSpec[] };
  budget: { approved?: boolean; estimate?: number; stop_loss?: number; per_shot?: { id: string; cost: number }[]; stills?: number; clips?: number; failure_rate?: number };
  costs: { used: number; discarded: number; total: number };
  rates?: { models?: Record<string, Record<string, any>> };
  discarded: { file: string; cost: number; reason: string; when: string; original: string }[];
  proposals: Proposal[];
  files: { stills: string[]; clips: string[] };
  reviews: Record<string, Review | null>;
}
export interface ProjectRow { name: string; shots: number; spent: number; estimate: number | null; approved: boolean; test?: boolean; assets?: number; favorite?: boolean; }

export interface BriefField { key: string; label: string; question: string; required: boolean; value: string; }
export interface Brief { fields: BriefField[]; required_done: number; required_total: number; missing: string[]; complete: boolean; }
export interface ChatAttachment { id: string; file: string; colors?: string[]; }
export interface ChatMsg { role: "user" | "assistant"; text: string; ts: string; model?: string; attachments?: ChatAttachment[]; }
export interface ProgressGroup { key: string; label: string; done: number; total: number; }
export interface NextStep { kind: "chat" | "apply-story" | "budget" | "image" | "clip" | "approve" | "export"; label: string; target?: string; }
export interface QueueItem { kind: "image" | "clip"; target: string; label: string; }
export interface Progress { groups: ProgressGroup[]; next: NextStep | null; queue?: QueueItem[]; }
export interface ChatState { messages: ChatMsg[]; pending_story: boolean; brief: Brief; mode: "test" | "real"; test_pipeline?: boolean; reply?: string; progress: Progress; }
export interface AutoTodo { id: string; title: string; done: boolean; progress: string; tab: string; }
export interface ManualTodo { id: string; title: string; done: boolean; }
export interface Todos { auto: AutoTodo[]; manual: ManualTodo[]; }
export interface BudgetEst { estimate: number; stop_loss: number; clips: number; stills: number; footage_seconds: number; failure_rate: number; approved: boolean; per_shot: { id: string; seconds: number; cost: number }[]; }

export interface LanguageInfo { name: string; tested: boolean; script: boolean; }
export interface Finding { where: string; severity: "high" | "medium" | "low"; issue: string; fix: string; source: "rules" | "ai"; }
export interface ScopeStatus { status: "ok" | "warn" | "fail"; findings: Finding[]; rules: string; ai: { status?: string; model?: string; summary?: string; error?: string } | null; ai_stale: boolean; when: string | null; running: boolean; }
export type VerifyMap = Record<"brief" | "story" | "assets" | "shots" | "todos", ScopeStatus>;
export interface CatalogModel { id: string; name: string; free: boolean; prompt_per_m: number; completion_per_m: number; context: number | null; }
export interface AiSettings { chat: { models: string[] }; verify: { models: string[] }; allow_paid: boolean; ai_cap_usd: number; auto_verify: boolean; }

export interface FoundStill { file: string; suggested_id: string; suggested_kind: ImageSpec["kind"]; used_by_shots: boolean; }
