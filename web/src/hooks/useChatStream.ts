import { useCallback, useEffect, useRef, useState } from "react";
import { api, upload } from "../api";
import { AI_NAME } from "../brand";
import { notifyDone, notifyStart } from "../notify";
import { useToast } from "../toast";
import type { ChatAction, ChatAttachment, ChatState, Overview } from "../types";
const slug = (n: string) =>
  n
    .replace(/\.[^.]+$/, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 40) || "upload";

export interface UseChatStreamProps {
  project: string;
  reloadAll: () => void;
  onApplied: () => void;
  refreshKey?: unknown;
}

export function useChatStream({ project, reloadAll, onApplied, refreshKey }: UseChatStreamProps) {  const toast = useToast();
  const [st, setSt] = useState<ChatState | null>(null);
  const [suggestedAction, setSuggestedAction] = useState<ChatAction | null>(null);
  const [text, setText] = useState("");
  // "@writer ..." is routed to a crew run; the server does not store it in the chat, so the reply is kept here
  const [routed, setRouted] = useState<{ agent: string; run: string; reply: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState("");
  const [files, setFiles] = useState<ChatAttachment[]>([]);
  const [assetPickerOpen, setAssetPickerOpen] = useState(false);
  const [projectAssets, setProjectAssets] = useState<{ id: string; file: string; kind?: string }[]>([]);

  const log = useRef<HTMLDivElement>(null);
  const attach = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const s = await api<ChatState>("GET", `/api/projects/${project}/chat`);
    setSt(s);
    setPending(s.pending_story ? (await api<{ text: string }>("GET", `/api/projects/${project}/story/pending`)).text : "");
  }, [project]);

  useEffect(() => {
    load().catch((e) => toast("error", e.message));
  }, [load, toast, refreshKey]);

  useEffect(() => {
    const key = `ai-studio-idea:${project}`;
    const idea = sessionStorage.getItem(key);
    if (idea) {
      sessionStorage.removeItem(key);
      setTimeout(() => send(idea), 400);
    }
    /* eslint-disable-next-line */
  }, [project]);

  useEffect(() => {
    const el = log.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [st?.messages.length, busy]);

  const send = async (msg?: string) => {
    const t = (msg ?? text).trim();
    if (!t || busy) return;
    const currentText = text;
    setText("");
    setBusy(true);
    const nid = notifyStart(`${AI_NAME} is replying`, t.length > 80 ? `${t.slice(0, 80)}…` : t, { project, to: `/p/${project}/chat` });
    const sent = files;
    setFiles([]);
    setSt((s) => s && { ...s, messages: [...s.messages, { role: "user", text: t, ts: new Date().toISOString(), ...(sent.length ? { attachments: sent } : {}) }] });
    try {
      const r = await api<{ routed_to?: string; run?: string; reply?: string; applied?: boolean; action?: ChatAction; executed?: { type: string; kind?: string; target?: string } }>("POST", `/api/projects/${project}/chat`, {
        text: t,
        prefs: { auto_storyboard: true },
        ...(sent.length ? { attachments: sent.map((f) => f.id) } : {}),
      });
      await load();
      reloadAll();
      setRouted(r.routed_to && r.run ? { agent: r.routed_to, run: r.run, reply: r.reply || "" } : null);
      setSuggestedAction(r.action || null);
      if (r.applied) {
        toast("ok", "Story.md and TODO.md are ready.");
        onApplied();
      }
      if (r.executed) {
        if (r.executed.type === "generate") {
          toast("ok", `Generated ${r.executed.kind || "image"} ${r.executed.target || ""}.`);
        } else if (r.executed.type === "approve_budget") {
          toast("ok", "Budget approved.");
        }
      }
      notifyDone(nid, "ok", r.applied ? "Reply ready. Story.md and TODO.md were written from your brief." : "Reply ready.");
    } catch (e: any) {
      setText(currentText);
      setFiles(sent);
      toast("error", e.message);
      notifyDone(nid, "error", e.message);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const attachFile = async (f?: File) => {
    if (!f) return;
    if (!f.type.startsWith("image/") && !/\.(png|jpe?g|webp|gif|bmp|tiff?|heic|heif)$/i.test(f.name)) {
      return toast("error", "That is not a supported image.");
    }
    try {
      const o = await api<any>("GET", `/api/projects/${project}`);
      const taken = new Set<string>((o.images?.images || []).map((i: any) => i.id));
      let id = slug(f.name),
        n = 2;
      while (taken.has(id)) id = `${slug(f.name)}_${n++}`;
      await upload(project, `stills/${id}.png`, f, false);
      const o2 = await api<any>("GET", `/api/projects/${project}`);
      const file = (o2.files.stills as string[]).find((x) => x.startsWith(`${id}.`)) || `${id}.png`;
      await api("POST", `/api/projects/${project}/stills/import`, { items: [{ file, id, kind: "other" }] });
      setFiles((x) => [...x, { id, file }]);
      toast("ok", `${id} saved in Uploads. It is sent with your next message.`);
      reloadAll();
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  const openAssetPicker = async () => {
    try {
      const o = await api<Overview>("GET", `/api/projects/${project}`);
      const list: { id: string; file: string; kind?: string }[] = [];
      const seen = new Set<string>();
      for (const img of o.images?.images || []) {
        const f = (o.files?.stills || []).find((x) => x.replace(/\.[^.]+$/, "") === img.id) || img.out?.replace(/^stills\//, "") || `${img.id}.png`;
        if (f && (o.files?.stills || []).includes(f)) {
          list.push({ id: img.id, file: f, kind: img.kind });
          seen.add(img.id);
        }
      }
      for (const f of o.files?.stills || []) {
        const id = f.replace(/\.[^.]+$/, "");
        if (!seen.has(id)) {
          list.push({ id, file: f, kind: "file" });
          seen.add(id);
        }
      }
      setProjectAssets(list);
      setAssetPickerOpen(true);
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  const attachExistingAsset = (item: { id: string; file: string }) => {
    if (files.some((f) => f.id === item.id)) {
      setFiles((x) => x.filter((f) => f.id !== item.id));
    } else {
      if (files.length >= 4) {
        toast("error", "You can attach up to 4 images per message.");
        return;
      }
      setFiles((x) => [...x, { id: item.id, file: item.file }]);
    }
  };

  const apply = async () => {
    try {
      const r = await api<any>("POST", `/api/projects/${project}/story/apply-pending`);
      toast("ok", `Storyboard applied: ${r.shots.shots.length} shots, ${r.images.images.length} images.`);
      await load();
      reloadAll();
      onApplied();
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  return {
    st,
    setSt,
    text,
    setText,
    routed,
    busy,
    pending,
    files,
    setFiles,
    assetPickerOpen,
    setAssetPickerOpen,
    projectAssets,
    log,
    attach,
    load,
    send,
    attachFile,
    openAssetPicker,
    suggestedAction,
    setSuggestedAction,
    attachExistingAsset,
    apply,
  };
}
