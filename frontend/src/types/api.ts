export type StrategyName = 'no_action' | 'rule_based' | 'ev_greedy' | 'rpa_optimizer';

export interface ActionSpec {
  action_id: string;
  action_type: string;
  action_cost: number;
  resource_requirements: Record<string, number>;
  enabled: boolean;
}

export interface ResourceLimits {
  retry?: number;
  messaging?: number;
  incentive_budget?: number;
  human_slots?: number;
  [key: string]: number | undefined;
}

export interface StrategyMetric {
  total_expected_net_ev: number;
  resource_used: Record<string, number>;
  status: string;
  plan_name?: string;
  n_transactions: number;
  n_planned: number;
  n_executed: number;
  n_successful: number;
  n_failed: number;
  n_blocked: number;
  planned_total_net_ev: number;
  recovered_total: number;
  cost_total: number;
  net_recovered_total: number;
  all_verified: boolean;
  simulation: boolean;
}

export interface BatchSummary {
  batch_id: string;
  status: string;
  n_transactions: number;
  n_actions: number;
  strategy_metrics: Record<string, StrategyMetric>;
  n_blocked_candidates: number;
  error?: string | null;
}

export interface PlanRecord {
  transaction_id: string;
  action_id: string;
  action_type: string;
  net_ev: number;
  name: string;
  version: string;
  status: string;
}

export interface EVTableRow {
  transaction_id: string;
  action_id: string;
  amount: number;
  p_recovery: number;
  recoverable_amount: number;
  gross_expected: number;
  action_cost: number;
  incentive_cost: number;
  total_cost: number;
  net_expected: number;
  is_no_op: boolean;
}

export interface PolicyVerdict {
  transaction_id: string;
  action_id: string;
  action_type: string;
  decision: 'ALLOW' | 'BLOCK';
  policy_id: string;
  rule: string;
  reason: string;
  limit: number | null;
  current_usage: number | null;
}

export interface ExecutionRecord {
  transaction_id: string;
  action_id: string;
  action_type: string;
  plan_name: string;
  status: 'successful' | 'failed' | 'blocked';
  attempted: number;
  recovered_amount: number;
  recovery_cost: number;
  net_recovered_amount: number;
  p_predicted?: number;
  seed?: number;
  simulation: boolean;
}

export interface VerificationRow {
  transaction_id: string;
  planned_action_id: string;
  planned_action_type: string;
  planned_net_ev: number;
  planned_index: number;
  executed: boolean;
  executed_action_id: string;
  executed_status: string;
  successful: boolean;
  failed: boolean;
  blocked: boolean;
  recovered_amount: number;
  recovery_cost: number;
  net_recovered_amount: number;
  verified: boolean;
}

export interface FullBatchResult {
  batch_id: string;
  status: string;
  created_at?: string;
  error?: string | null;
  ev_table?: EVTableRow[];
  verdicts?: PolicyVerdict[];
  plans?: Record<string, PlanRecord[]>;
  executions?: Record<string, ExecutionRecord[]>;
  verifications?: Record<string, { batch_metrics: StrategyMetric; rows: VerificationRow[] }>;
  transaction_ids?: string[];
  resource_limits?: ResourceLimits;
  summary?: BatchSummary;
}

export interface BatchListItem {
  batch_id: string;
  status: string;
  created_at?: string;
  n_transactions: number;
  strategies: string[];
  strategy_summaries?: Record<string, any>;
  has_audit?: boolean;
}

export interface AuditEvent {
  audit_id: string;
  batch_id: string;
  component: 'batch' | 'prediction' | 'ev' | 'policy' | 'optimizer' | 'execution' | 'verification' | string;
  event_type: string;
  entity_id: string;
  event_metadata: Record<string, any>;
  timestamp: string;
}

export interface DecisionExplanation {
  batch_id: string;
  transaction_id: string;
  prediction: {
    transaction_id: string;
    action_id: string;
    predicted_recovery_probability: number;
    model_identifier: string;
  } | null;
  ev: EVTableRow | null;
  policy: PolicyVerdict | null;
  decision: PlanRecord | null;
  execution: ExecutionRecord | null;
  verification: VerificationRow | null;
}

export interface VersionInfo {
  model: string;
  policy: string;
  optimizer: string;
  ev_engine: string;
  simulator: string;
  verification: string;
}

export interface HealthResponse {
  status: string;
  service: string;
  step: number;
  simulation_only: boolean;
}

export interface ActionsResponse {
  actions: ActionSpec[];
  default_resource_limits: ResourceLimits;
  available_splits: string[];
}

export interface BatchRequestPayload {
  split?: string;
  batch_seed?: number;
  resource_limits?: ResourceLimits;
  strategies?: string[];
  transaction_ids?: string[];
  batch_id?: string;
}

export interface CSVIngestionMetadata {
  source_type: string;
  input_row_count: number;
  accepted_row_count: number;
  rejected_row_count: number;
  detected_columns: string[];
  mapped_columns: Record<string, string>;
  unmapped_columns: string[];
  derived_features: string[];
  amount_unit: string;
  amount_transform_applied: number | null;
  customer_count: number;
  warnings: string[];
}

export interface CSVBatchResponse {
  batch_id: string;
  summary: BatchSummary;
  csv_metadata: CSVIngestionMetadata;
}
