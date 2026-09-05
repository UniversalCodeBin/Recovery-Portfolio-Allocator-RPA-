import React from 'react';
import { Sliders, Shield, Zap, Info, CheckCircle2 } from 'lucide-react';
import { FullBatchResult, StrategyMetric } from '../../types/api';
import { ResourceMeter } from '../common/ResourceMeter';
import { ActionBadge } from '../common/ActionBadge';

interface Props {
  batch: FullBatchResult | null;
}

export const ResourceConstraintsView: React.FC<Props> = ({ batch }) => {
  if (!batch) {
    return <div className="p-8 text-center text-slate-400">No active batch loaded.</div>;
  }

  const limits = batch.resource_limits || {
    incentive_budget: 5000,
    messaging: 2000,
    human_slots: 50,
    retry: 2000,
  };

  const rpaMetrics: StrategyMetric | undefined =
    batch.verifications?.['rpa_optimizer']?.batch_metrics ||
    batch.summary?.strategy_metrics?.['rpa_optimizer'];

  const consumed = rpaMetrics?.resource_used || {};

  const resourceDefinitions = [
    {
      key: 'retry',
      name: 'Smart Retry Limit',
      unit: 'calls',
      capacity: limits.retry ?? 2000,
      used: consumed['retry'] ?? 0,
      description: 'API automated payment retry quota to avoid gateway rate-limiting.',
      consumedBy: ['act_retry'],
    },
    {
      key: 'messaging',
      name: 'Customer Messaging Quota',
      unit: 'messages',
      capacity: limits.messaging ?? 2000,
      used: consumed['messaging'] ?? 0,
      description: 'SMS, WhatsApp, and email notification capacity across all interventions.',
      consumedBy: ['act_payment_link', 'act_customer_message', 'act_incentive', 'act_human_escalation'],
    },
    {
      key: 'incentive_budget',
      name: 'Incentive Discount Budget',
      unit: '₹ INR',
      capacity: limits.incentive_budget ?? 5000,
      used: consumed['incentive_budget'] ?? 0,
      description: 'Merchant promotional recovery discount pool (50 units per incentive).',
      consumedBy: ['act_incentive'],
    },
    {
      key: 'human_slots',
      name: 'Human Escalation Desk',
      unit: 'slots',
      capacity: limits.human_slots ?? 50,
      used: consumed['human_slots'] ?? 0,
      description: 'Dedicated support operations team capacity for high-value manual recovery.',
      consumedBy: ['act_human_escalation'],
    },
  ];

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h2 className="text-base font-bold text-white flex items-center gap-2">
          <Sliders className="w-5 h-5 text-cyan-400" />
          Shared Portfolio Resource Constraints
        </h2>
        <p className="text-xs text-slate-400 mt-1 leading-relaxed">
          The core differentiator of the Recovery Portfolio Allocator: instead of isolated transaction heuristics, the ILP optimizer allocates scarce organizational budgets across the entire transaction portfolio to maximize aggregate recovered net expected value.
        </p>
      </div>

      {/* Grid of Resource Meters */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {resourceDefinitions.map((res) => (
          <div key={res.key} className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
            <ResourceMeter
              name={res.name}
              consumed={res.used}
              capacity={res.capacity}
              unit={res.unit}
              description={res.description}
            />

            <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-xs">
              <span className="text-slate-500">Actions consuming this:</span>
              <div className="flex items-center gap-1.5 flex-wrap">
                {res.consumedBy.map((actionId) => (
                  <ActionBadge key={actionId} actionType={actionId} size="sm" />
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Action Resource Requirements Matrix */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <Info className="w-4 h-4 text-blue-400" />
          Candidate Action Consumption Matrix
        </h3>
        <p className="text-xs text-slate-400">
          Deterministic resource requirements per intervention evaluated by the Mixed-Integer LP solver:
        </p>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-slate-950/60 text-slate-400 border-b border-slate-800 text-[11px] uppercase">
              <tr>
                <th className="py-2.5 px-3">Action</th>
                <th className="py-2.5 px-3 text-right">Direct Cost</th>
                <th className="py-2.5 px-3 text-center">Retry</th>
                <th className="py-2.5 px-3 text-center">Messaging</th>
                <th className="py-2.5 px-3 text-center">Incentive Budget</th>
                <th className="py-2.5 px-3 text-center">Human Slots</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 text-slate-300">
              <tr className="hover:bg-slate-800/30">
                <td className="py-2.5 px-3 font-sans font-medium"><ActionBadge actionType="no_intervention" size="sm" /></td>
                <td className="py-2.5 px-3 text-right text-emerald-400">₹0.00</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
              </tr>
              <tr className="hover:bg-slate-800/30">
                <td className="py-2.5 px-3 font-sans font-medium"><ActionBadge actionType="retry" size="sm" /></td>
                <td className="py-2.5 px-3 text-right text-slate-200">₹1.00</td>
                <td className="py-2.5 px-3 text-center text-blue-400 font-bold">1</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
              </tr>
              <tr className="hover:bg-slate-800/30">
                <td className="py-2.5 px-3 font-sans font-medium"><ActionBadge actionType="payment_link" size="sm" /></td>
                <td className="py-2.5 px-3 text-right text-slate-200">₹2.00</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
                <td className="py-2.5 px-3 text-center text-cyan-400 font-bold">1</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
              </tr>
              <tr className="hover:bg-slate-800/30">
                <td className="py-2.5 px-3 font-sans font-medium"><ActionBadge actionType="customer_message" size="sm" /></td>
                <td className="py-2.5 px-3 text-right text-slate-200">₹0.50</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
                <td className="py-2.5 px-3 text-center text-cyan-400 font-bold">1</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
              </tr>
              <tr className="hover:bg-slate-800/30">
                <td className="py-2.5 px-3 font-sans font-medium"><ActionBadge actionType="incentive" size="sm" /></td>
                <td className="py-2.5 px-3 text-right text-amber-400">₹25.00</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
                <td className="py-2.5 px-3 text-center text-cyan-400 font-bold">1</td>
                <td className="py-2.5 px-3 text-center text-amber-400 font-bold">50.0</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
              </tr>
              <tr className="hover:bg-slate-800/30">
                <td className="py-2.5 px-3 font-sans font-medium"><ActionBadge actionType="human_escalation" size="sm" /></td>
                <td className="py-2.5 px-3 text-right text-rose-400">₹40.00</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
                <td className="py-2.5 px-3 text-center text-cyan-400 font-bold">1</td>
                <td className="py-2.5 px-3 text-center text-slate-500">0</td>
                <td className="py-2.5 px-3 text-center text-indigo-400 font-bold">1</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
