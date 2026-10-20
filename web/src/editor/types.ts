export type Aspect = "9:16" | "16:9" | "1:1";
export type TransitionType = string;   // one of TRANSITIONS below (the server checks the list)
export type Align = "left" | "center" | "right" | "justify";

export interface TransitionConfig {
  type: TransitionType;
  dur: number;
  direction?: "left" | "right" | "up" | "down" | "tl";
  color?: "black" | "white" | "gray";
  curve?: "linear" | "smooth" | "fast" | "slow";
}

export interface VClip { id: string; src: string; in: number; out: number; volume: number; transition: TransitionConfig; }
export interface TText {
  id: string; text: string; start: number; end: number; x: number; y: number;
  font: string; weight: number; size: number; color: string; bg: string | null; align: Align;
  bold: boolean; italic: boolean; underline: boolean; caps: boolean; opacity: number;
  shadow: { on: boolean; color: string; blur: number };
}
export interface AClip { id: string; src: string; start: number; in: number; out: number; volume: number; fadeIn: number; fadeOut: number; name?: string; }
export interface TElement {
  id: string;
  src: string;
  start: number;
  end: number;
  x: number;
  y: number;
  scale: number;
  opacity: number;
  name?: string;
}

export interface TFilter {
  id: string;
  intensity: number;
}

export interface TEffect {
  id: string;
  intensity: number;
  speed?: number;
}

export interface TSubtitleCue {
  id: string;
  start: number;
  end: number;
  text: string;
}

export interface TSubtitlesConfig {
  cues: TSubtitleCue[];
  style?: "tiktok" | "classic" | "minimal";
  font?: string;
  size?: number;
  color?: string;
  bg?: string;
  y?: number;
}

export interface TBackgroundConfig {
  type: "black" | "blur" | "color" | "gradient";
  color?: string;
  blurRadius?: number;
  gradient?: { from: string; to: string };
}

export interface Edit {
  version: 1;
  aspect: Aspect;
  fps: number;
  filter?: TFilter;
  effect?: TEffect;
  background?: TBackgroundConfig;
  tracks: {
    video: VClip[];
    text: TText[];
    audio: AClip[];
    elements?: TElement[];
    subtitles?: TSubtitlesConfig;
  };
}

export interface EditResponse {
  edit: Edit; saved: boolean; missing: string[]; warning: string | null;
  tools: { ffmpeg: boolean; ffprobe: boolean }; exports: { file: string; bytes: number; when: string }[];
}
export interface FontInfo { family: string; weights: { weight: number; name: string; file: string }[]; italic: { weight: number; file: string }[]; }

export type Sel = { kind: "video" | "text" | "audio" | "element" | "transition" | "subtitle"; id: string } | null;
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

export const FILTER_PRESETS: { id: string; label: string; desc: string }[] = [
  { id: "none", label: "Normal (None)", desc: "Original colors without grading" },
  { id: "cinema", label: "Cinematic Warm", desc: "Warm highlights, filmic contrast lift" },
  { id: "teal_orange", label: "Teal & Orange", desc: "Hollywood action blockbuster look" },
  { id: "vintage", label: "Vintage 70s", desc: "Nostalgic golden fade and warmth" },
  { id: "noir", label: "Film Noir", desc: "High-contrast monochrome black & white" },
  { id: "vibrant", label: "Vibrant Pop", desc: "Punchy color saturation and clarity" },
  { id: "cyberpunk", label: "Cyberpunk", desc: "Neon cyan and magenta grade" },
  { id: "warm", label: "Golden Hour", desc: "Soft ambient sunlight warmth" },
];

export const EFFECT_PRESETS: { id: string; label: string; desc: string }[] = [
  { id: "none", label: "None", desc: "No visual distortion" },
  { id: "vignette", label: "Vignette", desc: "Cinematic darkened edge shading" },
  { id: "grain", label: "35mm Film Grain", desc: "Organic analog film texture" },
  { id: "shake", label: "Handheld Camera", desc: "Organic subtle handheld drift" },
  { id: "zoompulse", label: "Ken Burns Push", desc: "Slow continuous push-in zoom" },
  { id: "glitch", label: "RGB Glitch", desc: "Subtle chromatic aberration scanlines" },
  { id: "blur", label: "Soft Glow Focus", desc: "Dreamy cinematic edge blur" },
];

export const BACKGROUND_PRESETS: { type: "black" | "blur" | "color" | "gradient"; label: string; desc: string; color?: string; gradient?: { from: string; to: string } }[] = [
  { type: "blur", label: "Smart Blur", desc: "Mirrors and blurs video behind canvas" },
  { type: "black", label: "Classic Black", desc: "Standard black letterbox" },
  { type: "color", color: "#0b0c16", label: "Midnight Dark", desc: "Deep blue-black matte" },
  { type: "color", color: "#1e1b4b", label: "Deep Indigo", desc: "Rich royal indigo matte" },
  { type: "color", color: "#18182b", label: "Studio Purple", desc: "AI Studio signature tone" },
  { type: "gradient", gradient: { from: "#2e0854", to: "#0f051d" }, label: "Violet Night", desc: "Smooth violet-to-dark gradient" },
  { type: "gradient", gradient: { from: "#0f172a", to: "#020617" }, label: "Deep Slate", desc: "Subtle dark slate gradient" },
];
