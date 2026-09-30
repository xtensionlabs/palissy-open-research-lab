"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CostChapter } from "@/components/CostChapter";
import { Index, type Chapter } from "@/components/Index";
import { Margin } from "@/components/Margin";
import { Masthead } from "@/components/Masthead";
import { NotebookChapter } from "@/components/NotebookChapter";
import { ResearchChapter } from "@/components/ResearchChapter";
import { StrategyChapter } from "@/components/StrategyChapter";
import { api } from "@/lib/api";
import { claimsFrom, type Claim } from "@/lib/provenance";
import type { Health } from "@/lib/types";
import { useProject } from "@/lib/useProject";

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const { project, records, decisions, routing, error, notFound, refresh } = useProject(id);
  const [chapter, setChapter] = useState<Chapter>("research");
  const [claim, setClaim] = useState<Claim | null>(null);
  const [marginOpen, setMarginOpen] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [allCost, setAllCost] = useState<number | null>(null);
  const [lessons, setLessons] = useState<string[]>([]);

  useEffect(() => {
    api.health().then(setHealth).catch(() => undefined);
  }, []);

  // Spend and lessons move with the run, so refetch when records change.
  useEffect(() => {
    api.costs().then((c) => setAllCost(c.total_usd)).catch(() => undefined);
    api.strategy().then((s) => setLessons(s.lessons)).catch(() => undefined);
  }, [records.length, project?.status]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMarginOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const state = project?.state ?? null;
  const claims = useMemo(() => claimsFrom(state, records), [state, records]);
  const select = useCallback((c: Claim) => { setClaim(c); setMarginOpen(true); }, []);

  const goToStage = useCallback((anchor: string) => {
    setChapter("research");
    setTimeout(() => document.getElementById(anchor)?.scrollIntoView({ behavior: "smooth", block: "start" }), 30);
  }, []);

  if (notFound) {
    return (
      <main className="home">
        <h1>That project doesn&rsquo;t exist.</h1>
        <Link className="btn" href="/">Back to start</Link>
      </main>
    );
  }
  if (error && !project) {
    return (
      <main className="home">
        <h1>Can&rsquo;t reach the lab.</h1>
        <p className="notice">{error} Start the server with <code className="mono">palissy-serve</code>.</p>
        <button className="btn" onClick={() => void refresh()}>Try again</button>
      </main>
    );
  }
  if (!project) {
    return (
      <main className="home" aria-busy="true">
        <div className="skeleton" style={{ width: "70%", height: 34 }} />
        <div className="skeleton" style={{ width: "40%", marginTop: 24 }} />
      </main>
    );
  }

  const gate = project.pending_gate;

  return (
    <div className="shell">
      {gate && <a className="skip" href="#gate">Skip to the decision</a>}
      <Index
        project={project}
        state={state}
        chapter={chapter}
        onChapter={setChapter}
        health={health}
        lessonCount={lessons.length}
        goToStage={goToStage}
      />

      <main className="main">
        <Masthead project={project} records={records} allCost={allCost} gate={gate} />

        {(project.status === "failed" || project.status === "interrupted") && (
          <div className="notice" role="alert">
            {project.status === "failed" ? "This run stopped." : "This run was interrupted."}{" "}
            {project.error && <span>{project.error}</span>}
          </div>
        )}
        {error && <div className="notice soft" role="status">Connection lost, trying again. {error}</div>}

        <div className={`chapter ${chapter === "research" ? "on" : ""}`} id="chapter-research" role="tabpanel" hidden={chapter !== "research"}>
          {state ? (
            <ResearchChapter
              project={project}
              state={state}
              records={records}
              decisions={decisions}
              gate={gate}
              routing={routing}
              health={health}
              claims={claims}
              activeClaim={claim?.key ?? null}
              onSelect={select}
              onDecided={() => void refresh()}
              openChapter={setChapter}
            />
          ) : (
            <p className="notice soft">
              This project was started before progress snapshots were saved, so only its cost and notebook are available.
            </p>
          )}
        </div>

        <div className={`chapter wide ${chapter === "cost" ? "on" : ""}`} id="chapter-cost" role="tabpanel" hidden={chapter !== "cost"}>
          <CostChapter project={project} records={records} routing={routing} allCost={allCost} />
        </div>
        <div className={`chapter ${chapter === "strategy" ? "on" : ""}`} id="chapter-strategy" role="tabpanel" hidden={chapter !== "strategy"}>
          <StrategyChapter state={state} current={lessons} />
        </div>
        <div className={`chapter wide ${chapter === "notebook" ? "on" : ""}`} id="chapter-notebook" role="tabpanel" hidden={chapter !== "notebook"}>
          <NotebookChapter project={project} state={state} />
        </div>
      </main>

      {marginOpen && <div className="scrim" aria-hidden="true" onClick={() => setMarginOpen(false)} />}
      <Margin claim={claim} records={records} open={marginOpen} onClose={() => setMarginOpen(false)} />
    </div>
  );
}
