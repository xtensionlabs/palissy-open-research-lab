import { Fragment } from "react";
import { Inline } from "./Inline";

type Block =
  | { t: "h"; level: number; text: string }
  | { t: "p"; text: string }
  | { t: "ul"; items: string[] }
  | { t: "table"; head: string[]; rows: string[][] };

const cells = (line: string) =>
  line.replace(/^\s*\||\|\s*$/g, "").split("|").map((c) => c.trim());

function parse(src: string): Block[] {
  const lines = src.split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) { blocks.push({ t: "h", level: h[1].length, text: h[2] }); i++; continue; }
    if (line.trim().startsWith("|") && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] ?? "")) {
      const head = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(cells(lines[i++]));
      blocks.push({ t: "table", head, rows });
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*]\s+/, ""));
      blocks.push({ t: "ul", items });
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\s*[-*]\s+|\s*\|)/.test(lines[i])) para.push(lines[i++]);
    blocks.push({ t: "p", text: para.join(" ") });
  }
  return blocks;
}

export function Markdown({ source, skipTitle = false }: { source: string; skipTitle?: boolean }) {
  const blocks = parse(source).filter((b, i) => !(skipTitle && i === 0 && b.t === "h"));
  return (
    <div className="nb-md">
      {blocks.map((b, i) => (
        <Fragment key={i}>
          {b.t === "h" && (b.level <= 2 ? <h3 className="sec">{b.text}</h3> : <h4>{b.text}</h4>)}
          {b.t === "p" && <p><Inline text={b.text} /></p>}
          {b.t === "ul" && (
            <ul>{b.items.map((it, j) => <li key={j}><Inline text={it} /></li>)}</ul>
          )}
          {b.t === "table" && (
            <div className="scroll-x">
              <table className="ledger">
                <thead><tr>{b.head.map((c, j) => <th key={j}>{c}</th>)}</tr></thead>
                <tbody>
                  {b.rows.map((r, j) => (
                    <tr key={j}>{r.map((c, k) => <td key={k}><Inline text={c} /></td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Fragment>
      ))}
    </div>
  );
}
