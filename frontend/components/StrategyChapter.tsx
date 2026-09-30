"use client";

import { useState } from "react";
import type { CycleState } from "@/lib/types";

type Mode = "changes" | "before" | "after";

function Lessons({ items, mark }: { items: { text: string; kind: "keep" | "add" | "rem" }[]; mark?: boolean }) {
  return (
    <ul className="lesson-diff">
      {items.map((l) => (
        <li key={`${l.kind}-${l.text}`} className={l.kind === "keep" ? undefined : l.kind}>
          <span className="gl">{!mark ? "·" : l.kind === "add" ? "+" : l.kind === "rem" ? "−" : "·"}</span>
          <span className="tx">{l.text}</span>
        </li>
      ))}
    </ul>
  );
}

export function StrategyChapter({ state, current }: { state: CycleState | null; current: string[] }) {
  const [mode, setMode] = useState<Mode>("changes");
  const before = state?.lessons_before ?? [];
  const after = state?.lessons_after ?? [];
  const reflected = !!state && (after.length > 0 || state.change_summary !== "");

  if (!reflected) {
    return (
      <>
        <h2 className="ch-title">Strategy</h2>
        {current.length === 0 ? (
          <p className="empty">No lessons yet. They appear after the first reflection.</p>
        ) : (
          <>
            <p className="sc" style={{ marginBottom: 20 }}>
              Lessons in force
            </p>
            <div className="sheet">
              <Lessons items={current.map((text) => ({ text, kind: "keep" as const }))} />
            </div>
            <p className="pricenote">This run&rsquo;s reflection will change them.</p>
          </>
        )}
      </>
    );
  }

  const kept = after.filter((l) => before.includes(l));
  const added = after.filter((l) => !before.includes(l));
  const removed = before.filter((l) => !after.includes(l));

  return (
    <>
      <h2 className="ch-title">Strategy</h2>
      <div className="seg" role="group" aria-label="View">
        {(["changes", "before", "after"] as Mode[]).map((m) => (
          <button key={m} aria-pressed={mode === m} onClick={() => setMode(m)}>
            {m[0].toUpperCase() + m.slice(1)}
          </button>
        ))}
      </div>
      <div className="sheet">
        {mode === "changes" && (
          <Lessons
            mark
            items={[
              ...kept.map((text) => ({ text, kind: "keep" as const })),
              ...added.map((text) => ({ text, kind: "add" as const })),
              ...removed.map((text) => ({ text, kind: "rem" as const })),
            ]}
          />
        )}
        {mode === "before" &&
          (before.length ? (
            <Lessons items={before.map((text) => ({ text, kind: "keep" as const }))} />
          ) : (
            <p className="empty" style={{ padding: 0 }}>None yet. This was the first run.</p>
          ))}
        {mode === "after" && <Lessons items={after.map((text) => ({ text, kind: "keep" as const }))} />}
      </div>
      {mode === "changes" && (
        <p className="legend">
          <span className="a">added</span>
          <span className="r">removed</span>
          <span>kept</span>
        </p>
      )}
      <p className="pricenote">The next run starts from the &ldquo;after&rdquo; list.</p>
    </>
  );
}
