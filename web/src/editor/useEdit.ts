import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Edit, EditResponse } from "./types";

export type SaveState = "idle" | "saving" | "saved" | "error";
const HISTORY = 100;

/** The edit list with undo/redo and debounced auto-save to edit.json.  `set(fn, key)`: edits with the same key within 700 ms are one undo step. */
export function useEdit(project: string) {
  const [data, setData] = useState<EditResponse | null>(null);
  const [edit, setEditState] = useState<Edit | null>(null);
  const [save, setSave] = useState<SaveState>("idle"); const [saveErr, setSaveErr] = useState("");
  const past = useRef<Edit[]>([]); const future = useRef<Edit[]>([]); const [, bump] = useState(0);
  const last = useRef<{ key: string; at: number }>({ key: "", at: 0 });
  const timer = useRef<number | undefined>(undefined); const latest = useRef<Edit | null>(null); const dirty = useRef(false);

  const flush = useCallback(async () => {
    window.clearTimeout(timer.current);
    if (!dirty.current || !latest.current) return;
    dirty.current = false; setSave("saving");
    try { await api("PUT", `/api/projects/${project}/edit`, latest.current); setSave(dirty.current ? "saving" : "saved"); setSaveErr(""); }
    catch (e: any) { dirty.current = true; setSave("error"); setSaveErr(e.message); }
  }, [project]);

  const schedule = useCallback(() => { dirty.current = true; setSave("saving"); window.clearTimeout(timer.current); timer.current = window.setTimeout(() => { flush(); }, 700); }, [flush]);

  const load = useCallback(async () => {
    const r = await api<EditResponse>("GET", `/api/projects/${project}/edit`);
    setData(r); setEditState(r.edit); latest.current = r.edit; past.current = []; future.current = []; dirty.current = false; setSave(r.saved ? "saved" : "idle"); bump((n) => n + 1);
  }, [project]);
  useEffect(() => { load().catch((e) => setSaveErr(e.message)); }, [load]);
  // never lose an edit when leaving the page
  useEffect(() => () => { if (dirty.current && latest.current) { fetch(`/api/projects/${project}/edit`, { method: "PUT", keepalive: true, headers: { "content-type": "application/json", "x-aistudio-token": sessionStorage.getItem("aistudio-token") || "" }, body: JSON.stringify(latest.current) }).catch(() => {}); } }, [project]);

  const set = useCallback((fn: (e: Edit) => Edit, key = "") => {
    const cur = latest.current; if (!cur) return;
    const next = fn(cur); if (next === cur) return;
    const now = Date.now();
    if (!(key && last.current.key === key && now - last.current.at < 700)) { past.current.push(cur); if (past.current.length > HISTORY) past.current.shift(); future.current = []; }
    last.current = { key, at: now };
    latest.current = next; setEditState(next); bump((n) => n + 1); schedule();
  }, [schedule]);
  const undo = useCallback(() => { const p = past.current.pop(); if (!p || !latest.current) return; future.current.push(latest.current); latest.current = p; last.current = { key: "", at: 0 }; setEditState(p); bump((n) => n + 1); schedule(); }, [schedule]);
  const redo = useCallback(() => { const n = future.current.pop(); if (!n || !latest.current) return; past.current.push(latest.current); latest.current = n; last.current = { key: "", at: 0 }; setEditState(n); bump((x) => x + 1); schedule(); }, [schedule]);

  return { data, edit, set, undo, redo, canUndo: past.current.length > 0, canRedo: future.current.length > 0, save, saveErr, flush, reload: load, setData };
}
