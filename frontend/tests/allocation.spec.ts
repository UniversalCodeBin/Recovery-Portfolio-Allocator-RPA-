import { test, expect } from '@playwright/test';
import { formatStrategyAllocation, getAllocationCounts } from '../src/utils/allocation';
import type { PlanRecord } from '../src/types/api';

function makePlanRecords(actionType: string, count: number, name = 'plan'): PlanRecord[] {
  return Array.from({ length: count }, (_, i) => ({
    transaction_id: `${name}-${actionType}-${i}`,
    action_id: `${actionType}_${i}`,
    action_type: actionType,
    net_ev: 0,
    name,
    version: '1.0',
    status: 'planned',
  }));
}

test.describe('formatStrategyAllocation', () => {
  test('TEST 1: single no_intervention allocation', () => {
    const records = makePlanRecords('no_intervention', 70);
    expect(formatStrategyAllocation(records)).toBe('70 no-action');
  });

  test('TEST 2: mixed incentive + human escalation allocation', () => {
    const records = [
      ...makePlanRecords('no_intervention', 58),
      ...makePlanRecords('incentive', 7),
      ...makePlanRecords('human_escalation', 5),
    ];
    expect(formatStrategyAllocation(records)).toBe(
      '58 no-action + 7 incentive + 5 human'
    );
  });

  test('TEST 3: no_action + customer_message allocation', () => {
    const records = [
      ...makePlanRecords('no_intervention', 69),
      ...makePlanRecords('customer_message', 1),
    ];
    expect(formatStrategyAllocation(records)).toBe('69 no-action + 1 message');
  });

  test('TEST 4: full allocation rendered in canonical action order', () => {
    const records = [
      ...makePlanRecords('no_intervention', 10),
      ...makePlanRecords('retry', 3),
      ...makePlanRecords('payment_link', 2),
      ...makePlanRecords('customer_message', 4),
      ...makePlanRecords('incentive', 5),
      ...makePlanRecords('human_escalation', 1),
    ];
    expect(formatStrategyAllocation(records)).toBe(
      '10 no-action + 3 retry + 2 payment link + 4 message + 5 incentive + 1 human'
    );
  });

  test('TEST 4b: allocation sorted canonically regardless of input order', () => {
    const records = [
      ...makePlanRecords('human_escalation', 1),
      ...makePlanRecords('customer_message', 4),
      ...makePlanRecords('incentive', 5),
      ...makePlanRecords('payment_link', 2),
      ...makePlanRecords('retry', 3),
      ...makePlanRecords('no_intervention', 10),
    ];
    expect(formatStrategyAllocation(records)).toBe(
      '10 no-action + 3 retry + 2 payment link + 4 message + 5 incentive + 1 human'
    );
  });

  test('TEST 5: empty allocation array renders em dash', () => {
    expect(formatStrategyAllocation([])).toBe('—');
  });

  test('TEST 6: undefined plan (strategy not run) renders em dash', () => {
    expect(formatStrategyAllocation(undefined)).toBe('—');
  });

  test('TEST 6b: null plan (unavailable allocation) renders em dash', () => {
    expect(formatStrategyAllocation(null as unknown as PlanRecord[])).toBe('—');
  });
});

test.describe('getAllocationCounts', () => {
  test('returns canonical ordered counts for a mixed plan', () => {
    const records = [
      ...makePlanRecords('customer_message', 2),
      ...makePlanRecords('no_intervention', 5),
      ...makePlanRecords('incentive', 1),
    ];
    const counts = getAllocationCounts(records);
    expect(counts).toEqual([
      { action_type: 'no_intervention', count: 5 },
      { action_type: 'customer_message', count: 2 },
      { action_type: 'incentive', count: 1 },
    ]);
  });

  test('returns empty array for empty records', () => {
    expect(getAllocationCounts([])).toEqual([]);
  });
});
