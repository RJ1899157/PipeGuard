export type Job = {
  id: string;
  name: string;
  namespace: string;
  integration_id: string;
  kind: string;
};
export type Run = {
  id: string;
  job_id: string;
  external_run_id: string;
  state: string;
  reconciliation_required: boolean;
  started_at: string | null;
  finished_at: string | null;
};
export type Attempt = {
  id: string;
  run_id: string;
  attempt_number: number;
  attempt_key: string;
  state: string;
  projection_source: string;
  error_code: string | null;
  reconciliation_required: boolean;
  started_at: string | null;
  finished_at: string | null;
};
export type Page<T> = {
  items: T[];
  has_more: boolean;
  limit: number;
  offset: number;
};
export type Incident = {
  id: string;
  job_id: string;
  condition: string;
  subject: string;
  severity: string;
  state: string;
  created_at: string;
  last_evaluated_at: string;
};
export type History = {
  id: string;
  action: string;
  evidence_key: string;
  evidence: Record<string, unknown>;
  actor: string;
  occurred_at: string;
  created_at: string;
};
export type Evidence = {
  event_id: string;
  payload_hash: string;
  basis: string;
  event_type: string;
  occurred_at: string;
  received_at: string;
};
export type GraphNode = {
  id: string;
  kind: "dataset" | "step";
  name: string;
  namespace: string;
  attempt_number?: number;
  external_run_id?: string;
  openlineage_run_id?: string;
};
export type Graph = {
  nodes: GraphNode[];
  edges: { source: string; target: string; evidence: Evidence[] }[];
  coverage: string;
  missing_metadata: string[];
  truncated: boolean;
  event_count: number;
  semantics: string;
  as_of: string;
  known_at: string;
};
export type Coverage = {
  detector: string;
  last_completed_at: string | null;
  jobs: {
    job_id: string;
    mode: string;
    lineage_expected: boolean;
    quality_expected: boolean;
    activity_interval_seconds: number | null;
    detector_status: string;
  }[];
  unmonitored_job_ids: string[];
  notice: string;
};
