/**
 * AI Studio API Contracts & Schema Definitions
 * Synchronized with backend schemas in `aistudio/schemas/`.
 */

// --- Todos & Tasks ---
export interface TodoItem {
  id: string;
  title: string;
  done: boolean;
}

export interface AutoTodoItem {
  id: string;
  title: string;
  done: boolean;
  progress: string;
  tab: string;
}

export interface TodosDoc {
  auto: AutoTodoItem[];
  manual: TodoItem[];
}

// --- Storyboard, Shots & Assets ---
export interface Shot {
  id: string;
  prompt: string;
  seconds: number;
  model?: string;
  resolution?: string;
  audio?: boolean;
  first_frame?: string;
  final_ok?: boolean;
  final_clip?: string;
  note?: string;
  voice_line?: string;
  voice_mode?: string;
  english?: string;
}

export interface ShotsDoc {
  shots: Shot[];
  language?: string;
  final_resolution: string;
  aspect_ratio: string;
}

export interface ImageAsset {
  id: string;
  kind: "character" | "background" | "frame" | "other" | string;
  out: string;
  prompt: string;
  refs: string[];
  aspect_ratio?: string;
}

export interface ImagesDoc {
  style?: string;
  images: ImageAsset[];
}

// --- Timeline & Video Editor ---
export interface VClipTransition {
  type: string;
  dur: number;
}

export interface VClip {
  id: string;
  src: string;
  in: number;
  out: number;
  volume: number;
  transition: VClipTransition;
}

export interface TextShadow {
  on: boolean;
  color: string;
  blur: number;
}

export interface TText {
  id: string;
  text: string;
  start: number;
  end: number;
  x: number;
  y: number;
  font: string;
  weight: number;
  size: number;
  color: string;
  bg: string | null;
  align: "left" | "center" | "right" | "justify";
  bold: boolean;
  italic: boolean;
  underline: boolean;
  caps: boolean;
  opacity: number;
  shadow: TextShadow;
}

export interface AClip {
  id: string;
  src: string;
  start: number;
  in: number;
  out: number;
  volume: number;
  fadeIn: number;
  fadeOut: number;
  name?: string;
}

export interface TracksDoc {
  video: VClip[];
  text: TText[];
  audio: AClip[];
}

export interface EditDoc {
  version: number;
  aspect: "9:16" | "16:9" | "1:1" | string;
  fps: number;
  tracks: TracksDoc;
}

// --- Project & Brief ---
export interface BriefField {
  key: string;
  label: string;
  question: string;
  required: boolean;
  value: string;
}

export interface BriefData {
  fields: BriefField[];
  required_done: number;
  required_total: number;
  missing: string[];
  complete: boolean;
}

export interface ProjectSummary {
  name: string;
  shots: number;
  spent: number;
  estimate: number | null;
  approved: boolean;
  test?: boolean;
  assets?: number;
  favorite?: boolean;
}

export interface ProjectOverview {
  name: string;
  mode: "test" | "real";
  test_pipeline?: boolean;
  is_test?: boolean;
  shots: { aspect_ratio?: string; audio?: boolean; shots: Shot[] };
  images: { style?: string; images: ImageAsset[] };
  budget: {
    approved?: boolean;
    estimate?: number;
    stop_loss?: number;
    per_shot?: { id: string; cost: number }[];
    stills?: number;
    clips?: number;
    failure_rate?: number;
  };
  costs: { used: number; discarded: number; total: number };
  rates?: { models?: Record<string, Record<string, any>> };
  discarded: { file: string; cost: number; reason: string; when: string; original: string }[];
  proposals: Proposal[];
  files: { stills: string[]; clips: string[]; audio?: string[] };
  reviews: Record<string, any>;
}

// --- Pipeline, Budget & Proposals ---
export interface ProposalSummary {
  provider?: string | null;
  prompt?: string;
  seconds?: number | null;
  audio?: boolean | null;
  first_frame?: string | null;
  refs?: string[];
  file?: string | null;
}

export interface Proposal {
  id: string;
  kind: string;
  shot: string;
  model: string;
  price: number;
  status: string;
  created?: string;
  code?: string;
  expires?: number;
  summary?: ProposalSummary;
  payload?: Record<string, any>;
}

export interface BudgetShot {
  id: string;
  seconds: number;
  cost: number;
}

export interface BudgetDoc {
  estimate: number;
  stop_loss: number;
  clips: number;
  stills: number;
  footage_seconds: number;
  failure_rate: number;
  approved: boolean;
  per_shot: BudgetShot[];
}

export interface ProgressGroup {
  key: string;
  label: string;
  done: number;
  total: number;
}

export interface NextAction {
  kind: "chat" | "apply-story" | "budget" | "image" | "clip" | "approve" | "export" | string;
  label: string;
  target?: string;
}

export interface QueueItem {
  kind: "image" | "clip" | string;
  target: string;
  label: string;
  price?: number;
  model?: string;
}

export interface ProductionProgress {
  groups: ProgressGroup[];
  next: NextAction | null;
  queue?: QueueItem[];
}
