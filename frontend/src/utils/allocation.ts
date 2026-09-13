import { PlanRecord } from '../types/api';

const ACTION_LABELS: Record<string, string> = {
  no_intervention: 'no-action',
  retry: 'retry',
  payment_link: 'payment link',
  customer_message: 'message',
  incentive: 'incentive',
  human_escalation: 'human',
};

const ACTION_ORDER = [
  'no_intervention',
  'retry',
  'payment_link',
  'customer_message',
  'incentive',
  'human_escalation',
];

export interface AllocationCounts {
  action_type: string;
  count: number;
}

export function getAllocationCounts(planRecords: PlanRecord[]): AllocationCounts[] {
  const counts: Record<string, number> = {};
  for (const rec of planRecords) {
    counts[rec.action_type] = (counts[rec.action_type] || 0) + 1;
  }
  return ACTION_ORDER
    .filter((a) => (counts[a] || 0) > 0)
    .map((a) => ({ action_type: a, count: counts[a] }));
}

export function formatStrategyAllocation(planRecords: PlanRecord[] | undefined): string {
  if (!planRecords || planRecords.length === 0) {
    return '—';
  }
  const counts = getAllocationCounts(planRecords);
  if (counts.length === 0) {
    return '—';
  }
  return counts
    .map((c) => `${c.count} ${ACTION_LABELS[c.action_type] || c.action_type}`)
    .join(' + ');
}
