import { useEffect, useRef, useState } from "react";
import { api, fileUrl, upload } from "../api";
import { confirmDialog, promptDialog } from "../dialogs";
import { ID_OK, stem } from "../ProjectPage";
import { useToast } from "../toast";
import type { FoundStill, ImageSpec, Overview } from "../types";

export type Kind = ImageSpec["kind"];

export interface UseProjectAssetsProps {
  name: string;
  o: Overview;
  load: () => void;
}

export function useProjectAssets({ name, o, load }: UseProjectAssetsProps) {
  const toast = useToast();
  const [doc, setDoc] = useState<ImageSpec[]>(o.images.images);
  const [style, setStyle] = useState(o.images.style || "");
  const [dirty, setDirty] = useState(false);
  const [adding, setAdding] = useState<Kind | null>(null);
  const [newId, setNewId] = useState("");
  const [newPrompt, setNewPrompt] = useState("");
  const [pick, setPick] = useState<string | null>(null);
  const [active, setActive] = useState<Kind>("character");
  const [dragId, setDragId] = useState<string | null>(null);
  const [found, setFound] = useState<FoundStill[]>([]);
  const [story, setStory] = useState("");
  const [checkingChar, setCheckingChar] = useState<{ id: string; file: string; analysis: any; replacing: boolean } | null>(null);

  const secs = useRef<Partial<Record<Kind, HTMLElement | null>>>({});

  useEffect(() => {
    api<{ text: string }>("GET", `/api/projects/${name}/docs/Story.md`)
      .then((r) => setStory(r.text))
      .catch(() => setStory(""));
  }, [name, o.images]);

  useEffect(() => {
    setDoc(o.images.images);
    setStyle(o.images.style || "");
    setDirty(false);
  }, [o.images]);

  useEffect(() => {
    api<{ files: FoundStill[] }>("GET", `/api/projects/${name}/stills/unregistered`)
      .then((r) => setFound(r.files))
      .catch(() => setFound([]));
  }, [name, o.files.stills.join("|"), o.images.images.length]);

  const file = (id: string) => o.files.stills.find((f) => stem(f) === id);
  const url = (id: string) => {
    const f = file(id);
    return f ? fileUrl(name, `stills/${encodeURIComponent(f)}`) : undefined;
  };

  const edit = (next: ImageSpec[]) => {
    setDoc(next);
    setDirty(true);
  };

  const persist = async (images: ImageSpec[], quiet = false) => {
    await api("PUT", `/api/projects/${name}/images`, { style, images });
    if (!quiet) toast("ok", "Image list saved.");
    load();
  };

  const save = async () => {
    try {
      await persist(doc);
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  const open = (kind: Kind) => {
    setActive(kind);
    setAdding(kind);
    setNewId("");
    setNewPrompt("");
    secs.current[kind]?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const add = async (kind: Kind) => {
    const id = newId.trim().toLowerCase();
    if (!ID_OK.test(id)) return toast("error", "Use a short id: lowercase letters, numbers, - or _ (for example ramesh_sheet).");
    if (doc.some((i) => i.id === id)) return toast("error", `An asset called ${id} already exists.`);
    const spec: ImageSpec = { id, kind, out: `stills/${id}.png`, prompt: newPrompt.trim() || `${kind} ${id}`, refs: [], aspect_ratio: kind === "frame" ? "9:16" : "3:2" };
    try {
      await persist([...doc, spec], true);
      setAdding(null);
      setNewId("");
      setNewPrompt("");
      setPick(id);
      toast("ok", `Added ${id}. Upload your image or generate one.`);
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  const up = async (id: string, f: File | undefined, replace: boolean) => {
    if (!f) return;
    if (!f.type.startsWith("image/") && !/\.(png|jpe?g|webp|gif|bmp|tiff?|heic|heif)$/i.test(f.name)) {
      return toast("error", "That is not a supported image.");
    }
    try {
      await upload(name, `stills/${id}.png`, f, replace);
      toast("ok", replace ? `Replaced ${id}. The old image is in Discarded.` : `Uploaded ${id}.`);
      load();

      const item = doc.find((x) => x.id === id);
      if (item?.kind === "character") {
        api<any>("POST", `/api/projects/${name}/character/analyze`, { rel: `stills/${id}.png` })
          .then((analysis) => {
            if (analysis && !analysis.is_character_sheet) {
              setCheckingChar({ id, file: `${id}.png`, analysis, replacing: replace });
            }
          })
          .catch(() => {});
      }
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  const discard = async (rel: string) => {
    const reason = await promptDialog("Why discard this image?", { title: "Discard image", ok: "Discard" });
    if (reason === null) return;
    await api("POST", `/api/projects/${name}/discard`, { rel, reason });
    load();
  };

  const remove = async (id: string) => {
    if (await confirmDialog(`Remove ${id} from the list? (Only possible while it has no image.)`, { title: "Remove asset", ok: "Remove", danger: true })) {
      persist(doc.filter((i) => i.id !== id)).catch((e: any) => toast("error", e.message));
    }
  };

  const toggleRef = (i: ImageSpec, ref: string) => {
    const has = i.refs.includes(ref);
    if (!has && i.refs.length >= 4) return toast("error", "At most 4 reference images.");
    edit(doc.map((x) => (x.id === i.id ? { ...x, refs: has ? x.refs.filter((r) => r !== ref) : [...x.refs, ref] } : x)));
  };

  const convertToRefAndGenerateMaster = async () => {
    if (!checkingChar) return;
    const { id, analysis } = checkingChar;
    const refId = `${id}_ref`;
    try {
      await api("POST", `/api/projects/${name}/assets/${id}/rename`, { new: refId });
      const cur = doc.filter((x) => x.id !== id && x.id !== refId);
      const prompt =
        analysis.suggested_prompt ||
        `Character reference sheet of ${id}: full-body front, side and back views, plus a grid of facial expressions labelled NEUTRAL, HAPPY, ANGRY, SAD, SURPRISED, THINKING, LAUGHING, CONCERNED, plus close-ups of the face and clothing detail.`;
      const masterSpec: ImageSpec = {
        id,
        kind: "character",
        out: `stills/${id}.png`,
        prompt,
        refs: [refId],
        aspect_ratio: "3:2",
      };
      const refSpec: ImageSpec = {
        id: refId,
        kind: "other",
        out: `stills/${refId}.png`,
        prompt: `Reference photo of ${id}`,
        refs: [],
        aspect_ratio: "3:2",
      };
      await persist([...cur, refSpec, masterSpec], true);
      toast("ok", `Kept uploaded photo as ${refId}. Character ${id} is ready to generate full model sheet.`);
      setCheckingChar(null);
      setPick(id);
      load();
    } catch (e: any) {
      toast("error", e.message);
    }
  };

  return {
    doc,
    setDoc,
    style,
    setStyle,
    dirty,
    setDirty,
    story,
    found,
    active,
    setActive,
    adding,
    setAdding,
    newId,
    setNewId,
    newPrompt,
    setNewPrompt,
    pick,
    setPick,
    dragId,
    setDragId,
    checkingChar,
    setCheckingChar,
    secs,
    file,
    url,
    edit,
    persist,
    save,
    open,
    add,
    up,
    discard,
    remove,
    toggleRef,
    convertToRefAndGenerateMaster,
  };
}
