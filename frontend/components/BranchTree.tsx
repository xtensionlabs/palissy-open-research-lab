"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { effectFmt, pFmt, seconds } from "@/lib/format";
import type { Arm, Branch, Contract, CycleState, Replay } from "@/lib/types";
import { hasContract } from "./PreReg";

const ARMS: { arm: Arm; label: string }[] = [
  { arm: "treatment", label: "Treatment" },
  { arm: "positive", label: "Positive control" },
  { arm: "negative", label: "Negative control" },
];

/** What a filled dot means for each arm, in words. */
function summary(arm: Arm, hits: number, ok: number, contract: Contract | null): string {
  if (arm === "treatment") {
    const size = contract && contract.min_effect > 0 ? ` and at least ${contract.min_effect}` : "";
    return `${hits} of ${ok} significant${size}`;
  }
  return arm === "positive" ? `${hits} of ${ok} detected` : `${hits} of ${ok} false alarms`;
}

function dotTitle(b: Branch): string {
  if (b.status === "rolled_back") return `${b.id} · rolled back (${b.reason})`;
  const r = b.result;
  return `${b.id} · seed +${b.seed_offset} · effect ${effectFmt(r?.effect)} · p ${pFmt(r?.p_value)} · ${seconds(b.duration_s)}`;
}

/**
 * The run as it really happened: one checkpoint, and every (arm, seed) branch forked from it.
 * Dots are real branches from the project state; nothing here is decorative.
 */
export function BranchTree({
  projectId, state, running, onReplayed,
}: {
  projectId: string;
  state: CycleState;
  running: boolean;
  onReplayed: () => void;
}) {
  const branches = state.branches ?? [];
  const contract = hasContract(state.contract) ? state.contract : null;
  const ck = state.checkpoint && "base" in state.checkpoint ? state.checkpoint : null;
  const local = state.backend === "local-fallback";
  const [open, setOpen] = useState(false);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.replay(projectId).then((r) => !cancelled && setReplay(r)).catch(() => undefined);
    return () => { cancelled = true; };
  }, [projectId]);

  if (branches.length === 0) return null;
  const rolled = branches.filter((b) => b.status === "rolled_back").length;
  const done = !running;

  async function runReplay() {
    setBusy(true);
    setError(null);
    try {
      setReplay(await api.runReplay(projectId));
      onReplayed();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The replay didn't run.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="branches">
      <p className="tree-root">
        <span className="sc">{local ? "No snapshot" : "Checkpoint"}</span>
        {ck?.image && <b>{ck.image.slice(0, 8)}</b>}
        <span>
          {local
            ? "ran on the local fallback, not in a sandbox"
            : `script attached once, then ${branches.length} branches forked from it`}
        </span>
      </p>

      <ul className="tree-arms" aria-label="Sandbox branches by arm">
        {ARMS.map(({ arm, label }) => {
          const mine = branches.filter((b) => b.arm === arm);
          const t = state.tally?.[arm];
          if (mine.length === 0) return null;
          return (
            <li key={arm}>
              <span className="arm-name">{label}</span>
              <span className="dots" role="list">
                {mine.map((b) => (
                  <i
                    key={b.id}
                    role="listitem"
                    title={dotTitle(b)}
                    aria-label={dotTitle(b)}
                    className={b.status === "rolled_back" ? "bad" : b.hit ? "hit" : ""}
                  />
                ))}
              </span>
              <span className="arm-sum">
                {t && t.ok > 0 ? (
                  <>
                    {summary(arm, t.hits, t.ok, contract)}
                    <span className="mono"> · median {effectFmt(t.median_effect)}</span>
                  </>
                ) : (
                  `${mine.length} run${mine.length > 1 ? "s" : ""}`
                )}
              </span>
            </li>
          );
        })}
      </ul>

      <p className="tree-key">
        <span className="k hit" />filled: counted
        <span className="k" />hollow: ran, didn&rsquo;t count
        {rolled > 0 && <><span className="k bad" />square: rolled back, left out ({rolled})</>}
      </p>

      <div className="toggles">
        <button type="button" className="toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
          <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M3 1l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" /></svg>
          {open ? "Hide the runs" : `All ${branches.length} runs`}
        </button>
      </div>
      {open && (
        <div className="detail scroll-x">
          <table className="ledger runs-table">
            <thead>
              <tr><th>Run</th><th className="r">Seed</th><th className="r">Effect</th><th className="r">p</th><th className="r">Time</th><th>Result</th></tr>
            </thead>
            <tbody>
              {branches.map((b) => (
                <tr key={b.id} className={b.status === "rolled_back" ? "rb" : undefined}>
                  <td>{b.id}</td>
                  <td className="r">+{b.seed_offset}</td>
                  <td className="r">{effectFmt(b.result?.effect)}</td>
                  <td className="r">{pFmt(b.result?.p_value)}</td>
                  <td className="r">{seconds(b.duration_s)}</td>
                  <td>{b.status === "rolled_back" ? `rolled back (${b.reason})` : b.hit ? "counted" : "ran"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {done && (
        <div className="replay">
          <div className="replay-row">
            <button type="button" className="btn" disabled={busy} onClick={runReplay}>
              {busy ? "Replaying…" : replay ? "Replay again" : `Replay all ${branches.length} runs`}
            </button>
            {busy && (
              <span className="replay-note" role="status">
                <i aria-hidden="true" />Starting each run again in a clean {local ? "process" : "sandbox"}. About {Math.max(20, Math.round(branches.length * 3.5))} s.
              </span>
            )}
          </div>
          {!busy && !replay && !error && (
            <p className="replay-help">
              {local
                ? "Re-runs each branch on this machine and compares the output. This backend isn't isolated."
                : "Starts every run again from the base image with the stored script and seeds, then compares the output byte for byte."}
            </p>
          )}
          {error && <p className="form-error" role="alert">{error}</p>}
          {replay && !busy && (
            <div className={`replay-result ${replay.matched === replay.total ? "ok" : "bad"}`} role="status">
              <b>
                {replay.matched === replay.total
                  ? `${replay.total} of ${replay.total} runs reproduced`
                  : `${replay.matched} of ${replay.total} runs reproduced`}
              </b>
              <span>
                {replay.duration_s} s on {replay.backend === "local-fallback" ? "this machine" : replay.backend}
                {replay.base && <> from <span className="mono">{replay.base.replace(/^tag:/, "")}</span></>}
              </span>
              {replay.matched !== replay.total && (
                <span className="differs">
                  Different output: {replay.items.filter((i) => !i.match).map((i) => i.id).join(", ")}
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
