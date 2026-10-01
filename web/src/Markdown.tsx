import { Fragment, type ReactNode } from "react";

/** A small, safe Markdown renderer for chat replies: **bold**, *italic*, `code`, # headings, - / 1. lists and line breaks. Builds elements, never HTML. */
const INLINE = /(\*\*[^*\n]+\*\*|__[^_\n]+__|`[^`\n]+`|\*[^*\s][^*\n]*\*|_[^_\s][^_\n]*_)/g;

function inline(text: string, key: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const k = `${key}-${i}`;
    if (/^\*\*[^*]+\*\*$/.test(part) || /^__[^_]+__$/.test(part)) return <strong key={k} className="font-bold text-white">{inline(part.slice(2, -2), k)}</strong>;
    if (/^`[^`]+`$/.test(part)) return <code key={k} className="rounded bg-white/10 px-1 py-0.5 font-mono text-[0.85em]">{part.slice(1, -1)}</code>;
    if (/^\*[^*]+\*$/.test(part) || /^_[^_]+_$/.test(part)) return <em key={k}>{inline(part.slice(1, -1), k)}</em>;
    return <Fragment key={k}>{part}</Fragment>;
  });
}

export function Markdown({ text }: { text: string }) {
  const out: ReactNode[] = []; const lines = text.replace(/\r\n?/g, "\n").split("\n");
  let list: { ordered: boolean; items: string[] } | null = null; let para: string[] = [];
  const flushPara = () => { if (para.length) { const n = out.length; out.push(<p key={`p${n}`} className="my-1 first:mt-0 last:mb-0">{para.map((l, i) => <Fragment key={i}>{i > 0 && <br />}{inline(l, `p${n}-${i}`)}</Fragment>)}</p>); para = []; } };
  const flushList = () => {
    if (!list) return; const n = out.length; const Tag = list.ordered ? "ol" : "ul";
    out.push(<Tag key={`l${n}`} className={`my-1 space-y-0.5 pl-5 ${list.ordered ? "list-decimal" : "list-disc"}`}>{list.items.map((t, i) => <li key={i}>{inline(t, `l${n}-${i}`)}</li>)}</Tag>); list = null;
  };
  lines.forEach((raw) => {
    const line = raw.trimEnd(); let m: RegExpMatchArray | null;
    if ((m = line.match(/^\s*[-*•]\s+(.*)$/))) { flushPara(); if (!list || list.ordered) { flushList(); list = { ordered: false, items: [] }; } list.items.push(m[1]); }
    else if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) { flushPara(); if (!list || !list.ordered) { flushList(); list = { ordered: true, items: [] }; } list.items.push(m[1]); }
    else if ((m = line.match(/^#{1,6}\s+(.*)$/))) { flushPara(); flushList(); out.push(<p key={`h${out.length}`} className="mb-1 mt-2 font-bold text-white first:mt-0">{inline(m[1], `h${out.length}`)}</p>); }
    else if (!line.trim()) { flushPara(); flushList(); }
    else { flushList(); para.push(line); }
  });
  flushPara(); flushList();
  return <>{out}</>;
}
