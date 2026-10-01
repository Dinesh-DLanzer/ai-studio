const KEY = "aistudio-token";

export function initToken(): string | null {
  const u = new URL(location.href);
  const t = u.searchParams.get("token");
  if (t) {
    sessionStorage.setItem(KEY, t);
    u.searchParams.delete("token");
    history.replaceState(null, "", u.pathname + u.search + u.hash);
  }
  return sessionStorage.getItem(KEY);
}
export const setToken = (t: string) => sessionStorage.setItem(KEY, t.trim());
export const getToken = () => sessionStorage.getItem(KEY) || "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

export async function api<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: { "x-aistudio-token": getToken(), ...(body !== undefined ? { "content-type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, (data as any).detail || (data as any).error || r.statusText);
  return data as T;
}

export const fileUrl = (project: string, rel: string) => `/files/${encodeURIComponent(project)}/${rel}?token=${encodeURIComponent(getToken())}`;

export async function upload(project: string, rel: string, file: File, replace = false) {
  const r = await fetch(`/api/projects/${encodeURIComponent(project)}/upload?rel=${encodeURIComponent(rel)}${replace ? "&replace=1" : ""}`, {
    method: "POST", headers: { "x-aistudio-token": getToken() }, body: file,
  });
  if (!r.ok) throw new ApiError(r.status, ((await r.json().catch(() => ({}))) as any).detail || r.statusText);
}

export async function uploadAudio(project: string, file: File): Promise<{ src: string; name: string; duration: number | null }> {
  const r = await fetch(`/api/projects/${encodeURIComponent(project)}/audio?filename=${encodeURIComponent(file.name)}`, { method: "POST", headers: { "x-aistudio-token": getToken() }, body: file });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, (j as any).detail || r.statusText);
  return j as any;
}
