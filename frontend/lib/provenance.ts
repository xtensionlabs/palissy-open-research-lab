import { host, modelName, seconds, stageLabel, usd } from "./format";
import type { CycleState, ProvRecord } from "./types";

/** Something on the page a reader can click to see where it came from. */
export interface Claim {
  key: string;
  kind: "hypothesis" | "citation" | "code" | "verdict" | "lessons";
  text: string;
  recordId: string;
  /** 1-based index of the cited source, for citations */
  sourceIndex?: number;
}

export type ChainKind = "claim" | "human" | "model" | "search" | "sandbox" | "source" | "rule";

export interface ChainItem {
  key: string;
  kind: ChainKind;
  title: string;
  lines: string[];
  quote?: string;
  recordId?: string;
}

function describe(r: ProvRecord): ChainItem {
  if (r.kind === "decision") {
    const action = String(r.outputs.action ?? "");
    const payload = (r.outputs.payload as string | null) ?? undefined;
    const title =
      action === "approve"
        ? "You approved"
        : action === "inject"
          ? "You added knowledge"
          : action === "reject"
            ? "You rejected it"
            : "You edited it";
    return {
      key: r.id,
      kind: "human",
      title,
      lines: [stageLabel(r.stage)],
      quote: payload,
      recordId: r.id,
    };
  }
  if (r.kind === "search" || r.kind === "extract") {
    return {
      key: r.id,
      kind: "search",
      title: "Web search",
      lines: [`${r.sources.length} sources · ${seconds(r.latency_s)}`],
      recordId: r.id,
    };
  }
  if (r.kind === "rule" && r.stage === "replay") {
    return {
      key: r.id,
      kind: "rule",
      title: `Replayed ${String(r.outputs.total ?? "")} runs: ${String(r.outputs.matched ?? "")} matched`,
      lines: ["Each run started again from the clean base image"],
      recordId: r.id,
    };
  }
  if (r.kind === "rule") {
    const verdict = r.outputs.verdict as string | undefined;
    return {
      key: r.id,
      kind: "rule",
      title: verdict ? `Verdict by rule: ${verdict}` : "Pre-registration frozen",
      lines: verdict
        ? ["From the pre-registration and controls, not a model"]
        : [`hash ${String(r.outputs.contract_hash ?? "")}`],
      recordId: r.id,
    };
  }
  if (r.kind === "sandbox" && r.stage === "checkpoint") {
    return {
      key: r.id,
      kind: "sandbox",
      title: "Sandbox checkpoint",
      lines: [`image ${String(r.outputs.image ?? "").slice(0, 8) || "none"} · every run forks from it`],
      recordId: r.id,
    };
  }
  if (r.kind === "sandbox") {
    const code = r.outputs.exit_code as number | undefined;
    const armName = (r.inputs.args as string[] | undefined)?.[0];
    const rep = r.inputs.rep as number | undefined;
    const arm = armName && rep !== undefined ? `${armName} #${rep + 1}` : armName;
    return {
      key: r.id,
      kind: "sandbox",
      title: `${code === 0 ? "Ran in sandbox" : "Sandbox run failed"}${arm ? ` · ${arm}` : ""}`,
      lines: [`exit ${code ?? "?"} · ${seconds(r.latency_s)}`],
      recordId: r.id,
    };
  }
  const { short } = modelName(r.model);
  return {
    key: r.id,
    kind: "model",
    title: `${short}`,
    lines: [
      stageLabel(r.stage),
      `${r.tokens_in.toLocaleString()} in · ${r.tokens_out.toLocaleString()} out`,
      `${usd(r.cost_usd, 5)} · ${seconds(r.latency_s)}`,
    ],
    recordId: r.id,
  };
}

/**
 * Walk a record's ancestors through `parents`, add the human decisions that shaped each model
 * step, and return them newest first (claim at the top, sources at the bottom).
 */
export function buildChain(records: ProvRecord[], claim: Claim): ChainItem[] {
  const byId = new Map(records.map((r) => [r.id, r]));
  const start = byId.get(claim.recordId);
  if (!start) return [];

  const path = new Map<string, ProvRecord>();
  const visit = (r: ProvRecord) => {
    if (path.has(r.id)) return;
    path.set(r.id, r);
    r.parents.forEach((p) => {
      const parent = byId.get(p);
      if (parent) visit(parent);
    });
  };
  visit(start);

  // Decisions that acted on a step on the path: direct children, plus earlier answers at the same
  // stage (an "inject" or "reject" is why a later proposal exists).
  const decisions = records.filter(
    (d) =>
      d.kind === "decision" &&
      [...path.values()].some(
        (r) => r.kind === "model" && (d.parents.includes(r.id) || (d.stage === r.stage && d.ts < r.ts)),
      ),
  );
  decisions.forEach((d) => path.set(d.id, d));

  const ordered = [...path.values()].sort((a, b) => b.ts - a.ts).map(describe);

  if (claim.kind === "citation" && claim.sourceIndex) {
    const search = [...path.values()].find((r) => r.kind === "search");
    const url = search?.sources[claim.sourceIndex - 1];
    const results = (search?.outputs.results as { title?: string; url?: string }[] | undefined) ?? [];
    const hit = results.find((r) => r.url === url);
    if (url) {
      ordered.unshift({
        key: `source-${claim.sourceIndex}`,
        kind: "source",
        title: hit?.title || host(url),
        lines: [host(url)],
      });
    }
  }
  return ordered;
}

/** The claims a reader can click, derived from the saved state and records. */
export function claimsFrom(state: CycleState | null | undefined, records: ProvRecord[]) {
  const reflection = [...records].reverse().find((r) => r.stage === "reflection" && r.kind === "model");
  return {
    hypothesis: state?.hypothesis_record_id
      ? ({ key: "hypothesis", kind: "hypothesis", text: state.hypothesis, recordId: state.hypothesis_record_id } as Claim)
      : null,
    code: state?.code_record_id
      ? ({ key: "code", kind: "code", text: "Experiment code", recordId: state.code_record_id } as Claim)
      : null,
    verdict: state?.analysis_record_id
      ? ({ key: "verdict", kind: "verdict", text: state.findings, recordId: state.analysis_record_id } as Claim)
      : null,
    lessons: reflection
      ? ({ key: "lessons", kind: "lessons", text: state?.change_summary ?? "Strategy", recordId: reflection.id } as Claim)
      : null,
    citation: (index: number): Claim | null =>
      state?.lit_record_id
        ? {
            key: `cite-${index}`,
            kind: "citation",
            text: state.literature[index - 1]?.title ?? `Source ${index}`,
            recordId: state.lit_record_id,
            sourceIndex: index,
          }
        : null,
  };
}
