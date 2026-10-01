/** Shapes returned by the providers / models / roles API (see aistudio/settings_api.py). Secrets never appear here, only masked info. */
export type Capability = "chat" | "vision" | "image" | "video";
export type Role = "chat" | "verify" | "vision" | "image" | "video";
export const ROLES: Role[] = ["chat", "verify", "vision", "image", "video"];
export type ProviderState = "active" | "inactive" | "needs_key" | "error";

export interface ProviderType { type: string; label: string; sub: string; fields: string[]; base_url: boolean; capabilities: Capability[]; }
export interface Provider {
  id: string; type: string; label: string; sub: string; base_url: string; enabled: boolean; fields: string[]; capabilities: Capability[];
  secret: { set: boolean; fields: Record<string, string> }; secret_source: "stored";
  status: { state: ProviderState; message: string; checked_at?: number }; used_in: Role[];
}
export interface ProvidersResponse { providers: Provider[]; secrets_backend: "keychain" | "file"; }

export interface PriceCard { kind: "video" | "image" | "text"; per_second?: Record<string, unknown>; per_image?: number; input_per_1m?: number; output_per_1m?: number; per_call?: number; free?: boolean; from?: string; }
export interface ModelInfo {
  provider: string; provider_label: string; ptype: string; id: string; name: string; capability: Capability;
  price: string | null; priced: boolean; free: boolean; card: PriceCard | null; suggest: PriceCard | null; custom: boolean;
}
export interface ChainEntry {
  provider: string; provider_label: string; ptype: string; model: string; problem: string | null;
  price: string | null; priced: boolean; free: boolean; unhealthy: string | null; dearer: boolean;
}
export interface RoleView { title: string; sub: string; capability: Capability; chain: ChainEntry[]; policy: { retries: number; timeout: number }; overridden: boolean; }
export interface RolesResponse { roles: Record<Role, RoleView>; allow_paid: boolean; ai_cap_usd: number; auto_verify: boolean; fake_mode: boolean; }
export interface ChainRef { provider: string; model: string; }
export interface TestRow { provider: string; model: string; ok: boolean; message: string; }
