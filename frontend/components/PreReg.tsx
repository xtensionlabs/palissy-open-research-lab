"use client";

import type { Check, Contract, Critique } from "@/lib/types";

const ROWS: [keyof Contract, string][] = [
  ["statistic", "Measures"],
  ["test", "Test"],
  ["null", "Null"],
  ["supports_if", "Supports if"],
  ["refutes_if", "Refutes if"],
  ["positive_control", "Positive control"],
  ["negative_control", "Negative control"],
];

const QUESTIONS: Record<string, string> = {
  knowable_in_advance: "Outcome not known in advance",
  null_is_real: "The null is a real null",
  test_matches_claim: "The test does what it says",
};

const LEVEL = { ok: "No flaw found", concern: "Concern", blocking: "Blocking" } as const;

const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

export const hasContract = (c: unknown): c is Contract =>
  !!c && typeof c === "object" && "statistic" in c;

export const hasCritique = (c: unknown): c is Critique =>
  !!c && typeof c === "object" && "level" in c;

/** The commitment made before anything runs. The verdict is computed from it, by rule. */
export function PreReg({ contract, hash, error }: { contract: Contract | null; hash?: string; error?: string }) {
  if (!contract) {
    return (
      <div className="prereg missing">
        <span className="sc">Pre-registration</span>
        <p>None was committed{error ? ` (${error})` : ""}. Any result will be inconclusive.</p>
      </div>
    );
  }
  return (
    <div className="prereg">
      <div className="prereg-head">
        <span className="sc">Pre-registration</span>
        <span className="stamp">{hash ? <>Frozen <span className="mono">{hash}</span></> : "Frozen when you approve"}</span>
      </div>
      <p className="prereg-line">
        Predicts <b>{{ any: "an effect", increase: "an increase", decrease: "a decrease" }[contract.direction]}</b>
        {" · "}significant below <b className="mono">p {contract.alpha}</b>
      </p>
      <dl>
        {ROWS.map(([k, label]) => (
          <div key={k}>
            <dt>{label}</dt>
            <dd>{String(contract[k])}</dd>
          </div>
        ))}
      </dl>
      <p className="prereg-foot">The verdict is worked out from this and both controls, not by a model.</p>
    </div>
  );
}

/** What the design critic found. Passed questions stay one line; failed ones say why. */
export function CriticNote({ critique }: { critique: Critique }) {
  return (
    <div className={`critic ${critique.level}`}>
      <div className="critic-head">
        <span className="sc">Critic</span>
        <span className={`lvl ${critique.level}`}>{LEVEL[critique.level]}</span>
        <span className="by">{critique.checked_by.map(cap).join(" → ")}</span>
      </div>
      <ul>
        {Object.entries(critique.answers).map(([k, a]) => (
          <li key={k} className={a.ok ? "ok" : "bad"}>
            <span className="gl" aria-label={a.ok ? "passed" : "failed"}>{a.ok ? "✓" : "✗"}</span>
            <span>
              <b>{QUESTIONS[k] ?? k}</b>
              {!a.ok && <span className="why">{a.why}</span>}
            </span>
          </li>
        ))}
      </ul>
      {critique.edited_after && <p className="critic-foot">You edited the code after this review.</p>}
    </div>
  );
}

/** The mechanical checks behind a verdict. */
export function Checks({ checks }: { checks: Check[] }) {
  return (
    <ul className="checks">
      {checks.map((c) => (
        <li key={c.name} className={c.passed ? "ok" : "bad"}>
          <span className="gl" aria-label={c.passed ? "passed" : "failed"}>{c.passed ? "✓" : "✗"}</span>
          <span><b>{c.name}</b> <span className="why">{c.detail}</span></span>
        </li>
      ))}
    </ul>
  );
}
