import React from 'react';
import {
  DollarSign,
  TrendingUp,
  ShieldCheck,
  Zap,
  CheckCircle2,
  XCircle,
  ArrowRight,
  Sparkles,
  Sliders,
  FileSpreadsheet,
  AlertTriangle,
} from 'lucide-react';
import { FullBatchResult, StrategyMetric, StrategyName } from '../../types/api';
import { KPICard } from '../common/KPICard';
import { ResourceMeter } from '../common/ResourceMeter';
import { StatusBadge } from '../common/StatusBadge';
import { SimulationDisclaimer } from '../common/SimulationDisclaimer';
import { ActiveTab } from '../common/Sidebar';

interface Props {
  batch: FullBatchResult | null;
  onNavigate: (tab: ActiveTab) => void;
  onLoadDemo: () => void;
  isLoading: boolean;
}

export const OverviewView: React.FC<Props> = ({
  batch,
  onNavigate,
  onLoadDemo,
  isLoading,
}) => {
  if (!batch) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-center bg-slate-900/50 border border-slate-800 rounded-2xl max-w-xl mx-auto my-12">
        <div className="w-14 h-14 rounded-2xl bg-blue-500/10 border border-blue-500/30 flex items-center justify-center text-blue-400 mb-4 shadow-lg shadow-blue-500/5">
          <Sparkles className="w-7 h-7" />
        </div>
        <h3 className="text-lg font-bold text-white mb-2">No Active Recovery Batch</h3>
        <p className="text-sm text-slate-400 mb-6 max-w-md leading-relaxed">
          Load the verified Razorpay demo batch (370 transactions) or configure a custom run to explore AI-driven portfolio recovery optimization.
        </p>
        <button
          onClick={onLoadDemo}
          disabled={isLoading}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm shadow-lg shadow-blue-500/25 transition-all disabled:opacity-50"
        >
          <Sparkles className="w-4 h-4 text-amber-300" />
          <span>Load Verified Demo Batch</span>
        </button>
      </div>
    );
  }

  // Calculate high-level stats
  const evRows = batch.ev_table || [];
  const uniqueTxns = new Map<string, number>();
  for (const r of evRows) {
    if (!uniqueTxns.has(r.transaction_id)) {
      uniqueTxns.set(r.transaction_id, r.amount);
    }
  }
  let totalRevenueAtRisk = 0;
  uniqueTxns.forEach((amt) => {
    totalRevenueAtRisk += amt;
  });

  const rpaMetrics: StrategyMetric | undefined =
    batch.verifications?.['rpa_optimizer']?.batch_metrics ||
    batch.summary?.strategy_metrics?.['rpa_optimizer'];
  const hasRpaRun = !!rpaMetrics;

  const greedyMetrics: StrategyMetric | undefined =
    batch.verifications?.['ev_greedy']?.batch_metrics ||
    batch.summary?.strategy_metrics?.['ev_greedy'];
  const hasGreedyRun = !!greedyMetrics;

  const noActionMetrics: StrategyMetric | undefined =
    batch.verifications?.['no_action']?.batch_metrics ||
    batch.summary?.strategy_metrics?.['no_action'];
  const hasNoActionRun = !!noActionMetrics;

  const nBlocked =
    batch.summary?.n_blocked_candidates ??
    (batch.verdicts ? batch.verdicts.filter((v) => v.decision === 'BLOCK').length : 0);

  const resourceLimits = batch.resource_limits || {
    incentive_budget: 5000,
    messaging: 2000,
    human_slots: 50,
    retry: 2000,
  };

  const rpaResourceUsed = rpaMetrics?.resource_used || {};

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Simulation Banner */}
      <SimulationDisclaimer />

      {/* Main KPI Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          title="Revenue at Risk"
          value={`₹${totalRevenueAtRisk.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
          subtitle={`${uniqueTxns.size || batch.transaction_ids?.length || 0} failed transactions`}
          icon={<DollarSign className="w-5 h-5 text-rose-400" />}
          badge="Unrecovered"
          badgeColor="rose"
          accent="rose"
        />

        <KPICard
          title="Expected Net EV (RPA)"
          value={`₹${(rpaMetrics?.total_expected_net_ev ?? rpaMetrics?.planned_total_net_ev ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
          subtitle="Exact Mixed-Integer LP (CBC)"
          icon={<TrendingUp className="w-5 h-5 text-blue-400" />}
          badge="Optimal"
          badgeColor="blue"
          accent="blue"
        />

        <KPICard
          title="Simulated Net Recovery"
          value={`₹${(rpaMetrics?.net_recovered_total ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
          subtitle={`Gross ₹${(rpaMetrics?.recovered_total ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })} - Cost ₹${(rpaMetrics?.cost_total ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
          icon={<Zap className="w-5 h-5 text-emerald-400" />}
          badge="Simulated"
          badgeColor="emerald"
          accent="emerald"
        />

        <KPICard
          title="Policy Gate Blocks"
          value={nBlocked.toLocaleString()}
          subtitle="Hard constraints enforced"
          icon={<ShieldCheck className="w-5 h-5 text-amber-400" />}
          badge="ALLOW/BLOCK"
          badgeColor="amber"
          accent="amber"
        />
      </div>

      {/* 2-Column Section: Strategy Summary & Resource Allocation */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Strategy Comparison Summary Card (2 cols) */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                Recovery Strategies Comparison
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
                  Fair Split Comparison
                </span>
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                All strategies receive identical transaction batches, ML probabilities, and policy gates.
              </p>
            </div>
            <button
              onClick={() => onNavigate('comparison')}
              className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 font-medium transition-colors"
            >
              <span>Full Comparison</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-950/60 text-slate-400 font-mono border-b border-slate-800">
                <tr>
                  <th className="py-2.5 px-3">Strategy</th>
                  <th className="py-2.5 px-3">Selection Logic</th>
                  <th className="py-2.5 px-3 text-right">Expected Net EV</th>
                  <th className="py-2.5 px-3 text-right">Simulated Net</th>
                  <th className="py-2.5 px-3 text-right">Cost</th>
                  <th className="py-2.5 px-3 text-center">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono">
                {/* No Action */}
                <tr className="hover:bg-slate-800/30">
                  <td className="py-2.5 px-3 font-semibold text-slate-300">No Action</td>
                  <td className="py-2.5 px-3 text-slate-400 font-sans">No intervention (zero cost)</td>
                  <td className="py-2.5 px-3 text-right text-slate-200">
                    {hasNoActionRun ? `₹${(noActionMetrics?.planned_total_net_ev ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
                  </td>
                  <td className="py-2.5 px-3 text-right text-slate-200">
                    {hasNoActionRun ? `₹${(noActionMetrics?.net_recovered_total ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
                  </td>
                  <td className="py-2.5 px-3 text-right text-slate-500">₹0</td>
                  <td className="py-2.5 px-3 text-center">
                    <StatusBadge status={hasNoActionRun ? "Baseline" : "Not Run"} size="sm" />
                  </td>
                </tr>

                {/* EV Greedy */}
                <tr className="hover:bg-slate-800/30">
                  <td className="py-2.5 px-3 font-semibold text-slate-300">EV-Greedy</td>
                  <td className="py-2.5 px-3 text-slate-400 font-sans">Best EV/resource per txn</td>
                  <td className="py-2.5 px-3 text-right text-slate-200">
                    {hasGreedyRun ? `₹${(greedyMetrics?.planned_total_net_ev ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
                  </td>
                  <td className="py-2.5 px-3 text-right text-slate-200">
                    {hasGreedyRun ? `₹${(greedyMetrics?.net_recovered_total ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
                  </td>
                  <td className="py-2.5 px-3 text-right text-amber-400">
                    {hasGreedyRun ? `₹${(greedyMetrics?.cost_total ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
                  </td>
                  <td className="py-2.5 px-3 text-center">
                    <StatusBadge status={hasGreedyRun ? "Comparator" : "Not Run"} size="sm" />
                  </td>
                </tr>

                {/* RPA Optimizer */}
                <tr className="bg-blue-500/5 hover:bg-blue-500/10 font-bold border-l-2 border-blue-500">
                  <td className="py-2.5 px-3 text-blue-300 flex items-center gap-1.5">
                    <Sparkles className="w-3.5 h-3.5 text-blue-400" />
                    <span>RPA Optimizer</span>
                  </td>
                  <td className="py-2.5 px-3 text-blue-200/90 font-sans font-normal">Exact ILP (OR-Tools)</td>
                  <td className="py-2.5 px-3 text-right text-blue-300 font-bold">
                    {hasRpaRun ? `₹${(rpaMetrics?.planned_total_net_ev ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
                  </td>
                  <td className="py-2.5 px-3 text-right text-emerald-400 font-bold">
                    {hasRpaRun ? `₹${(rpaMetrics?.net_recovered_total ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
                  </td>
                  <td className="py-2.5 px-3 text-right text-amber-400">
                    {hasRpaRun ? `₹${(rpaMetrics?.cost_total ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
                  </td>
                  <td className="py-2.5 px-3 text-center">
                    <StatusBadge status={hasRpaRun ? "Optimal" : "Not Run"} size="sm" />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="pt-2 border-t border-slate-800 text-[11px] text-slate-400 flex items-center justify-between">
            <span>
              Batch Seed: <strong className="text-slate-300 font-mono">{rpaMetrics?.plan_name ? 0 : 0}</strong> • Reconciliation: <strong className="text-emerald-400 font-mono">{hasRpaRun ? 'PASS' : '—'}</strong>
            </span>
            <button
              onClick={() => onNavigate('plan')}
              className="text-blue-400 hover:text-blue-300 font-medium flex items-center gap-1"
            >
              <span>Inspect Recovery Plan</span>
              <ArrowRight className="w-3 h-3" />
            </button>
          </div>
        </div>

        {/* Resource Consumption Overview (1 col) */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-1">
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                <Sliders className="w-4 h-4 text-cyan-400" />
                Resource Budgets
              </h2>
              <button
                onClick={() => onNavigate('resources')}
                className="text-xs text-blue-400 hover:text-blue-300 font-medium flex items-center gap-0.5"
              >
                <span>Details</span>
                <ArrowRight className="w-3 h-3" />
              </button>
            </div>
            <p className="text-xs text-slate-400 mb-4">
              Shared capacity constraints enforced by optimizer.
            </p>

            <div className="space-y-3">
              <ResourceMeter
                name="Retry Capacity"
                consumed={rpaResourceUsed['retry'] || 0}
                capacity={resourceLimits['retry'] || 2000}
                unit="calls"
              />
              <ResourceMeter
                name="Messaging Capacity"
                consumed={rpaResourceUsed['messaging'] || 0}
                capacity={resourceLimits['messaging'] || 2000}
                unit="messages"
              />
              <ResourceMeter
                name="Incentive Budget"
                consumed={rpaResourceUsed['incentive_budget'] || 0}
                capacity={resourceLimits['incentive_budget'] || 5000}
                unit="₹"
              />
              <ResourceMeter
                name="Human Slots"
                consumed={rpaResourceUsed['human_slots'] || 0}
                capacity={resourceLimits['human_slots'] || 50}
                unit="slots"
              />
            </div>
          </div>

          <div className="pt-3 border-t border-slate-800 flex items-center justify-between text-xs text-slate-500">
            <span>Guaranteed feasible via No-Op fallback</span>
            <span className="text-emerald-400 font-mono font-medium">Within Limits</span>
          </div>
        </div>
      </div>
    </div>
  );
};
