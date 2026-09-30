// Shapes returned by the Palissy FastAPI backend (palissy/api.py, palissy/db.py).

export type ProjectStatus = "running" | "done" | "failed" | "interrupted";

export type StageKey =
  | "literature"
  | "hypothesis"
  | "experiment_design"
  | "execution"
  | "analysis"
  | "reflection"
  | "notebook";

export type GateStage = "hypothesis" | "experiment_design" | "strategy_update";
export type GateAction = "approve" | "reject" | "modify" | "inject";
export type Verdict = "supports" | "refutes" | "inconclusive" | "failed";

export interface Source {
  title?: string;
  url?: string;
  content?: string;
}

/** Snapshot of the current cycle, saved by the pipeline after every stage. */
export interface CycleState {
  question: string;
  stage: StageKey | "done";
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
  hypothesis_record_id: string;
  code: string;
  code_record_id: string;
  backend: string;
  stdout: string;
  stderr: string;
  exit_code: number;
  exec_record_id: string;
  repaired: boolean;
  verdict: Verdict | "";
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
  proposal: Record<string, string>;
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
  kind: "model" | "search" | "extract" | "sandbox" | "decision";
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
