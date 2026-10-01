import type { StageKey } from "./types";

export const STAGES: { key: StageKey; label: string }[] = [
  { key: "triage", label: "Question" },
  { key: "literature", label: "Literature" },
  { key: "hypothesis", label: "Hypothesis" },
  { key: "experiment_design", label: "Experiment" },
  { key: "execution", label: "Execution" },
  { key: "analysis", label: "Analysis" },
  { key: "reflection", label: "Reflection" },
  { key: "notebook", label: "Notebook" },
];

export const usd = (n: number | null | undefined, digits = 4) =>
  `$${(n ?? 0).toFixed(digits)}`;

export const seconds = (n: number) => `${n < 10 ? n.toFixed(1) : Math.round(n)} s`;

export function clock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/** "nvidia/Nemotron-3-Ultra-550b-a55b" -> { tier: "Ultra", short: "Nemotron 3 Ultra" } */
export function modelName(model: string | null | undefined): { tier: string; short: string } {
  const m = (model ?? "").toLowerCase();
  const tier = m.includes("ultra") ? "Ultra" : m.includes("super") ? "Super" : m.includes("nano") ? "Nano" : "";
  return { tier, short: tier ? `Nemotron 3 ${tier}` : model ?? "" };
}

export function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

const EXTRA_LABELS: Record<string, string> = {
  literature_summary: "Literature",
  code_generation: "Code repair",
  design_critic: "Design critic",
  design_critic_escalated: "Critic, second look",
  strategy_update: "Reflection",
};

export const stageLabel = (stage: string) =>
  EXTRA_LABELS[stage] ?? STAGES.find((s) => s.key === stage)?.label ?? stage.replace(/_/g, " ");
