"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { alternatives } from "@/lib/cost";
import { usd } from "@/lib/format";
import type { Gate, GateAction, Health, ProvRecord, Routing } from "@/lib/types";
import { CodeBlock } from "./CodeBlock";
import { CriticNote, PreReg, hasContract, hasCritique } from "./PreReg";

const COPY = {
  triage: { kicker: "Before anything runs", title: "Is this question testable?", approve: "Continue knowingly", noun: "question" },
  hypothesis: { kicker: "Your decision · 1 of 3", title: "Approve this hypothesis?", approve: "Approve", noun: "hypothesis" },
  experiment_design: { kicker: "Your decision · 2 of 3", title: "Run this experiment?", approve: "Approve and run", noun: "code" },
  strategy_update: { kicker: "Your decision · 3 of 3", title: "Keep these lessons?", approve: "Keep lessons", noun: "lessons" },
} as const;

const str = (v: unknown) => (typeof v === "string" ? v : "");

function lessonLines(text: string): string[] {
  return text
    .split("\n")
    .map((l) => l.replace(/^-\s*/, "").trim())
    .filter((l) => l && l !== "(none)");
}

function Proposal({ gate }: { gate: Gate }) {
  const p = gate.proposal;
  const [all, setAll] = useState(false);
  if (gate.stage === "triage") {
    return (
      <>
        <p className="proposal"><b>{str(p.label)}</b> {str(p.reason)}</p>
        {str(p.reframe) && (
          <p className="proposal">
            <span className="sc">Closest question a simulation can test</span>
            {str(p.reframe)}
          </p>
        )}
      </>
    );
  }
  if (gate.stage === "hypothesis") {
    return (
      <>
        <p className="proposal">{str(p.hypothesis)}</p>
        {str(p.prediction) && (
          <p className="proposal">
            <span className="sc">Prediction</span>
            {str(p.prediction)}
          </p>
        )}
        {str(p.warning) && <p className="flag" role="note">{str(p.warning)} Edit it, or reject it with a reason.</p>}
      </>
    );
  }
  if (gate.stage === "experiment_design") {
    const code = str(p["experiment code"]);
    const n = code.trimEnd().split("\n").length;
    return (
      <>
        <PreReg contract={hasContract(p.preregistration) ? p.preregistration : null} error={str(p.preregistration_error)} />
        {hasCritique(p.critic) && <CriticNote critique={p.critic} />}
        <CodeBlock code={code} label="Proposed experiment code" expanded={all} />
        {n > 24 && (
          <button type="button" className="toggle" aria-expanded={all} onClick={() => setAll(!all)}>
            {all ? "Collapse" : `Show all ${n} lines`}
          </button>
        )}
      </>
    );
  }
  const before = lessonLines(str(p["lessons before"]));
  const after = lessonLines(str(p["lessons after"]));
  const kept = after.filter((l) => before.includes(l));
  const added = after.filter((l) => !before.includes(l));
  const removed = before.filter((l) => !after.includes(l));
  return (
    <>
      <ul className="lesson-diff">
        {added.map((l) => (
          <li className="add" key={`a-${l}`}><span className="gl">+</span><span className="tx">{l}</span></li>
        ))}
        {removed.map((l) => (
          <li className="rem" key={`r-${l}`}><span className="gl">−</span><span className="tx">{l}</span></li>
        ))}
      </ul>
      {added.length + removed.length === 0 && <p className="proposal">No change to the lessons.</p>}
      {kept.length > 0 && (
        <>
          <button type="button" className="toggle" aria-expanded={all} onClick={() => setAll(!all)}>
            {all ? "Hide" : `${kept.length} lessons kept`}
          </button>
          {all && (
            <ul className="lesson-diff" style={{ marginTop: 12 }}>
              {kept.map((l) => (
                <li key={`k-${l}`}><span className="gl">·</span><span className="tx">{l}</span></li>
              ))}
            </ul>
          )}
        </>
      )}
    </>
  );
}

function initialModify(gate: Gate): string {
  const p = gate.proposal;
  if (gate.stage === "triage") return str(p.reframe) || str(p.question);
  if (gate.stage === "hypothesis") return str(p.hypothesis);
  if (gate.stage === "experiment_design") return str(p["experiment code"]);
  return lessonLines(str(p["lessons after"])).join("; ");
}

export function GateCard({
  gate,
  records,
  routing,
  health,
  onDecided,
}: {
  gate: Gate;
  records: ProvRecord[];
  routing: Routing | null;
  health: Health | null;
  onDecided: () => void;
}) {
  const copy = COPY[gate.stage];
  const [open, setOpen] = useState<GateAction | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = (action: GateAction) => {
    setError(null);
    setText(action === "modify" ? initialModify(gate) : "");
    setOpen(open === action ? null : action);
  };

  async function submit(action: GateAction, payload?: string) {
    if ((action === "reject" || action === "inject" || action === "modify") && !payload?.trim()) {
      setError(
        action === "reject" ? "Say why, so the next attempt can do better." : "Write something first.",
      );
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.decide(gate.project_id, gate.id, action, payload?.trim());
      setOpen(null);
      onDecided();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't go through.");
    } finally {
      setBusy(false);
    }
  }

  const triage = gate.stage === "triage";
  const reframe = triage ? str(gate.proposal.reframe) : "";
  const lastCode = [...records].reverse().find((r) => r.kind === "model" && r.stage === "experiment_design");
  const alts = gate.stage === "experiment_design" ? alternatives(lastCode, routing) : null;

  return (
    <section className="decision" id="gate" aria-labelledby="gate-title">
      <div className="kicker">
        <span className="sc">{copy.kicker}</span>
      </div>
      <h3 id="gate-title">{copy.title}</h3>
      <p className="waitline">
        <i aria-hidden="true" />
        Waiting for you. Nothing continues until you decide.
      </p>

      <Proposal gate={gate} />

      {gate.stage === "experiment_design" && health && (
        <p className="run-spec">
          <span>Runs in <b>{health.executor}</b></span>
          {health.image && <span><b>{health.image}</b></span>}
          <span>Limit <b>{health.timeout_s} s</b></span>
        </p>
      )}
      {alts && (
        <p className="alt-cost">
          Same step on{" "}
          {alts.costs.map((c, i) => (
            <span key={c.flavor}>
              {i > 0 && " · "}
              <span className={c.flavor === alts.used ? "used" : undefined}>
                {c.flavor[0].toUpperCase() + c.flavor.slice(1)} <b>{usd(c.cost, 5)}</b>
              </span>
            </span>
          ))}
        </p>
      )}

      {triage ? (
        <div className="actions" role="group" aria-label="Decision">
          {reframe && (
            <button className="btn primary" disabled={busy} onClick={() => submit("modify", reframe)}>
              {busy && open === null ? "Sending…" : "Use this question"}
            </button>
          )}
          <button className={reframe ? "btn" : "btn primary"} disabled={busy} onClick={() => submit("approve")}>
            {copy.approve}
          </button>
          <button className="btn" aria-expanded={open === "modify"} onClick={() => toggle("modify")}>Edit question</button>
          <button className="btn" aria-expanded={open === "inject"} onClick={() => toggle("inject")}>Add context</button>
        </div>
      ) : (
        <div className="actions" role="group" aria-label="Decision">
          <button className="btn primary" disabled={busy} onClick={() => submit("approve")}>
            {busy && open === null ? "Sending…" : copy.approve}
          </button>
          <button className="btn" aria-expanded={open === "reject"} onClick={() => toggle("reject")}>Reject</button>
          <button className="btn" aria-expanded={open === "modify"} onClick={() => toggle("modify")}>Modify</button>
          <button className="btn" aria-expanded={open === "inject"} onClick={() => toggle("inject")}>Add knowledge</button>
        </div>
      )}

      {open && (
        <div className="reveal">
          <label htmlFor="gate-text">
            {open === "reject" && "Why reject?"}
            {open === "modify" && (gate.stage === "strategy_update" ? "Lessons, separated by ;" : `Your ${copy.noun}`)}
            {open === "inject" && (triage ? "What should it know about the question?" : "What should it know?")}
          </label>
          <textarea
            id="gate-text"
            className={open === "modify" && gate.stage === "experiment_design" ? "codefield" : undefined}
            value={text}
            onChange={(e) => setText(e.target.value)}
            autoFocus
            spellCheck={open !== "modify" || gate.stage !== "experiment_design"}
          />
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="row">
            <button className="btn primary sm" disabled={busy} onClick={() => submit(open, text)}>
              {busy ? "Sending…" : open === "modify" ? "Use mine" : open === "reject" ? "Reject" : triage ? "Add and check again" : "Add and regenerate"}
            </button>
            <button className="btn ghost sm" onClick={() => setOpen(null)}>Cancel</button>
          </div>
        </div>
      )}
      {!open && error && <p className="form-error" role="alert">{error}</p>}
    </section>
  );
}
