import { useSyncExternalStore } from "react";

/** A tiny global store of AI-process notifications (chat replies, images, clips, reviews). Shown in the bell menu; kept in this browser only. */
export type NotifyStatus = "running" | "ok" | "error";
export interface Notice { id: string; title: string; text: string; status: NotifyStatus; ts: number; project?: string; to?: string; read: boolean; }

const KEY = "ai-studio-notifications"; const MAX = 40;
let items: Notice[] = [];
try { items = (JSON.parse(localStorage.getItem(KEY) || "[]") as Notice[]).filter((n) => n.status !== "running").slice(0, MAX); } catch { items = []; }
const subs = new Set<() => void>();
const emit = () => { try { localStorage.setItem(KEY, JSON.stringify(items.filter((n) => n.status !== "running"))); } catch { /* private window */ } subs.forEach((f) => f()); };
const set = (next: Notice[]) => { items = next.slice(0, MAX); emit(); };

export function notifyStart(title: string, text: string, extra: { project?: string; to?: string } = {}): string {
  const id = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  set([{ id, title, text, status: "running", ts: Date.now(), read: false, ...extra }, ...items]);
  return id;
}
export function notifyDone(id: string, status: "ok" | "error", text: string) {
  set(items.map((n) => (n.id === id ? { ...n, status, text, ts: Date.now(), read: false } : n)));
}
/** One-shot notice for something that already finished. */
export function notify(title: string, text: string, status: "ok" | "error" = "ok", extra: { project?: string; to?: string } = {}) {
  notifyDone(notifyStart(title, text, extra), status, text);
}
export const markAllRead = () => set(items.map((n) => ({ ...n, read: true })));
export const clearNotices = () => set(items.filter((n) => n.status === "running"));
export const removeNotice = (id: string) => set(items.filter((n) => n.id !== id));

const snapshot = () => items;
export const useNotices = () => useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, snapshot);
