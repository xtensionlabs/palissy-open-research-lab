import { Fragment } from "react";

const INLINE = /(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;

/** Minimal inline markdown: **bold**, *italic*, `code`, [text](url). Nothing else, no HTML. */
export function Inline({ text }: { text: string }) {
  const parts = text.split(INLINE).filter((p) => p !== "");
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith("**") && p.endsWith("**") && p.length > 4) return <strong key={i}>{p.slice(2, -2)}</strong>;
        if (p.startsWith("*") && p.endsWith("*") && p.length > 2) return <em key={i}>{p.slice(1, -1)}</em>;
        if (p.startsWith("`") && p.endsWith("`") && p.length > 2) return <code key={i} className="mono">{p.slice(1, -1)}</code>;
        const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(p);
        if (link && /^https?:\/\//.test(link[2])) {
          return <a key={i} href={link[2]} target="_blank" rel="noreferrer noopener">{link[1]}</a>;
        }
        return <Fragment key={i}>{p}</Fragment>;
      })}
    </>
  );
}

/** Italicise abbreviated species names ("E. coli") in a question. */
export function Question({ text }: { text: string }) {
  const parts = text.split(/(\b[A-Z]\. [a-z]{3,}\b)/);
  return (
    <>
      {parts.map((p, i) => (i % 2 === 1 ? <em key={i}>{p}</em> : <Fragment key={i}>{p}</Fragment>))}
    </>
  );
}
