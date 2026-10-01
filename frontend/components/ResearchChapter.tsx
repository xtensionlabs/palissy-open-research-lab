"use client";

import { useState } from "react";
import { STAGES, modelName, seconds, usd, host } from "@/lib/format";
import type { Claim } from "@/lib/provenance";
import type {
  CycleState, Decision, Gate, Health, Project, ProvRecord, Routing, StageKey,
} from "@/lib/types";
import { ClaimText, Footnote } from "./Claim";
import { CodeBlock } from "./CodeBlock";
import { GateCard } from "./GateCard";
import { firstSentence } from "@/lib/text";
import { Inline } from "./Inline";
import { Checks, CriticNote, PreReg, hasContract, hasCritique } from "./PreReg";

type Status = "done" | "current" | "pending";
const ORDER: string[] = STAGES.map((s) => s.key);
const NO = (key: StageKey) => ORDER.indexOf(key) + 1;
const ARM_LABEL = { treatment: "Treatment", positive: "Positive control", negative: "Negative control" } as const;

// Which record stages belong to each pipeline stage, for the per-stage timing and cost.
const RECORD_STAGES: Record<StageKey, string[]> = {
  triage: ["triage"],
  literature: ["literature", "literature_summary"],
  hypothesis: ["hypothesis"],
  experiment_design: ["experiment_design", "design_critic", "design_critic_escalated"],
  execution: ["execution", "code_generation"],
  analysis: ["analysis"],
  reflection: ["reflection"],
  notebook: [],
};

interface Props {
  project: Project;
  state: CycleState;
  records: ProvRecord[];
  decisions: Decision[];
  gate: Gate | null;
  routing: Routing | null;
  health: Health | null;
  claims: {
    hypothesis: Claim | null;
    code: Claim | null;
    verdict: Claim | null;
    lessons: Claim | null;
    citation: (n: number) => Claim | null;
  };
  activeClaim: string | null;
  onSelect: (c: Claim) => void;
  onDecided: () => void;
  openChapter: (c: "notebook") => void;
}

function Toggle({ open, onClick, children }: { open: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" className="toggle" aria-expanded={open} onClick={onClick}>
      <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M3 1l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" /></svg>
      {children}
    </button>
  );
}

function Section({
  no, id, title, status, badge, stat, children,
}: {
  no: number; id: string; title: string; status: Status | "failed"; badge: [string, string]; stat?: React.ReactNode; children?: React.ReactNode;
}) {
  return (
    <section className={`stage ${status === "failed" ? "current" : status}`} id={id} aria-labelledby={`${id}-h`}>
      <div className="head">
        <span className="no" aria-hidden="true">{no}</span>
        <h2 id={`${id}-h`}>{title}</h2>
        <span className={`badge ${badge[0]}`}>{badge[1]}</span>
        {stat && <span className="stat">{stat}</span>}
      </div>
      {children && <div className="stage-body">{children}</div>}
    </section>
  );
}

export function ResearchChapter(p: Props) {
  const { project, state: st, records, gate, decisions } = p;
  const [openKey, setOpenKey] = useState<string | null>(null);
  const flip = (k: string) => setOpenKey(openKey === k ? null : k);

  const current = st.stage === "done" ? ORDER.length : ORDER.indexOf(st.stage);
  const broken = project.status === "failed" || project.status === "interrupted";
  const statusOf = (key: StageKey): Status => {
    const i = ORDER.indexOf(key);
    return i < current ? "done" : i === current && project.status !== "done" ? "current" : i === current ? "done" : "pending";
  };
  const badgeFor = (key: StageKey, awaiting: boolean): [string, string] => {
    const s = statusOf(key);
    if (s === "done") return ["done", "Done"];
    if (s === "pending") return ["pend", "Up next"];
    if (broken) return ["fail", project.status === "failed" ? "Stopped" : "Interrupted"];
    return awaiting ? ["wait", "Awaiting you"] : ["run", "Working"];
  };
  const stat = (key: StageKey) => {
    const rs = records.filter((r) => RECORD_STAGES[key].includes(r.stage));
    if (!rs.length) return null;
    const secs = rs.reduce((a, r) => a + r.latency_s, 0);
    const cost = rs.reduce((a, r) => a + r.cost_usd, 0);
    const model = [...rs].reverse().find((r) => r.kind === "model")?.model;
    const tier = modelName(model).tier;
    return (
      <>
        {tier && <span>{tier}</span>}
        <span className="mono">{seconds(secs)}</span>
        {cost > 0 && <span className="mono">{usd(cost, 5)}</span>}
      </>
    );
  };

  const gateFor = (stage: Gate["stage"]) => (gate && gate.stage === stage ? gate : null);
  const decisionsFor = (stage: string) => decisions.filter((d) => d.stage === stage);
  const working = (key: StageKey) => statusOf(key) === "current" && !broken;
  const sandboxRuns = records.filter((r) => r.kind === "sandbox").sort((a, b) => a.ts - b.ts);
  const codeLines = st.code ? st.code.replace(/\n$/, "").split("\n").length : 0;
  const contract = hasContract(st.contract) ? st.contract : null;
  const critic = hasCritique(st.critique) ? st.critique : null;
  const triage = st.triage && "category" in st.triage ? st.triage : null;
  const checks = st.checks ?? [];
  const reasons = st.verdict_reasons ?? [];
  const unusable = st.verdict === "inconclusive" || st.verdict === "failed";
  const armOf = (r: ProvRecord) => (r.inputs.args as string[] | undefined)?.[0] as keyof typeof ARM_LABEL | undefined;

  const decisionLine = (d: Decision) =>
    d.action === "approve" ? "You approved it."
    : d.action === "inject" ? `You added: “${d.payload}”`
    : d.action === "reject" ? `You rejected it: “${d.payload}”`
    : `You edited it.`;

  return (
    <>
      {/* QUESTION CHECK */}
      <Section no={NO("triage")} id="triage" title="Question" status={statusOf("triage")}
        badge={badgeFor("triage", !!gateFor("triage"))} stat={stat("triage")}>
        {gateFor("triage") ? (
          <GateCard key={gate!.id} gate={gate!} records={records} routing={p.routing} health={p.health} onDecided={p.onDecided} />
        ) : triage ? (
          triage.category === "testable" ? (
            <p className="oneline">Testable by simulation.</p>
          ) : (
            <>
              <p className="oneline"><b className="flag-word">{triage.label}</b> {triage.reason}</p>
              <p className="decided-line">
                {triage.decision === "reframed"
                  ? <>You reframed it: <i>{st.question}</i></>
                  : "You chose to continue knowingly."}
              </p>
            </>
          )
        ) : statusOf("triage") === "done" ? (
          <p className="oneline pend">Not checked on this older run.</p>
        ) : (
          <p className="oneline pend">{working("triage") ? "Checking whether a simulation can test this…" : "Whether a simulation can test this."}</p>
        )}
      </Section>

      {/* LITERATURE */}
      <Section no={NO("literature")} id="literature" title="Literature" status={statusOf("literature")}
        badge={badgeFor("literature", false)} stat={stat("literature")}>
        {st.literature_summary ? (
          <>
            <p className="oneline">
              <Inline text={firstSentence(st.literature_summary)} />
              {st.literature.slice(0, 6).map((_, i) => (
                <Footnote key={i} n={i + 1} claim={p.claims.citation(i + 1)} active={p.activeClaim} onSelect={p.onSelect} />
              ))}
            </p>
            <Toggle open={openKey === "lit"} onClick={() => flip("lit")}>
              {openKey === "lit" ? "Hide" : `${st.literature.length} sources and summary`}
            </Toggle>
            {openKey === "lit" && (
              <div className="detail">
                <blockquote className="summary"><Inline text={st.literature_summary} /></blockquote>
                <ol className="sources" style={{ marginTop: 20 }}>
                  {st.literature.map((s, i) => (
                    <li key={i}>
                      <span className="mono">[{i + 1}]</span>
                      <span>
                        <span className="ttl">{s.title || (s.url && host(s.url))}</span>
                        <br />
                        {s.url && <a className="url" href={s.url} target="_blank" rel="noreferrer noopener">{s.url}</a>}
                      </span>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </>
        ) : (
          <p className="oneline pend">Searching the literature<span className="cursor" /></p>
        )}
      </Section>

      {/* 2 HYPOTHESIS */}
      <Section no={NO("hypothesis")} id="hypothesis" title="Hypothesis" status={statusOf("hypothesis")}
        badge={badgeFor("hypothesis", !!gateFor("hypothesis"))} stat={stat("hypothesis")}>
        {gateFor("hypothesis") ? (
          <GateCard key={gate!.id} gate={gate!} records={records} routing={p.routing} health={p.health} onDecided={p.onDecided} />
        ) : st.hypothesis ? (
          <>
            <p className="oneline">
              <ClaimText claim={p.claims.hypothesis} active={p.activeClaim} onSelect={p.onSelect}>{st.hypothesis}</ClaimText>
            </p>
            <Toggle open={openKey === "hyp"} onClick={() => flip("hyp")}>{openKey === "hyp" ? "Hide" : "Prediction and your part"}</Toggle>
            {openKey === "hyp" && (
              <div className="detail">
                {st.prediction && <p><span className="sc">Prediction</span>{st.prediction}</p>}
                {st.rationale && <p><span className="sc">Why</span>{st.rationale}</p>}
                {decisionsFor("hypothesis").map((d) => (
                  <p key={d.id}><span className="sc">You</span>{decisionLine(d)}</p>
                ))}
              </div>
            )}
          </>
        ) : statusOf("hypothesis") === "current" ? (
          <p className="oneline pend">{st.human_notes.length ? "Rewriting with your input…" : "Drafting a hypothesis…"}</p>
        ) : (
          <p className="oneline pend">A testable claim, drafted from what it found.</p>
        )}
      </Section>

      {/* 3 EXPERIMENT */}
      <Section no={NO("experiment_design")} id="experiment_design" title="Experiment" status={statusOf("experiment_design")}
        badge={badgeFor("experiment_design", !!gateFor("experiment_design"))} stat={stat("experiment_design")}>
        {gateFor("experiment_design") ? (
          <GateCard key={gate!.id} gate={gate!} records={records} routing={p.routing} health={p.health} onDecided={p.onDecided} />
        ) : st.code ? (
          <>
            <p className="oneline">
              <ClaimText claim={p.claims.code} active={p.activeClaim} onSelect={p.onSelect}>
                {codeLines}-line script{st.repaired ? ", repaired after a failed run" : ""}
              </ClaimText>
              {contract
                ? <span className="aside-tag">pre-registered · <span className="mono">{st.contract_hash}</span></span>
                : st.contract_error !== undefined && <span className="aside-tag bad">not pre-registered</span>}
            </p>
            {critic?.approved_over && (
              <p className="flag" role="note">You ran this over the critic&rsquo;s {critic.approved_over}.</p>
            )}
            <div className="toggles">
              {st.contract_error !== undefined && (
                <Toggle open={openKey === "prereg"} onClick={() => flip("prereg")}>
                  {openKey === "prereg" ? "Hide" : "Pre-registration and critic"}
                </Toggle>
              )}
              <Toggle open={openKey === "code"} onClick={() => flip("code")}>{openKey === "code" ? "Hide code" : "Show code"}</Toggle>
            </div>
            {openKey === "prereg" && (
              <div className="detail">
                <PreReg contract={contract} hash={st.contract_hash} error={st.contract_error} />
                {critic && <CriticNote critique={critic} />}
              </div>
            )}
            {openKey === "code" && <div className="detail"><CodeBlock code={st.code} label="Experiment code" /></div>}
          </>
        ) : statusOf("experiment_design") === "current" ? (
          <p className="oneline pend">Writing the experiment…</p>
        ) : (
          <p className="oneline pend">Code for you to read before anything runs.</p>
        )}
      </Section>

      {/* 4 EXECUTION */}
      <Section no={NO("execution")} id="execution" title="Execution" status={statusOf("execution")}
        badge={badgeFor("execution", false)} stat={stat("execution")}>
        {sandboxRuns.length > 0 ? (
          <>
            <p className="oneline">
              {working("execution") ? "Running in the sandbox…" : st.exit_code === 0 ? "Finished cleanly." : `Exited with code ${st.exit_code}.`}
              {st.backend && <span className="mono" style={{ fontSize: 13, marginLeft: 10, color: "var(--muted)" }}>{st.backend}</span>}
            </p>
            {(st.stdout || st.stderr) && (
              <>
                <Toggle open={openKey === "out"} onClick={() => flip("out")}>{openKey === "out" ? "Hide output" : "Output"}</Toggle>
                {openKey === "out" && (
                  <div className="detail">
                    {st.stdout && <pre className="runlog">{st.stdout}</pre>}
                    {st.stderr && <pre className="runlog err" style={{ marginTop: 12 }}>{st.stderr}</pre>}
                  </div>
                )}
              </>
            )}
            <ol className="runs" aria-label="Sandbox runs">
              {sandboxRuns.map((r, i) => {
                const ok = r.outputs.exit_code === 0;
                const arm = armOf(r);
                return (
                  <li key={r.id} className={ok ? "ok" : "bad"}>
                    <span className="mark"><i aria-hidden="true" />{arm ? ARM_LABEL[arm] : `Run ${i + 1}`}</span>
                    <span>{ok ? "finished" : `exit ${String(r.outputs.exit_code)}`} · {seconds(r.latency_s)}</span>
                  </li>
                );
              })}
            </ol>
          </>
        ) : working("execution") ? (
          <p className="oneline pend">Starting the sandbox<span className="cursor" /></p>
        ) : (
          <p className="oneline pend">Runs only after you approve the code.</p>
        )}
      </Section>

      {/* 5 ANALYSIS */}
      <Section no={NO("analysis")} id="analysis" title="Analysis" status={statusOf("analysis")}
        badge={badgeFor("analysis", false)} stat={stat("analysis")}>
        {st.verdict ? (
          <>
            <p className="verdict-row">
              <span className={`verdict ${st.verdict}`}>{st.verdict}</span>
              {checks.length > 0 && <span className="by-rule">by rule, from the pre-registration</span>}
            </p>
            {critic?.approved_over && !unusable && (
              <p className="flag" role="note">
                The design critic called this run {critic.approved_over}: {critic.summary || "the outcome may be fixed by the parameters."}{" "}
                Read this verdict with that in mind.
              </p>
            )}
            {reasons.length > 0 && (
              <ul className="reasons">{reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
            )}
            {st.findings && (
              <p className="oneline" style={{ marginTop: 12 }}>
                <ClaimText claim={p.claims.verdict} active={p.activeClaim} onSelect={p.onSelect}>{st.findings}</ClaimText>
              </p>
            )}
            <div className="toggles">
              {checks.length > 0 && (
                <Toggle open={openKey === "chk"} onClick={() => flip("chk")}>
                  {openKey === "chk" ? "Hide checks" : `Checks · ${checks.filter((c) => c.passed).length} of ${checks.length} passed`}
                </Toggle>
              )}
              {st.caveats.length > 0 && (
                <Toggle open={openKey === "cav"} onClick={() => flip("cav")}>{openKey === "cav" ? "Hide" : "Caveats"}</Toggle>
              )}
            </div>
            {openKey === "chk" && <div className="detail"><Checks checks={checks} /></div>}
            {openKey === "cav" && (
              <ul className="caveats">{st.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>
            )}
          </>
        ) : (
          <p className="oneline pend">{working("analysis") ? "Reading the result…" : "A verdict, no stronger than the run allows."}</p>
        )}
      </Section>

      {/* 6 REFLECTION */}
      <Section no={NO("reflection")} id="reflection" title="Reflection" status={statusOf("reflection")}
        badge={badgeFor("reflection", !!gateFor("strategy_update"))} stat={stat("reflection")}>
        {gateFor("strategy_update") ? (
          <GateCard key={gate!.id} gate={gate!} records={records} routing={p.routing} health={p.health} onDecided={p.onDecided} />
        ) : st.change_summary ? (
          <>
            <p className="oneline">
              <ClaimText claim={p.claims.lessons} active={p.activeClaim} onSelect={p.onSelect}>{st.change_summary}</ClaimText>
            </p>
            <Toggle open={openKey === "ref"} onClick={() => flip("ref")}>{openKey === "ref" ? "Hide" : "What worked, what didn't"}</Toggle>
            {openKey === "ref" && (
              <div className="detail">
                {st.what_worked && <p><span className="sc">{unusable ? "Worked, in the process" : "Worked"}</span>{st.what_worked}</p>}
                {st.what_failed && <p><span className="sc">Didn&rsquo;t</span>{st.what_failed}</p>}
              </div>
            )}
          </>
        ) : (
          <p className="oneline pend">{working("reflection") ? "Deciding what to change next time…" : "Lessons that shape the next run."}</p>
        )}
      </Section>

      {/* 7 NOTEBOOK */}
      <Section no={NO("notebook")} id="notebook-stage" title="Notebook" status={statusOf("notebook")}
        badge={badgeFor("notebook", false)}>
        {project.notebook_path ? (
          <>
            <p className="oneline">The record is ready.</p>
            <button type="button" className="btn primary" style={{ marginTop: 20 }} onClick={() => p.openChapter("notebook")}>
              Open notebook
            </button>
          </>
        ) : (
          <p className="oneline pend">Assembled when the run finishes.</p>
        )}
      </Section>
    </>
  );
}
