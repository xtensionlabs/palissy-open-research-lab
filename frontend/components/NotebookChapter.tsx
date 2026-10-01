"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { CycleState, Notebook, Project } from "@/lib/types";
import { CodeBlock } from "./CodeBlock";
import { Markdown } from "./Markdown";

export function NotebookChapter({ project, state }: { project: Project; state: CycleState | null }) {
  const [nb, setNb] = useState<Notebook | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ready = !!project.notebook_path;

  useEffect(() => {
    if (!ready) return;
    api
      .notebook(project.id)
      .then(setNb)
      .catch((e: Error) => setError(e.message));
  }, [ready, project.id]);

  function download() {
    if (!nb) return;
    const blob = new Blob([JSON.stringify(nb, null, 1)], { type: "application/x-ipynb+json" });
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement("a"), { href: url, download: `palissy-${project.id}.ipynb` });
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      <h2 className="ch-title">Notebook</h2>
      {!ready && <p className="empty">Assembled when the run finishes.</p>}
      {error && <p className="notice">{error}</p>}
      {ready && !nb && !error && <div className="skeleton" style={{ width: "60%" }} />}
      {nb && (
        <>
          {state?.data_source === "simulated" && (
            <div className="simlabel" role="note">
              <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
                <circle cx="9" cy="9" r="7.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
                <path d="M9 5v5M9 12.4v.2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
              <span>Tested on simulated data, within the model&rsquo;s stated assumptions.</span>
            </div>
          )}
          <article className="nbdoc">
            {nb.cells.map((c, i) => {
              const src = c.source.join("");
              if (c.cell_type === "markdown") return <Markdown key={i} source={src} skipTitle={i === 0} />;
              const out = (c.outputs ?? []).flatMap((o) => o.text ?? []).join("");
              return (
                <div className="cell" key={i}>
                  <span className="io">In</span>
                  <div>
                    <CodeBlock code={src} label={src.startsWith('"""Palissy harness') ? "Seed harness" : "Experiment code"} />
                    {out && <pre className="runlog out">{out}</pre>}
                  </div>
                </div>
              );
            })}
          </article>
          <button type="button" className="btn dl" onClick={download}>
            Download .ipynb
          </button>
        </>
      )}
    </>
  );
}
