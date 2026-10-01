"use client";

import { useEffect, useState } from "react";
import { clock, usd } from "@/lib/format";
import type { Gate, Project, ProvRecord } from "@/lib/types";
import { Question } from "./Inline";

const GATE_NAME = { triage: "Question", hypothesis: "Hypothesis", experiment_design: "Experiment", strategy_update: "Strategy" } as const;

export function Masthead({
  project, records, allCost, gate,
}: {
  project: Project;
  records: ProvRecord[];
  allCost: number | null;
  gate: Gate | null;
}) {
  const running = project.status === "running";
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, [running]);

  const last = records.length ? records[records.length - 1].ts : project.created_at;
  const elapsed = (running ? now : last) - project.created_at;

  return (
    <header className="masthead">
      <p className="eyebrow sc">Project {project.id}</p>
      <h1><Question text={project.question} /></h1>
      <dl className="meta">
        <div><dt>Elapsed</dt><dd>{clock(elapsed)}</dd></div>
        <div><dt>This project</dt><dd>{usd(project.cost_usd)}</dd></div>
        {allCost !== null && <div><dt>All projects</dt><dd>{usd(allCost)}</dd></div>}
      </dl>
      {gate && (
        <a className="waiting-pill" href="#gate">
          <span className="dot" aria-hidden="true" />
          Waiting for you: {GATE_NAME[gate.stage]}
        </a>
      )}
    </header>
  );
}
