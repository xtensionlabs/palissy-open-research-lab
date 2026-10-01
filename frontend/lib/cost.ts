import { stageLabel } from "./format";
import type { ProvRecord, Routing } from "./types";

export type Flavor = "nano" | "super" | "ultra";

/** USD per 1M tokens (in, out) for each model tier, read from the server's routing table. */
export function flavorPrices(routing: Routing | null): Record<Flavor, [number, number]> | null {
  if (!routing) return null;
  const out: Partial<Record<Flavor, [number, number]>> = {};
  for (const s of routing.stages) out[s.flavor] ??= [s.price_in, s.price_out];
  return out.nano && out.super && out.ultra ? (out as Record<Flavor, [number, number]>) : null;
}

export const callCost = (tokensIn: number, tokensOut: number, price: [number, number]) =>
  (tokensIn * price[0] + tokensOut * price[1]) / 1_000_000;

export function tierOf(model: string | null): Flavor | null {
  const m = (model ?? "").toLowerCase();
  return m.includes("ultra") ? "ultra" : m.includes("super") ? "super" : m.includes("nano") ? "nano" : null;
}

/** What one model call would have cost on each tier, given its real token counts. */
export function alternatives(rec: ProvRecord | undefined, routing: Routing | null) {
  const prices = flavorPrices(routing);
  if (!rec || !prices) return null;
  const used = tierOf(rec.model);
  return {
    used,
    costs: (["nano", "super", "ultra"] as Flavor[]).map((f) => ({
      flavor: f,
      cost: callCost(rec.tokens_in, rec.tokens_out, prices[f]),
    })),
  };
}

export interface Breakdown {
  key: string;
  label: string;
  calls: number;
  tokensIn: number;
  tokensOut: number;
  cost: number;
}

function group(records: ProvRecord[], keyOf: (r: ProvRecord) => string, labelOf: (k: string) => string) {
  const map = new Map<string, Breakdown>();
  for (const r of records) {
    if (r.kind !== "model") continue;
    const key = keyOf(r);
    const row = map.get(key) ?? { key, label: labelOf(key), calls: 0, tokensIn: 0, tokensOut: 0, cost: 0 };
    row.calls += 1;
    row.tokensIn += r.tokens_in;
    row.tokensOut += r.tokens_out;
    row.cost += r.cost_usd;
    map.set(key, row);
  }
  return [...map.values()];
}

export const byModel = (records: ProvRecord[]) =>
  group(records, (r) => tierOf(r.model) ?? "other", (k) => (k === "other" ? "Other" : k[0].toUpperCase() + k.slice(1)))
    .sort((a, b) => b.cost - a.cost);

const STAGE_ORDER = [
  "triage", "literature_summary", "hypothesis", "experiment_design", "design_critic",
  "design_critic_escalated", "code_generation", "analysis", "reflection",
];
export const byStage = (records: ProvRecord[]) =>
  group(records, (r) => r.stage, stageLabel)
    .sort((a, b) => STAGE_ORDER.indexOf(a.key) - STAGE_ORDER.indexOf(b.key));
