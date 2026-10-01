export type Aspect = "9:16" | "16:9" | "1:1";
export type TransitionType = string;   // one of TRANSITIONS below (the server checks the list)
export type Align = "left" | "center" | "right" | "justify";

export interface VClip { id: string; src: string; in: number; out: number; volume: number; transition: { type: TransitionType; dur: number }; }
export interface TText {
  id: string; text: string; start: number; end: number; x: number; y: number;
  font: string; weight: number; size: number; color: string; bg: string | null; align: Align;
  bold: boolean; italic: boolean; underline: boolean; caps: boolean; opacity: number;
  shadow: { on: boolean; color: string; blur: number };
}
export interface AClip { id: string; src: string; start: number; in: number; out: number; volume: number; fadeIn: number; fadeOut: number; name?: string; }
export interface Edit { version: 1; aspect: Aspect; fps: number; tracks: { video: VClip[]; text: TText[]; audio: AClip[] }; }

export interface EditResponse {
  edit: Edit; saved: boolean; missing: string[]; warning: string | null;
  tools: { ffmpeg: boolean; ffprobe: boolean }; exports: { file: string; bytes: number; when: string }[];
}
export interface FontInfo { family: string; weights: { weight: number; name: string; file: string }[]; italic: { weight: number; file: string }[]; }

export type Sel = { kind: "video" | "text" | "audio"; id: string } | null;
export type Tool = "media" | "text" | "elements" | "audio" | "transitions" | "filters" | "effects" | "subtitles" | "aspect" | "background";

export const TRANSITION_GROUPS: { group: string; items: { id: string; label: string }[] }[] = [
  { group: "Basic", items: [{ id: "cut", label: "Cut" }] },
  { group: "Dissolves and fades", items: [
    { id: "crossfade", label: "Crossfade" }, { id: "dissolve", label: "Dissolve" }, { id: "fade", label: "Dip to black" }, { id: "fadewhite", label: "Dip to white" },
    { id: "fadegrays", label: "Fade via grey" }, { id: "fadefast", label: "Fast fade" }, { id: "fadeslow", label: "Slow fade" }] },
  { group: "Wipes", items: [
    { id: "wipe", label: "Wipe left" }, { id: "wiperight", label: "Wipe right" }, { id: "wipeup", label: "Wipe up" }, { id: "wipedown", label: "Wipe down" }, { id: "wipetl", label: "Wipe corner" }] },
  { group: "Slides and pushes", items: [
    { id: "slideleft", label: "Slide left" }, { id: "slideright", label: "Slide right" }, { id: "slideup", label: "Slide up" }, { id: "slidedown", label: "Slide down" },
    { id: "smoothleft", label: "Smooth left" }, { id: "smoothright", label: "Smooth right" }] },
  { group: "Cover and reveal", items: [
    { id: "coverleft", label: "Cover left" }, { id: "coverright", label: "Cover right" }, { id: "revealleft", label: "Reveal left" }, { id: "revealright", label: "Reveal right" }] },
  { group: "Shapes", items: [
    { id: "circleopen", label: "Circle open" }, { id: "circleclose", label: "Circle close" }, { id: "radial", label: "Radial sweep" }, { id: "vertopen", label: "Doors open (vertical)" },
    { id: "horzopen", label: "Doors open (horizontal)" }, { id: "diagtl", label: "Diagonal" }] },
  { group: "Effects", items: [
    { id: "pixelize", label: "Pixelate" }, { id: "zoomin", label: "Zoom in" }, { id: "hblur", label: "Blur" }, { id: "squeezeh", label: "Squeeze" },
    { id: "hlslice", label: "Slices" }, { id: "vuslice", label: "Vertical slices" }, { id: "hlwind", label: "Wind" }, { id: "distance", label: "Distance" }] },
];
export const TRANSITIONS = TRANSITION_GROUPS.flatMap((g) => g.items);
export const MAX_TEXT = 100;
