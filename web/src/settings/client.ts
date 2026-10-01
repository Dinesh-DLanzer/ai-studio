import { api } from "../api";
import type { ChainRef, ModelInfo, PriceCard, Provider, ProviderType, ProvidersResponse, Role, RolesResponse, TestRow } from "./types";

const q = (project?: string) => (project ? `?project=${encodeURIComponent(project)}` : "");
const enc = encodeURIComponent;

/** The built-in test provider still runs the server's test pipeline, but it is not something to pick or manage, so the UI never lists it. */
const notFake = <T extends { provider?: string; type?: string }>(xs: T[]) => xs.filter((x) => x.provider !== "fake" && x.type !== "fake");
const hideFake = (r: RolesResponse): RolesResponse => ({ ...r, roles: Object.fromEntries(Object.entries(r.roles).map(([k, v]) => [k, { ...v, chain: notFake(v.chain) }])) as RolesResponse["roles"] });

export const settingsApi = {
  types: () => api<{ types: ProviderType[] }>("GET", "/api/provider-types").then((r) => r.types),
  providers: () => api<ProvidersResponse>("GET", "/api/providers").then((r) => ({ ...r, providers: notFake(r.providers) })),
  createProvider: (b: { type: string; label?: string; base_url?: string; secret?: Record<string, string> }) => api<Provider>("POST", "/api/providers", b),
  updateProvider: (id: string, b: Partial<Pick<Provider, "label" | "base_url" | "enabled">>) => api<Provider>("PATCH", `/api/providers/${enc(id)}`, b),
  deleteProvider: (id: string, force = false) => api<{ ok: boolean; removed_from: Role[] }>("DELETE", `/api/providers/${enc(id)}${force ? "?force=1" : ""}`),
  putSecret: (id: string, fields: Record<string, string>) => api<Provider>("PUT", `/api/providers/${enc(id)}/secret`, fields),
  deleteSecret: (id: string) => api<Provider>("DELETE", `/api/providers/${enc(id)}/secret`),
  testProvider: (id: string) => api<{ result: { ok: boolean; message: string }; provider: Provider }>("POST", `/api/providers/${enc(id)}/test`),
  providerModels: (id: string, refresh = false) => api<{ models: ModelInfo[]; error: string | null }>("GET", `/api/providers/${enc(id)}/models${refresh ? "?refresh=1" : ""}`),
  addModel: (id: string, model: string, capability: string) => api<{ models: ModelInfo[] }>("POST", `/api/providers/${enc(id)}/models`, { id: model, capability }),
  models: (capability?: string) => api<{ models: ModelInfo[]; errors: Record<string, string> }>("GET", `/api/models${capability ? `?capability=${capability}` : ""}`).then((r) => ({ ...r, models: notFake(r.models) })),
  putPrice: (provider: string, model: string, card: PriceCard) => api<{ price: string }>("PUT", `/api/prices/${enc(provider)}/${model.split("/").map(enc).join("/")}`, card),
  roles: (project?: string) => api<RolesResponse>("GET", `/api/roles${q(project)}`).then(hideFake),
  putRole: (role: Role, chain: ChainRef[], policy?: { retries?: number; timeout?: number }, project?: string) => api<RolesResponse>("PUT", `/api/roles/${role}${q(project)}`, { chain, policy }).then(hideFake),
  testRole: (role: Role, project?: string) => api<{ role: Role; results: TestRow[] }>("POST", `/api/roles/${role}/test${q(project)}`),
  resetRoles: () => api<RolesResponse>("POST", "/api/roles/reset").then(hideFake),
  putLimits: (b: { allow_paid?: boolean; ai_cap_usd?: number; auto_verify?: boolean }) => api<RolesResponse>("PUT", "/api/limits", b).then(hideFake),
  usage: (project: string) => api<{ rows: { provider: string; model: string; cost: number; calls: number }[] }>("GET", `/api/projects/${enc(project)}/usage`),
};
