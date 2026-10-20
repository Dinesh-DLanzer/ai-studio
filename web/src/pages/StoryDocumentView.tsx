import { useState } from "react";
import {
  Clock,
  Download,
  FileCode2,
  FileText,
  Film,
  Layers,
  MapPin,
  Mic,
  Palette,
  Printer,
  Sparkles,
  Type,
  Users,
  Video,
  Eye,
  Check,
  Copy,
} from "lucide-react";
import { fileUrl } from "../api";
import { Button } from "../ui";

export interface ShotItem {
  number: string;
  time: string;
  purpose: string;
  visual: string;
  camera: string;
  action: string;
  voice: string;
  voiceType: string;
  english: string;
  onScreenText: string;
  uses: string[];
  imageId: string;
  prompt: string;
}

export interface CharacterItem {
  id: string;
  name: string;
  description: string;
}

export interface BackgroundItem {
  id: string;
  name: string;
  description: string;
}

export interface ParsedStoryDocument {
  rawTitle: string;
  concept: Record<string, string>;
  sharedStyle: string;
  characters: CharacterItem[];
  backgrounds: BackgroundItem[];
  characterNotes: string;
  shots: ShotItem[];
}

export function parseStoryDocument(text: string): ParsedStoryDocument {
  const lines = text.split("\n");

  let rawTitle = "AI Video Storyboard";
  const titleMatch = text.match(/^#\s+(.+)$/m);
  if (titleMatch) rawTitle = titleMatch[1].replace(/[*_#]/g, "").trim();

  // Concept metadata
  const concept: Record<string, string> = {};
  const conceptBlock = text.match(/##\s+Concept\s*\n([\s\S]*?)(?=\n##|\n#|\n---|$)/i);
  if (conceptBlock) {
    const metaRegex = /\*\*([A-Za-z0-9\s_-]+):\*\*\s*([^\n]+)/g;
    let m: RegExpExecArray | null;
    while ((m = metaRegex.exec(conceptBlock[1])) !== null) {
      concept[m[1].trim().toLowerCase()] = m[2].trim();
    }
  }

  // Shared style
  let sharedStyle = "";
  const styleMatch = text.match(/##\s+Shared style\s*\n([\s\S]*?)(?=\n##|\n#|\n---|$)/i);
  if (styleMatch) {
    sharedStyle = styleMatch[1].trim().replace(/^[-*>\s]+/, "");
  }

  // Character notes
  let characterNotes = "";
  const charNotesMatch = text.match(/##\s+Character notes\s*\n([\s\S]*?)(?=\n##|\n#|\n---|$)/i);
  if (charNotesMatch) {
    characterNotes = charNotesMatch[1].trim();
  }

  // Characters section
  const characters: CharacterItem[] = [];
  const charsSection = text.match(/##\s+Characters\s*\n([\s\S]*?)(?=\n##|\n#|\n---|$)/i);
  if (charsSection) {
    const charBlocks = charsSection[1].split(/^###\s+/m);
    for (const b of charBlocks) {
      const trimmed = b.trim();
      if (!trimmed) continue;
      const firstLineEnd = trimmed.indexOf("\n");
      const name = (firstLineEnd > -1 ? trimmed.slice(0, firstLineEnd) : trimmed).replace(/[*#]/g, "").trim();
      const desc = (firstLineEnd > -1 ? trimmed.slice(firstLineEnd) : "").trim();
      const id = name.toLowerCase().replace(/[^a-z0-9_-]+/g, "_");
      if (name) characters.push({ id, name, description: desc });
    }
  }

  // Backgrounds section
  const backgrounds: BackgroundItem[] = [];
  const bgSection = text.match(/##\s+Backgrounds\s*\n([\s\S]*?)(?=\n##|\n#|\n---|$)/i);
  if (bgSection) {
    const bgBlocks = bgSection[1].split(/^###\s+/m);
    for (const b of bgBlocks) {
      const trimmed = b.trim();
      if (!trimmed) continue;
      const firstLineEnd = trimmed.indexOf("\n");
      const name = (firstLineEnd > -1 ? trimmed.slice(0, firstLineEnd) : trimmed).replace(/[*#]/g, "").trim();
      const desc = (firstLineEnd > -1 ? trimmed.slice(firstLineEnd) : "").trim();
      const id = name.toLowerCase().replace(/[^a-z0-9_-]+/g, "_");
      if (name) backgrounds.push({ id, name, description: desc });
    }
  }

  // Shots / Scenes
  const shots: ShotItem[] = [];
  const shotMatches = Array.from(text.matchAll(/^##\s+(?:Shot|Scene)\s+(\d+)\s*[—–-]?\s*([^\n]*)/gim));

  for (let idx = 0; idx < shotMatches.length; idx++) {
    const match = shotMatches[idx];
    const shotNum = String(match[1]).padStart(2, "0");
    const shotTiming = match[2].trim() || "";

    const startIndex = match.index! + match[0].length;
    const nextMatch = shotMatches[idx + 1];
    const endIndex = nextMatch ? nextMatch.index! : text.length;
    const block = text.slice(startIndex, endIndex);

    const getField = (fieldName: string) => {
      const re = new RegExp(`\\*\\*${fieldName}\\*\\*[:]?\\s*([^\\n*#]+(?:\\n(?!\\*\\*|###|##|#)[^\\n*#]+)*)`, "i");
      const res = block.match(re);
      return res ? res[1].trim() : "";
    };

    const getBlockquoteField = (fieldName: string) => {
      const re = new RegExp(`\\*\\*${fieldName}\\*\\*[^\\n]*\\n(?:>\\s*([^\\n]+)\\s*)+`, "i");
      const res = block.match(re);
      if (!res) return "";
      const matches = Array.from(block.slice(block.indexOf(res[0])).matchAll(/^>\s*(.+)$/gm));
      return matches.map((m) => m[1].trim()).join(" ");
    };

    const purposeMatch = block.match(/###\s*Purpose:\s*([^\n]+)/i);
    const purpose = purposeMatch ? purposeMatch[1].replace(/[*_#]/g, "").trim() : "";

    const voiceTypeMatch = block.match(/\*\*Voice\*\*\s*\(([^)]+)\)/i);
    const voiceType = voiceTypeMatch ? voiceTypeMatch[1].trim().toUpperCase() : "ON-CAMERA";

    let voice = "";
    const voiceMatch = block.match(/\*\*Voice\*\*[^\n]*\n>([^\n*]+)/i);
    if (voiceMatch) voice = voiceMatch[1].trim();

    let english = "";
    const engMatch = block.match(/\*\*English\*\*[^\n]*\n>([^\n*]+)/i);
    if (engMatch) english = engMatch[1].trim();

    const onScreen = getBlockquoteField("On-screen text") || getField("On-screen text");

    const usesRaw = getField("Uses");
    const uses = usesRaw
      ? usesRaw
          .split(/[,]/)
          .map((u) => u.trim())
          .filter(Boolean)
      : [];

    let imageId = getField("Image");
    if (!imageId) imageId = `s${shotNum}`;

    let prompt = "";
    const promptMatch = block.match(/\*\*AI Video Prompt\*\*[^\n]*\n([\s\S]*?)(?=\n##|\n#|\n---|$)/i);
    if (promptMatch) {
      prompt = promptMatch[1]
        .split("\n")
        .map((l) => l.replace(/^>\s*/, "").trim())
        .filter(Boolean)
        .join(" ");
    }

    shots.push({
      number: shotNum,
      time: shotTiming,
      purpose,
      visual: getField("Visual"),
      camera: getField("Camera"),
      action: getField("Action"),
      voice,
      voiceType,
      english,
      onScreenText: onScreen,
      uses,
      imageId,
      prompt,
    });
  }

  return {
    rawTitle,
    concept,
    sharedStyle,
    characters,
    backgrounds,
    characterNotes,
    shots,
  };
}

export function exportStoryToPdf(projectName: string, doc: ParsedStoryDocument, stills: string[]) {
  const printWindow = window.open("", "_blank");
  if (!printWindow) {
    alert("Please allow popups to export the PDF.");
    return;
  }

  const findStill = (id: string) => {
    const f = stills.find((s) => s.toLowerCase().startsWith(id.toLowerCase() + "."));
    return f ? fileUrl(projectName, `stills/${encodeURIComponent(f)}`) : null;
  };

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>${doc.concept["title"] || doc.rawTitle} — Screenplay Storyboard</title>
  <style>
    @page {
      size: A4;
      margin: 14mm 16mm;
    }
    *, *::before, *::after {
      box-sizing: border-box;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: #0f172a;
      background: #ffffff;
      margin: 0;
      padding: 0;
      line-height: 1.5;
      font-size: 11pt;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }
    header.doc-header {
      border-bottom: 2px solid #0f172a;
      padding-bottom: 12px;
      margin-bottom: 20px;
    }
    .header-badge {
      display: inline-block;
      font-size: 8pt;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      background: #0f172a;
      color: #ffffff;
      padding: 3px 8px;
      border-radius: 4px;
      margin-bottom: 6px;
    }
    h1.doc-title {
      font-size: 20pt;
      font-weight: 800;
      margin: 4px 0 8px 0;
      color: #0f172a;
      letter-spacing: -0.02em;
    }
    .meta-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
      margin-bottom: 20px;
      padding: 12px 14px;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      font-size: 9.5pt;
    }
    .meta-item strong {
      display: block;
      color: #64748b;
      font-size: 7.5pt;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .section-title {
      font-size: 12pt;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      border-bottom: 1px solid #cbd5e1;
      padding-bottom: 4px;
      margin: 20px 0 10px 0;
      color: #1e293b;
    }
    .shared-style-box {
      background: #f1f5f9;
      border-left: 4px solid #6366f1;
      padding: 10px 14px;
      font-size: 9.5pt;
      margin-bottom: 20px;
      border-radius: 0 4px 4px 0;
    }
    .cast-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-bottom: 20px;
    }
    .cast-card {
      border: 1px solid #e2e8f0;
      background: #ffffff;
      border-radius: 6px;
      padding: 10px 12px;
      font-size: 9pt;
      page-break-inside: avoid;
    }
    .cast-card h4 {
      margin: 0 0 4px 0;
      font-size: 10pt;
      color: #0f172a;
    }
    .shot-card {
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      margin-bottom: 16px;
      page-break-inside: avoid;
      break-inside: avoid;
      overflow: hidden;
    }
    .shot-header {
      background: #f1f5f9;
      border-bottom: 1px solid #e2e8f0;
      padding: 8px 12px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 10pt;
      font-weight: 700;
    }
    .shot-badge {
      background: #e2e8f0;
      padding: 2px 7px;
      border-radius: 3px;
      font-size: 8pt;
      font-weight: 700;
      color: #334155;
      text-transform: uppercase;
    }
    .shot-body {
      padding: 10px 12px;
      display: grid;
      grid-template-columns: 1.4fr 1fr;
      gap: 14px;
      font-size: 9pt;
    }
    .field-row {
      margin-bottom: 6px;
    }
    .field-label {
      font-weight: 700;
      color: #475569;
      font-size: 8pt;
      text-transform: uppercase;
      margin-bottom: 1px;
    }
    .dialogue-bubble {
      background: #eff6ff;
      border-left: 3px solid #3b82f6;
      padding: 6px 10px;
      border-radius: 0 4px 4px 0;
      margin-bottom: 8px;
    }
    .dialogue-voice {
      font-weight: 600;
      color: #1e3a8a;
    }
    .dialogue-trans {
      font-style: italic;
      color: #64748b;
      font-size: 8.5pt;
      margin-top: 2px;
    }
    .prompt-box {
      background: #f8fafc;
      border-top: 1px dashed #cbd5e1;
      padding: 6px 12px;
      font-size: 7.5pt;
      font-family: ui-monospace, Menlo, monospace;
      color: #64748b;
    }
    footer.doc-footer {
      border-top: 1px solid #e2e8f0;
      margin-top: 30px;
      padding-top: 10px;
      font-size: 8pt;
      color: #94a3b8;
      display: flex;
      justify-content: space-between;
    }
  </style>
</head>
<body>
  <header class="doc-header">
    <span class="header-badge">AI Commercial Storyboard &amp; Screenplay</span>
    <h1 class="doc-title">${doc.concept["title"] || doc.rawTitle}</h1>
    <div style="font-size: 9pt; color: #64748b;">
      Project: <strong>${projectName}</strong> · Generated via AI Video Studio · ${doc.shots.length} Scenes (${doc.concept["target duration"] || "~45s"})
    </div>
  </header>

  <div class="meta-grid">
    <div class="meta-item">
      <strong>Format</strong>
      <span>${doc.concept["format"] || "9:16 Vertical"}</span>
    </div>
    <div class="meta-item">
      <strong>Duration</strong>
      <span>${doc.concept["target duration"] || "~88s"}</span>
    </div>
    <div class="meta-item">
      <strong>Language</strong>
      <span>${doc.concept["language"] || "Tamil / English"}</span>
    </div>
    <div class="meta-item">
      <strong>Brand</strong>
      <span>${doc.concept["brand"] || projectName}</span>
    </div>
  </div>

  ${
    doc.sharedStyle
      ? `
    <div class="section-title">Shared Visual Aesthetic &amp; Camera Direction</div>
    <div class="shared-style-box">${doc.sharedStyle}</div>
  `
      : ""
  }

  ${
    doc.characters.length > 0
      ? `
    <div class="section-title">Cast &amp; Characters</div>
    <div class="cast-grid">
      ${doc.characters
        .map(
          (c) => `
        <div class="cast-card">
          <h4>${c.name}</h4>
          <div>${c.description}</div>
        </div>
      `
        )
        .join("")}
    </div>
  `
      : ""
  }

  ${
    doc.backgrounds.length > 0
      ? `
    <div class="section-title">Locations &amp; Settings</div>
    <div class="cast-grid">
      ${doc.backgrounds
        .map(
          (b) => `
        <div class="cast-card">
          <h4>${b.name}</h4>
          <div>${b.description}</div>
        </div>
      `
        )
        .join("")}
    </div>
  `
      : ""
  }

  <div class="section-title">Shot-by-Shot Storyboard (${doc.shots.length} Scenes)</div>

  ${doc.shots
    .map((s) => {
      const imgUrl = findStill(s.imageId);
      return `
    <div class="shot-card">
      <div class="shot-header">
        <div>
          <span>Shot ${s.number}</span>
          ${s.time ? `<span style="margin-left: 8px; color: #64748b; font-weight: normal;">${s.time}</span>` : ""}
        </div>
        <div>
          ${s.purpose ? `<span class="shot-badge">${s.purpose}</span>` : ""}
          <span style="font-size: 8pt; color: #64748b; margin-left: 8px;">Asset: ${s.imageId}</span>
        </div>
      </div>
      <div class="shot-body">
        <div>
          ${
            s.visual
              ? `
            <div class="field-row">
              <div class="field-label">Visual</div>
              <div>${s.visual}</div>
            </div>
          `
              : ""
          }
          ${
            s.camera
              ? `
            <div class="field-row">
              <div class="field-label">Camera</div>
              <div>${s.camera}</div>
            </div>
          `
              : ""
          }
          ${
            s.action
              ? `
            <div class="field-row">
              <div class="field-label">Action</div>
              <div>${s.action}</div>
            </div>
          `
              : ""
          }
          ${
            s.uses && s.uses.length > 0
              ? `
            <div class="field-row">
              <div class="field-label">Uses</div>
              <div style="font-size: 8pt; color: #64748b;">${s.uses.join(", ")}</div>
            </div>
          `
              : ""
          }
        </div>
        <div>
          ${
            s.voice
              ? `
            <div class="field-row">
              <div class="field-label">Voiceover (${s.voiceType})</div>
              <div class="dialogue-bubble">
                <div class="dialogue-voice">${s.voice}</div>
                ${s.english ? `<div class="dialogue-trans">${s.english}</div>` : ""}
              </div>
            </div>
          `
              : ""
          }
          ${
            s.onScreenText
              ? `
            <div class="field-row">
              <div class="field-label">On-Screen Text</div>
              <div style="padding: 4px 8px; background: #fef08a; border-radius: 3px; font-weight: 600; font-size: 8.5pt;">
                ${s.onScreenText}
              </div>
            </div>
          `
              : ""
          }
        </div>
      </div>
      ${
        s.prompt
          ? `
        <div class="prompt-box">
          <strong>AI Prompt:</strong> ${s.prompt}
        </div>
      `
          : ""
      }
    </div>
    `;
    })
    .join("")}

  <footer class="doc-footer">
    <div>${doc.concept["title"] || doc.rawTitle} · Screenplay Document</div>
    <div>Page generated by AI Studio · dlanzer.com</div>
  </footer>

  <script>
    window.addEventListener('load', () => {
      setTimeout(() => {
        window.print();
      }, 300);
    });
  </script>
</body>
</html>`;

  printWindow.document.open();
  printWindow.document.write(html);
  printWindow.document.close();
}

export function StoryDocumentView({
  text,
  name,
  stills,
  onSwitchToMarkdown,
  onExportPdf,
}: {
  text: string;
  name: string;
  stills: string[];
  onSwitchToMarkdown: () => void;
  onExportPdf?: () => void;
}) {
  const doc = parseStoryDocument(text);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const copyPrompt = (id: string, promptText: string) => {
    navigator.clipboard.writeText(promptText);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1800);
  };

  const findStill = (id: string) => {
    const f = stills.find((s) => s.toLowerCase().startsWith(id.toLowerCase() + "."));
    return f ? fileUrl(name, `stills/${encodeURIComponent(f)}`) : null;
  };

  const getPurposeTone = (p: string) => {
    const up = p.toUpperCase();
    if (up.includes("HOOK")) return "border-purple-500/40 bg-purple-500/15 text-purple-300";
    if (up.includes("AUDIENCE")) return "border-sky-500/40 bg-sky-500/15 text-sky-300";
    if (up.includes("PROBLEM")) return "border-amber-500/40 bg-amber-500/15 text-amber-300";
    if (up.includes("MYTH")) return "border-red-500/40 bg-red-500/15 text-red-300";
    if (up.includes("RESULT") || up.includes("PROOF")) return "border-emerald-500/40 bg-emerald-500/15 text-emerald-300";
    if (up.includes("CTA")) return "border-pink-500/40 bg-pink-500/15 text-pink-300";
    return "border-slate-700 bg-slate-800 text-slate-300";
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Document Actions Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-800 bg-[#0e0e17] px-4 py-3 shadow-sm">
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 rounded-lg border border-purple-500/40 bg-purple-500/10 px-3 py-1 text-xs font-bold text-purple-300">
            <Eye size={14} /> Document Preview
          </span>
          <span className="text-xs text-slate-400">
            {doc.shots.length} Scenes · Screenplay View
          </span>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            className="!border-slate-700 hover:!bg-slate-800 text-xs"
            onClick={onSwitchToMarkdown}
          >
            <FileCode2 size={14} /> Markdown Editor
          </Button>
          <Button
            variant="pink"
            className="text-xs font-semibold shadow-sm"
            onClick={() => (onExportPdf ? onExportPdf() : exportStoryToPdf(name, doc, stills))}
          >
            <Printer size={14} /> Export as PDF
          </Button>
        </div>
      </div>

      {/* Screenplay Cover / Header Panel */}
      <div className="relative overflow-hidden rounded-2xl border border-slate-800 bg-gradient-to-b from-[#131322] to-[#0a0a12] p-6 shadow-card">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-purple-500/30 bg-purple-500/10 px-3 py-0.5 text-[0.7rem] font-extrabold uppercase tracking-wider text-purple-300">
              <Film size={12} /> AI Commercial Screenplay
            </div>
            <h2 className="text-2xl font-black tracking-tight text-white sm:text-3xl">
              {doc.concept["title"] || doc.rawTitle}
            </h2>
            <p className="mt-1 text-xs text-slate-400">
              Project <span className="font-semibold text-slate-200">{name}</span> · {doc.shots.length} timed scenes
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div className="rounded-xl border border-slate-800 bg-slate-900/80 px-3 py-2">
              <span className="block text-[0.65rem] font-bold uppercase tracking-wider text-slate-400">Duration</span>
              <span className="text-sm font-extrabold text-white">{doc.concept["target duration"] || "~88s"}</span>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/80 px-3 py-2">
              <span className="block text-[0.65rem] font-bold uppercase tracking-wider text-slate-400">Format</span>
              <span className="text-sm font-extrabold text-white">{doc.concept["format"] || "9:16"}</span>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/80 px-3 py-2">
              <span className="block text-[0.65rem] font-bold uppercase tracking-wider text-slate-400">Language</span>
              <span className="text-sm font-extrabold text-white">{doc.concept["language"] || "English"}</span>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/80 px-3 py-2">
              <span className="block text-[0.65rem] font-bold uppercase tracking-wider text-slate-400">Brand</span>
              <span className="text-sm font-extrabold text-white">{doc.concept["brand"] || name}</span>
            </div>
          </div>
        </div>

        {/* Core narrative flow */}
        {doc.concept["core flow"] && (
          <div className="mt-5 border-t border-slate-800/80 pt-4">
            <span className="mb-2 block text-[0.68rem] font-bold uppercase tracking-wider text-slate-400">Narrative Arc &amp; Flow</span>
            <div className="flex flex-wrap gap-1.5">
              {doc.concept["core flow"].split("→").map((step, idx) => (
                <span
                  key={idx}
                  className="rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1 text-xs font-semibold text-slate-300"
                >
                  {step.trim()}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Shared Aesthetic Box */}
      {doc.sharedStyle && (
        <div className="rounded-2xl border border-purple-500/20 bg-purple-950/10 p-5 shadow-sm">
          <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-purple-300">
            <Palette size={15} /> Shared Visual Style &amp; Cinematic Lighting
          </div>
          <p className="text-xs leading-relaxed text-slate-300 sm:text-sm">{doc.sharedStyle}</p>
        </div>
      )}

      {/* Cast & Characters Grid */}
      {doc.characters.length > 0 && (
        <div>
          <h3 className="mb-3 flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-slate-300">
            <Users size={16} className="text-pink-400" /> Characters &amp; Talent ({doc.characters.length})
          </h3>
          <div className="grid gap-3 sm:grid-cols-2">
            {doc.characters.map((c) => {
              const imgUrl = findStill(c.id);
              return (
                <div
                  key={c.id}
                  className="flex gap-4 rounded-2xl border border-slate-800 bg-[#0e0e17] p-4 transition hover:border-slate-700"
                >
                  {imgUrl ? (
                    <img
                      src={imgUrl}
                      alt={c.name}
                      className="h-20 w-20 shrink-0 rounded-xl object-cover border border-slate-700 shadow-md"
                    />
                  ) : (
                    <div className="grid h-20 w-20 shrink-0 place-items-center rounded-xl border border-slate-800 bg-slate-900 text-slate-500 font-bold">
                      {c.name.slice(0, 2).toUpperCase()}
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <h4 className="text-sm font-bold text-white">{c.name}</h4>
                    <span className="mb-1.5 inline-block text-[0.68rem] font-mono text-purple-300">ID: {c.id}</span>
                    <p className="line-clamp-3 text-xs leading-relaxed text-slate-400">{c.description}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Backgrounds / Places Grid */}
      {doc.backgrounds.length > 0 && (
        <div>
          <h3 className="mb-3 flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-slate-300">
            <MapPin size={16} className="text-sky-400" /> Environments &amp; Sets ({doc.backgrounds.length})
          </h3>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {doc.backgrounds.map((b) => {
              const imgUrl = findStill(b.id);
              return (
                <div
                  key={b.id}
                  className="flex flex-col overflow-hidden rounded-2xl border border-slate-800 bg-[#0e0e17] transition hover:border-slate-700"
                >
                  {imgUrl ? (
                    <img src={imgUrl} alt={b.name} className="h-28 w-full object-cover" />
                  ) : (
                    <div className="grid h-28 w-full place-items-center border-b border-slate-800 bg-slate-900/60 text-xs text-slate-500 font-semibold">
                      {b.name}
                    </div>
                  )}
                  <div className="p-3">
                    <h4 className="text-xs font-bold text-white">{b.name}</h4>
                    <span className="block text-[0.65rem] font-mono text-slate-400">ID: {b.id}</span>
                    <p className="mt-1 line-clamp-2 text-[0.75rem] text-slate-400">{b.description}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Storyboard Shots / Scenes */}
      <div>
        <div className="mb-4 flex items-center justify-between border-b border-slate-800 pb-2">
          <h3 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-slate-200">
            <Layers size={16} className="text-brand" /> Scene-by-Scene Storyboard ({doc.shots.length})
          </h3>
          <span className="text-xs text-slate-400">Production Sequence</span>
        </div>

        {doc.shots.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-800 p-8 text-center text-slate-500">
            <p className="text-sm">No scenes parsed from script yet.</p>
            <Button variant="outline" className="mt-3 text-xs" onClick={onSwitchToMarkdown}>
              Open Markdown Editor
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            {doc.shots.map((s) => {
            const frameUrl = findStill(s.imageId);
            const isCopied = copiedId === s.number;

            return (
              <div
                key={s.number}
                className="overflow-hidden rounded-2xl border border-slate-800 bg-[#0c0c14] shadow-sm transition hover:border-slate-700/80"
              >
                {/* Shot Header */}
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 bg-[#12121e] px-4 py-2.5">
                  <div className="flex items-center gap-2.5">
                    <span className="grid h-6 min-w-6 place-items-center rounded-md bg-white font-mono text-xs font-black text-black">
                      {s.number}
                    </span>
                    <span className="text-xs font-extrabold text-slate-200">
                      Scene {s.number}
                    </span>
                    {s.time && (
                      <span className="flex items-center gap-1 rounded-md border border-slate-700 bg-slate-800 px-2 py-0.5 text-[0.68rem] font-semibold text-slate-300">
                        <Clock size={11} /> {s.time}
                      </span>
                    )}
                    {s.purpose && (
                      <span className={`rounded-md border px-2 py-0.5 text-[0.68rem] font-bold ${getPurposeTone(s.purpose)}`}>
                        {s.purpose}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <span className="rounded bg-slate-800/80 px-2 py-0.5 font-mono text-[0.7rem] text-slate-300">
                      Frame: {s.imageId}
                    </span>
                  </div>
                </div>

                {/* Shot Content Grid */}
                <div className="grid gap-4 p-4 lg:grid-cols-12">
                  {/* Left: Frame Thumbnail */}
                  <div className="lg:col-span-3">
                    <div className="relative aspect-[9/16] w-full max-w-[140px] overflow-hidden rounded-xl border border-slate-800 bg-slate-900 shadow-md">
                      {frameUrl ? (
                        <img src={frameUrl} alt={`Scene ${s.number}`} className="h-full w-full object-cover" />
                      ) : (
                        <div className="flex h-full w-full flex-col items-center justify-center p-2 text-center text-slate-500">
                          <Film size={22} className="mb-1 text-slate-600" />
                          <span className="text-[0.65rem] font-bold">STILL: {s.imageId}</span>
                          <span className="text-[0.55rem] text-slate-600">Pending render</span>
                        </div>
                      )}
                      <span className="absolute bottom-1 right-1 rounded bg-black/80 px-1 text-[0.6rem] font-mono text-white/80">
                        9:16
                      </span>
                    </div>
                  </div>

                  {/* Center: Action & Camera */}
                  <div className="space-y-3 lg:col-span-5">
                    {s.visual && (
                      <div>
                        <span className="mb-0.5 block text-[0.68rem] font-bold uppercase tracking-wider text-slate-400">
                          Visual Scene
                        </span>
                        <p className="text-xs leading-relaxed text-slate-200">{s.visual}</p>
                      </div>
                    )}

                    {s.camera && (
                      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-2.5">
                        <span className="mb-0.5 flex items-center gap-1 text-[0.65rem] font-bold uppercase tracking-wider text-sky-300">
                          <Video size={12} /> Camera Movement
                        </span>
                        <p className="text-xs text-slate-300">{s.camera}</p>
                      </div>
                    )}

                    {s.action && (
                      <div>
                        <span className="mb-0.5 block text-[0.68rem] font-bold uppercase tracking-wider text-slate-400">
                          Talent Action
                        </span>
                        <p className="text-xs text-slate-300">{s.action}</p>
                      </div>
                    )}

                    {s.uses && s.uses.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1 pt-1">
                        <span className="text-[0.65rem] font-semibold text-slate-400">Uses:</span>
                        {s.uses.map((u, i) => (
                          <span
                            key={i}
                            className="rounded-md border border-slate-800 bg-slate-900 px-2 py-0.5 font-mono text-[0.68rem] text-slate-300"
                          >
                            {u}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Right: Audio & Overlay */}
                  <div className="space-y-3 lg:col-span-4">
                    {s.voice ? (
                      <div className="rounded-xl border border-blue-500/25 bg-blue-500/10 p-3">
                        <div className="mb-1 flex items-center justify-between">
                          <span className="flex items-center gap-1 text-[0.65rem] font-bold uppercase tracking-wider text-blue-300">
                            <Mic size={12} /> Dialogue / Voice
                          </span>
                          <span className="rounded bg-blue-500/20 px-1.5 py-0.5 text-[0.62rem] font-bold text-blue-200">
                            {s.voiceType}
                          </span>
                        </div>
                        <p className="font-semibold text-xs leading-relaxed text-blue-100">{s.voice}</p>
                        {s.english && (
                          <p className="mt-1 border-t border-blue-500/20 pt-1 text-[0.72rem] italic text-slate-300">
                            "{s.english}"
                          </p>
                        )}
                      </div>
                    ) : (
                      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-2.5 text-xs text-slate-500 italic">
                        No dialogue (Music / Ambience)
                      </div>
                    )}

                    {s.onScreenText && (
                      <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-2.5">
                        <span className="mb-0.5 flex items-center gap-1 text-[0.65rem] font-bold uppercase tracking-wider text-amber-300">
                          <Type size={12} /> On-Screen Graphics
                        </span>
                        <p className="font-bold text-xs text-amber-100">{s.onScreenText}</p>
                      </div>
                    )}
                  </div>
                </div>

                {/* AI Prompt Footer */}
                {s.prompt && (
                  <div className="flex items-center justify-between border-t border-slate-800/70 bg-[#09090f] px-4 py-2 text-xs">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="shrink-0 text-[0.68rem] font-bold uppercase tracking-wider text-slate-400">
                        Prompt:
                      </span>
                      <span className="truncate font-mono text-[0.72rem] text-slate-400">
                        {s.prompt}
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() => copyPrompt(s.number, s.prompt)}
                      className="ml-3 flex shrink-0 items-center gap-1 rounded-md border border-slate-800 bg-slate-900 px-2 py-1 text-[0.68rem] font-semibold text-slate-300 hover:bg-slate-800"
                    >
                      {isCopied ? (
                        <>
                          <Check size={11} className="text-emerald-400" /> Copied
                        </>
                      ) : (
                        <>
                          <Copy size={11} /> Copy
                        </>
                      )}
                    </button>
                  </div>
                )}
              </div>
            );
          })}
          </div>
        )}
      </div>
    </div>
  );
}
