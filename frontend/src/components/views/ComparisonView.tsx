import React, { useState } from 'react';
import {
  GitCompare,
  Sparkles,
  CheckCircle2,
  XCircle,
  ShieldCheck,
  RefreshCw,
  AlertCircle,
  HelpCircle,
  Zap,
} from 'lucide-react';
import { FullBatchResult, StrategyMetric, StrategyName } from '../../types/api';
import { StatusBadge } from '../common/StatusBadge';
import { SimulationDisclaimer } from '../common/SimulationDisclaimer';

interface Props {
  batch: FullBatchResult | null;
  onRunComparison: (seed: number) => void;
  isLoading: boolean;
}

export const ComparisonView: React.FC<Props> = ({
  batch,
  onRunComparison,
  isLoading,
}) => {
  const [seed, setSeed] = useState(0);

  if (!batch) {
    return (
      <div className="p-8 text-center text-slate-400">
        No batch loaded. Load a demo batch or run a new recovery batch.
      </div>
    );
  }

  const verifs = batch.verifications || {};
  const summaryMetrics = batch.summary?.strategy_metrics || {};

  const strategies: {
    id: StrategyName;
    title: string;
    description: string;
    badge: string;
    badgeColor: string;
    isRecommended?: boolean;
  }[] = [
    {
      id: 'no_action',
      title: 'No Action (Baseline)',
      description: 'Zero interventions. Natural baseline recovery without handling costs.',
      badge: 'Baseline',
      badgeColor: 'slate',
    },
    {
      id: 'rule_based',
      title: 'Rule-Based Heuristic',
      description: 'Deterministic merchant business rules without expected-value optimization.',
      badge: 'Rules',
      badgeColor: 'amber',
    },
    {
      id: 'ev_greedy',
      title: 'EV-Greedy Comparator',
      description: 'Greedy allocation ranking transactions by best EV-per-resource ratio.',
      badge: 'Greedy',
      badgeColor: 'blue',
    },
    {
      id: 'rpa_optimizer',
      title: 'RPA Optimizer (ILP)',
      description: 'Exact Mixed-Integer Linear Programming over the entire batch portfolio.',
      badge: 'RPA Recommended',
      badgeColor: 'emerald',
      isRecommended: true,
    },
  ];

  const getMetric = (strat: StrategyName): StrategyMetric | undefined => {
    return verifs[strat]?.batch_metrics || summaryMetrics[strat];
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      <SimulationDisclaimer />

      {/* Header & Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-slate-900 border border-slate-800 rounded-xl p-5">
        <div>
          <h2 className="text-base font-bold text-white flex items-center gap-2">
            <GitCompare className="w-5 h-5 text-blue-400" />
            Strategy Comparison Benchmarks
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Fair comparison: identical transaction batches, identical ML predictions, identical EV formulas, and identical policy gates.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs font-mono bg-slate-800/80 px-2.5 py-1 rounded-lg border border-slate-700">
            <span className="text-slate-400">Batch Seed:</span>
            <input
              type="number"
              value={seed}
              onChange={(e) => setSeed(parseInt(e.target.value) || 0)}
              className="w-14 bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-white font-mono text-center focus:outline-none focus:border-blue-500"
            />
          </div>
          <button
            onClick={() => onRunComparison(seed)}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold text-xs transition-colors shadow-sm disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Re-run Comparison</span>
          </button>
        </div>
      </div>

      {/* Strategy Comparison Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950/80 text-slate-400 font-mono border-b border-slate-800 uppercase tracking-wider text-[11px]">
              <tr>
                <th className="py-3 px-4">Strategy</th>
                <th className="py-3 px-4 text-right">Planned Net EV</th>
                <th className="py-3 px-4 text-right">Simulated Gross</th>
                <th className="py-3 px-4 text-right">Cost</th>
                <th className="py-3 px-4 text-right">Simulated Net</th>
                <th className="py-3 px-4 text-center">Success / Total</th>
                <th className="py-3 px-4 text-center">Resource Usage</th>
                <th className="py-3 px-4 text-center">Verification</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 font-mono">
              {strategies.map((s) => {
                const metric = getMetric(s.id);
                const hasRun = !!metric;
                const netEv = metric?.total_expected_net_ev ?? metric?.planned_total_net_ev ?? 0;
                const recovered = metric?.recovered_total ?? 0;
                const cost = metric?.cost_total ?? 0;
                const netRecovered = metric?.net_recovered_total ?? 0;
                const successful = metric?.n_successful ?? 0;
                const total = metric?.n_planned ?? metric?.n_transactions ?? 0;
                const resources = metric?.resource_used || {};

                return (
                  <tr
                    key={s.id}
                    className={`transition-colors ${
                      s.isRecommended
                        ? 'bg-blue-500/5 hover:bg-blue-500/10 border-l-4 border-blue-500'
                        : 'hover:bg-slate-800/40'
                    }`}
                  >
                    {/* Strategy info */}
                    <td className="py-3.5 px-4 font-sans">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white text-sm">{s.title}</span>
                        {s.isRecommended && (
                          <span className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-300 font-semibold border border-blue-500/30">
                            <Sparkles className="w-3 h-3" /> Exact ILP
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-slate-400 mt-0.5 max-w-sm font-normal">
                        {s.description}
                      </p>
                    </td>

                    {/* Planned Expected Net EV */}
                    <td className="py-3.5 px-4 text-right text-slate-100 font-bold text-sm">
                      {hasRun ? `₹${netEv.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
                    </td>

                    {/* Gross Recovered */}
                    <td className="py-3.5 px-4 text-right text-emerald-400 font-medium">
                      {hasRun ? `₹${recovered.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
                    </td>

                    {/* Cost */}
                    <td className="py-3.5 px-4 text-right text-amber-400 font-medium">
                      {hasRun ? `₹${cost.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'}
                    </td>

                    {/* Net Recovered */}
                    <td className="py-3.5 px-4 text-right font-bold text-sm">
                      {hasRun ? (
                        <span className={netRecovered >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                          ₹${netRecovered.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>

                    {/* Success rate */}
                    <td className="py-3.5 px-4 text-center font-mono">
                      {hasRun ? (
                        <div>
                          <span className="text-slate-200 font-semibold">{successful}</span>
                          <span className="text-slate-500"> / {total}</span>
                        </div>
                      ) : (
                        <span className="text-slate-500">Not Run</span>
                      )}
                    </td>

                    {/* Resource Usage */}
                    <td className="py-3.5 px-4 text-center font-mono text-[11px]">
                      {hasRun ? (
                        <div className="space-y-0.5 text-slate-400">
                          <div>
                            retry: <strong className="text-slate-200">{resources['retry'] || 0}</strong>
                          </div>
                          <div>
                            msg: <strong className="text-slate-200">{resources['messaging'] || 0}</strong>
                          </div>
                        </div>
                      ) : (
                        '—'
                      )}
                    </td>

                    {/* Verification Status */}
                    <td className="py-3.5 px-4 text-center">
                      {hasRun ? (
                        metric.all_verified ? (
                          <StatusBadge status="Verified" size="sm" />
                        ) : (
                          <StatusBadge status="Discrepancy" size="sm" />
                        )
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Honest Scientific Transparency Card */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4.5 text-xs space-y-2 text-slate-300">
        <div className="flex items-center gap-2 font-semibold text-blue-400">
          <HelpCircle className="w-4 h-4" />
          <span>Scientific Transparency & Comparator Notes</span>
        </div>
        <p className="text-slate-400 leading-relaxed">
          On this synthetic validation dataset, the strong <strong>EV-Greedy baseline</strong> and the <strong>RPA exact ILP optimizer</strong> achieve similar total net EV allocations. Under current action unit economics (handling fees of ₹250 for incentives and low baseline recovery probabilities of ~0.03–0.05), high-cost actions are deterministically filtered by the <strong>Policy Gate (`min_net_ev`)</strong>. The system intentionally avoids fabricating false lift, demonstrating mathematically proven portfolio optimization that shines when scarce resources are fiercely contested.
        </p>
      </div>
    </div>
  );
};
