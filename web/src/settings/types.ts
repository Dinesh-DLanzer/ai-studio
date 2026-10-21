/** Shapes returned by the providers / models / roles API (see aistudio/settings_api.py). Secrets never appear here, only masked info. */
export type Capability = "chat" | "vision" | "image" | "video";
export type Role = "chat" | "verify" | "vision" | "image" | "video";
export const ROLES: Role[] = ["chat", "verify", "vision", "image", "video"];
export type ProviderState = "active" | "inactive" | "needs_key" | "error";

export interface ProviderType { type: string; label: string; sub: string; fields: string[]; base_url: boolean; capabilities: Capability[]; auth_type?: "api_key" | "oauth"; }
export interface ChatGPTStatus { codex_detected: boolean; connected: boolean; provider_id: string | null; signed_in: boolean; plan: string; expires_at: number; expired: boolean; }
export interface Provider {
  id: string; type: string; label: string; sub: string; base_url: string; enabled: boolean; fields: string[]; capabilities: Capability[];
  secret: { set: boolean; fields: Record<string, string> }; secret_source: "stored";
  status: { state: ProviderState; message: string; checked_at?: number }; used_in: Role[];
}
export interface ProvidersResponse { providers: Provider[]; secrets_backend: "keychain" | "file"; }

export interface PriceCard { kind: "video" | "image" | "text" | "audio" | "utility"; minimum_seconds?: number; per_reference_image?: number; retrieved_at?: string; source?: string; per_1k_chars?: number; per_minute?: number; per_run?: number; per_second?: Record<string, unknown>; per_image?: number; input_per_1m?: number; output_per_1m?: number; per_call?: number; free?: boolean; from?: string; }
export interface ModelInfo {
  provider: string; provider_label: string; ptype: string; id: string; name: string; capability: Capability;
  price: string | null; priced: boolean; free: boolean; card: PriceCard | null; suggest: PriceCard | null; custom: boolean;
}
export interface ChainEntry {
  provider: string; provider_label: string; ptype: string; model: string; problem: string | null;
  price: string | null; priced: boolean; free: boolean; card?: PriceCard | null; unhealthy: string | null; dearer: boolean;
}
export interface RoleView { title: string; sub: string; capability: Capability; chain: ChainEntry[]; policy: { retries: number; timeout: number }; overridden: boolean; }
export interface RolesResponse { roles: Record<Role, RoleView>; allow_paid: boolean; ai_cap_usd: number; auto_verify: boolean; fake_mode: boolean; }
export interface ChainRef { provider: string; model: string; }
export interface TestRow { provider: string; model: string; ok: boolean; message: string; }

export type Task = "text_to_image" | "image_edit" | "text_to_video" | "image_to_video" | "video_extend" | "video_to_video" | "upscale" | "reframe" | "motion_transfer"
  | "tts" | "voice_clone" | "music" | "sfx" | "lipsync" | "transcribe";

/** What one model can do (aistudio/schemas/catalog.py). Empty durations / resolutions / aspect_ratios mean "not constrained". */
export interface CapabilityProfile {
  tasks: Task[]; durations: number[]; resolutions: string[]; aspect_ratios: string[];
  audio: "none" | "optional" | "always";
  frames: { start: boolean; end: boolean; keyframes: number };
  references: { max: number; roles: string[] };
  camera: { mode: "native" | "prompt" | "none"; native: string[]; param: string | null };
  seed: boolean; negative_prompt: boolean; tools: "native" | "json";
  source: "user" | "provider_api" | "builtin" | "default"; verified_at: string | null; note?: string | null;
}

/** One image or video model with its effective profile, the user's partial override and its price (GET /api/capabilities). */
export interface CapabilityModel {
  provider: string; provider_label: string; ptype: string; id: string; name: string; capability: Capability;
  price: string | null; priced: boolean; card: PriceCard | null; profile: CapabilityProfile; override: Partial<CapabilityProfile> | null;
}
