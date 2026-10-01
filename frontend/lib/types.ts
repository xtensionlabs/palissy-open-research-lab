// Shapes returned by the Palissy FastAPI backend (palissy/api.py, palissy/db.py).

export type ProjectStatus = "running" | "done" | "failed" | "interrupted";

export type StageKey =
  | "triage"
  | "literature"
  | "hypothesis"
  | "experiment_design"
  | "execution"
  | "analysis"
  | "reflection"
  | "notebook";

export type GateStage = "triage" | "hypothesis" | "experiment_design" | "strategy_update";
export type GateAction = "approve" | "reject" | "modify" | "inject";
export type Verdict = "supports" | "refutes" | "inconclusive" | "failed";

export interface Source {
  title?: string;
  url?: string;
  content?: string;
}

export type TriageCategory = "testable" | "fiction" | "needs_wet_lab" | "not_empirical";

export interface Triage {
  category: TriageCategory;
  label: string;
  reason: string;
  reframe: string;
  question: string;
  record_id: string;
  decision?: "continued" | "reframed";
}

/** The pre-registration committed before anything runs (palissy/stages/verdict.py). */
export interface Contract {
  statistic: string;
  test: string;
  null: string;
  alpha: number;
  direction: "increase" | "decrease" | "any";
  supports_if: string;
  refutes_if: string;
  positive_control: string;
  negative_control: string;
}

export type CriticLevel = "ok" | "concern" | "blocking";

export interface Critique {
  level: CriticLevel;
  answers: Record<string, { ok: boolean; why: string }>;
  summary: string;
  checked_by: string[];
  record_ids: string[];
  edited_after?: boolean;
  approved_over?: "" | "concern" | "blocking";
}

export type Arm = "treatment" | "positive" | "negative";

export interface ArmResult {
  effect?: number;
  p_value?: number;
  n?: number;
  successes?: number | null;
}

export interface ArmRun {
  stdout: string;
  stderr: string;
  exit_code: number;
  duration_s: number;
  backend: string;
  result: ArmResult | null;
  record_id: string;
}

export interface Check {
  name: string;
  passed: boolean;
  detail: string;
}

/** Snapshot of the current cycle, saved by the pipeline after every stage. */
export interface CycleState {
  question: string;
  stage: StageKey | "done";
  original_question?: string;
  triage?: Triage | Record<string, never>;
  data_source: string;
  lessons_before: string[];
  lessons_after: string[];
  human_notes: string[];
  literature: Source[];
  literature_summary: string;
  lit_record_id: string;
  hypothesis: string;
  prediction: string;
  rationale: string;
  hypothesis_warning?: string;
  hypothesis_record_id: string;
  code: string;
  code_record_id: string;
  contract?: Contract | Record<string, never>;
  contract_error?: string;
  contract_hash?: string;
  code_hash?: string;
  critique?: Critique | Record<string, never>;
  arms?: Partial<Record<Arm, ArmRun>>;
  backend: string;
  stdout: string;
  stderr: string;
  exit_code: number;
  exec_record_id: string;
  repaired: boolean;
  verdict: Verdict | "";
  verdict_reasons?: string[];
  checks?: Check[];
  verdict_record_id?: string;
  findings: string;
  caveats: string[];
  analysis_record_id: string;
  what_worked: string;
  what_failed: string;
  change_summary: string;
  notebook_path: string;
}

export interface Gate {
  id: string;
  project_id: string;
  cycle: number;
  stage: GateStage;
  title: string;
  proposal: Record<string, unknown>;
  status: string;
  created_at: number;
}

export interface Project {
  id: string;
  question: string;
  status: ProjectStatus;
  created_at: number;
  notebook_path: string | null;
  error: string | null;
  cost_usd: number;
  pending_gate: Gate | null;
  state?: CycleState | null;
}

export interface ProvRecord {
  id: string;
  kind: "model" | "search" | "extract" | "sandbox" | "decision" | "rule";
  stage: string;
  summary: string;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  model: string | null;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_s: number;
  sources: string[];
  parents: string[];
  ts: number;
}

export interface Decision {
  id: string;
  stage: GateStage;
  action: GateAction;
  payload: string | null;
  ts: number;
}

export interface RoutingStage {
  stage: string;
  flavor: "nano" | "super" | "ultra";
  reason: string;
  price_in: number;
  price_out: number;
}

export interface Routing {
  stages: RoutingStage[];
  unit: string;
}

export interface Costs {
  total_usd: number;
  by_model: {
    model: string;
    kind: string;
    calls: number;
    tokens_in: number | null;
    tokens_out: number | null;
    cost_usd: number | null;
    latency_s: number | null;
  }[];
  projects: { id: string; question: string; status: ProjectStatus; cost_usd: number }[];
}

export interface Notebook {
  cells: { cell_type: "markdown" | "code"; source: string[]; outputs?: { text?: string[] }[] }[];
}

export interface Health {
  ok: boolean;
  running: number;
  executor: string;
  image: string | null;
  timeout_s: number;
  local_fallback: boolean;
}
