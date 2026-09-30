"use client";

import { STAGES, usd } from "@/lib/format";
import type { CycleState, Health, Project } from "@/lib/types";
import { Brand } from "./Brand";

export type Chapter = "research" | "cost" | "strategy" | "notebook";

const CHAPTERS: { key: Chapter; label: string }[] = [
  { key: "research", label: "Research" },
  { key: "cost", label: "Cost" },
  { key: "strategy", label: "Strategy" },
  { key: "notebook", label: "Notebook" },
];

export function Index({
  project, state, chapter, onChapter, health, lessonCount, goToStage,
}: {
  project: Project;
  state: CycleState | null;
  chapter: Chapter;
  onChapter: (c: Chapter) => void;
  health: Health | null;
  lessonCount: number;
  goToStage: (key: string) => void;
}) {
  const current = !state ? -1 : state.stage === "done" ? STAGES.length : STAGES.findIndex((s) => s.key === state.stage);
  const hint: Partial<Record<Chapter, string>> = {
    cost: usd(project.cost_usd),
    strategy: lessonCount ? String(lessonCount) : undefined,
  };
  return (
    <nav className="index" aria-label="Project">
      <Brand />
      <dl className="proj-meta">
        <div>
          <dt>Status</dt>
          <dd><span className={`status ${project.status}`}><i aria-hidden="true" />{project.status}</span></dd>
        </div>
        <div><dt>Project</dt><dd>{project.id}</dd></div>
      </dl>

      <ol className="stages" aria-label="Stages">
        {STAGES.map((s, i) => {
          const cls = i < current ? "done" : i === current && project.status !== "done" ? "current" : "";
          return (
            <li key={s.key} className={cls}>
              <a
                href={`#${s.key === "notebook" ? "notebook-stage" : s.key}`}
                aria-current={cls === "current" ? "step" : undefined}
                onClick={(e) => { e.preventDefault(); goToStage(s.key === "notebook" ? "notebook-stage" : s.key); }}
              >
                <span className="node" aria-hidden="true" />
                <span className="t">{s.label}</span>
              </a>
            </li>
          );
        })}
      </ol>

      <ul className="chapters" role="tablist" aria-label="Chapters">
        {CHAPTERS.map((c) => (
          <li key={c.key} role="presentation">
            <button
              role="tab"
              aria-selected={chapter === c.key}
              aria-controls={`chapter-${c.key}`}
              onClick={() => onChapter(c.key)}
            >
              {c.label}
              {hint[c.key] && <small>{hint[c.key]}</small>}
            </button>
          </li>
        ))}
      </ul>

      {health && (
        <p className="sandbox-line">
          Sandbox <b>{health.executor}</b>
          {health.image && (
            <>
              <br />
              <code>{health.image.split("/").map((part, i, all) => (
                <span key={i}>{part}{i < all.length - 1 && <>/<wbr /></>}</span>
              ))}</code>
            </>
          )}
        </p>
      )}
    </nav>
  );
}
