"use client";

import { buildChain, type Claim } from "@/lib/provenance";
import type { ProvRecord } from "@/lib/types";

/** Cut at a word boundary so a quote never ends mid-word. */
function clip(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, max);
  return `${cut.slice(0, Math.max(cut.lastIndexOf(" "), 40))}…`;
}

const KIND_LABEL = { claim: "Claim", human: "Human", model: "Model", search: "Search", sandbox: "Sandbox", source: "Source", rule: "Rule" } as const;

export function Margin({
  claim, records, open, onClose,
}: {
  claim: Claim | null;
  records: ProvRecord[];
  open: boolean;
  onClose: () => void;
}) {
  const chain = claim ? buildChain(records, claim) : [];
  return (
    <aside className={`margin${open ? " open" : ""}`} aria-label="Where it came from">
      <header>
        <span className="sc">Where it came from</span>
        <button type="button" className="close" onClick={onClose}>Close</button>
      </header>
      {!claim ? (
        <p className="margin-empty">Click an underlined line or a source number.</p>
      ) : (
        <div className="note">
          <p className="quote">{clip(claim.text, 150)}</p>
          {chain.length === 0 ? (
            <p className="margin-empty">No record found for this yet.</p>
          ) : (
            <ol className="chain">
              {chain.map((it) => (
                <li key={it.key} className={it.kind}>
                  <span className="kind">{KIND_LABEL[it.kind]}</span>
                  <span className="what">{it.title}</span>
                  {it.lines.map((l, i) => <span className="m" key={i}>{l}</span>)}
                  {it.quote && <span className="quote-h">“{it.quote}”</span>}
                  {it.recordId && <span className="m">{it.recordId}</span>}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </aside>
  );
}
