import React, { useState } from 'react';
import {
  PlayCircle,
  CheckCircle2,
  XCircle,
  ShieldAlert,
  Zap,
  RotateCcw,
  Sparkles,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  ShieldCheck,
} from 'lucide-react';
import { FullBatchResult, StrategyName, StrategyMetric, VerificationRow } from '../../types/api';
import { KPICard } from '../common/KPICard';
import { StatusBadge } from '../common/StatusBadge';
import { ActionBadge } from '../common/ActionBadge';
import { SimulationDisclaimer } from '../common/SimulationDisclaimer';

interface Props {
  batch: FullBatchResult | null;
  onExecute: (strategy: StrategyName, seed: number) => void;
  isLoading: boolean;
}

export const ExecutionView: React.FC<Props> = ({ batch, onExecute, isLoading }) => {
  const [strategy, setStrategy] = useState<StrategyName>('rpa_optimizer');
  const [seed, setSeed] = useState(0);
  const [page, setPage] = useState(1);
  const pageSize = 50;

  if (!batch) {
    return <div className="p-8 text-center text-slate-400">No active batch loaded.</div>;
  }

  const verifData = batch.verifications?.[strategy];
  const metrics: StrategyMetric | undefined =
    verifData?.batch_metrics || batch.summary?.strategy_metrics?.[strategy];

  const rows: VerificationRow[] = verifData?.rows || [];

  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const displayedRows = rows.slice((page - 1) * pageSize, page * pageSize);

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Simulation Banner */}
      <SimulationDisclaimer />

      {/* Execution Control Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-bold text-white flex items-center gap-2">
            <PlayCircle className="w-5 h-5 text-emerald-400" />
            Simulated Execution & Reconciliation Layer
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Seeded Monte-Carlo recovery realization with fail-closed policy enforcement and strict planned-vs-executed verification.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Strategy selector */}
          <select
            value={strategy}
            onChange={(e) => {
              setStrategy(e.target.value as StrategyName);
              setPage(1);
            }}
            className="bg-slate-800 border border-slate-700 text-slate-200 text-xs rounded-lg px-3 py-1.5 focus:outline-none focus:border-blue-500 font-mono"
          >
            <option value="rpa_optimizer">RPA Optimizer (ILP)</option>
            <option value="ev_greedy">EV-Greedy Comparator</option>
            <option value="rule_based">Rule-Based</option>
            <option value="no_action">No Action</option>
          </select>

          {/* Seed selector */}
          <div className="flex items-center gap-1.5 text-xs font-mono bg-slate-800 px-2.5 py-1.5 rounded-lg border border-slate-700">
            <span className="text-slate-400">Seed:</span>
            <input
              type="number"
              value={seed}
              onChange={(e) => setSeed(parseInt(e.target.value) || 0)}
              className="w-14 bg-slate-900 border border-slate-700 rounded px-1 text-white font-mono text-center focus:outline-none"
            />
          </div>

          <button
            onClick={() => onExecute(strategy, seed)}
            disabled={isLoading}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs shadow-md shadow-emerald-500/20 transition-all disabled:opacity-50"
          >
            <Zap className={`w-3.5 h-3.5 ${isLoading ? 'animate-pulse' : ''}`} />
            <span>{isLoading ? 'Simulating...' : 'Run Simulation'}</span>
          </button>
        </div>
      </div>

      {/* Realized Metrics Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          title="Recovered (Gross)"
          value={`₹${(metrics?.recovered_total ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
          subtitle={`Planned Net EV: ₹${(metrics?.planned_total_net_ev ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
          icon={<CheckCircle2 className="w-5 h-5 text-emerald-400" />}
          badge="Monte-Carlo"
          badgeColor="emerald"
        />

        <KPICard
          title="Execution Costs"
          value={`₹${(metrics?.cost_total ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
          subtitle="Handling + Incentive Fees"
          icon={<Zap className="w-5 h-5 text-amber-400" />}
          badge="Incurred"
          badgeColor="amber"
        />

        <KPICard
          title="Net Realized Amount"
          value={`₹${(metrics?.net_recovered_total ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
          subtitle="Gross Recovered - Total Costs"
          icon={<ShieldCheck className="w-5 h-5 text-cyan-400" />}
          badge="Net Realized"
          badgeColor="blue"
          accent="blue"
        />

        <KPICard
          title="Success / Failed"
          value={`${metrics?.n_successful ?? 0} / ${metrics?.n_failed ?? 0}`}
          subtitle={`Blocked by policy: ${metrics?.n_blocked ?? 0}`}
          icon={<XCircle className="w-5 h-5 text-rose-400" />}
          badge={metrics?.all_verified ? '100% Verified' : 'Reconciled'}
          badgeColor={metrics?.all_verified ? 'emerald' : 'slate'}
          accent="emerald"
        />
      </div>

      {/* Reconciliation Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
        <div className="p-4 bg-slate-950/40 border-b border-slate-800 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              Reconciliation Ledger (Planned vs Executed)
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Every planned action is verified against its simulator execution log. Fail-closed: unapproved actions are strictly blocked.
            </p>
          </div>
          <span className="text-xs font-mono px-2.5 py-1 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
            Reconciliation: {metrics?.all_verified ? 'PASS' : 'PENDING'}
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-slate-950/80 text-slate-400 border-b border-slate-800 text-[11px] uppercase">
              <tr>
                <th className="py-2.5 px-3">Transaction ID</th>
                <th className="py-2.5 px-3">Planned Action</th>
                <th className="py-2.5 px-3">Executed Action</th>
                <th className="py-2.5 px-3 text-right">Planned EV</th>
                <th className="py-2.5 px-3 text-right">Recovered</th>
                <th className="py-2.5 px-3 text-right">Cost</th>
                <th className="py-2.5 px-3 text-right">Net Realized</th>
                <th className="py-2.5 px-3 text-center">Outcome</th>
                <th className="py-2.5 px-3 text-center">Verified</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {displayedRows.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-slate-500 font-sans">
                    No execution rows found for strategy {strategy}. Click "Run Simulation" above to execute.
                  </td>
                </tr>
              ) : (
                displayedRows.map((row) => (
                  <tr key={row.transaction_id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-2.5 px-3 font-semibold text-slate-200">
                      {row.transaction_id}
                    </td>
                    <td className="py-2.5 px-3 font-sans">
                      <ActionBadge actionType={row.planned_action_type} actionId={row.planned_action_id} size="sm" />
                    </td>
                    <td className="py-2.5 px-3 font-sans">
                      <ActionBadge actionType={row.executed_action_id} actionId={row.executed_action_id} size="sm" />
                    </td>
                    <td className="py-2.5 px-3 text-right text-slate-300">
                      ₹{row.planned_net_ev.toFixed(1)}
                    </td>
                    <td className="py-2.5 px-3 text-right text-emerald-400 font-medium">
                      ₹{row.recovered_amount.toFixed(1)}
                    </td>
                    <td className="py-2.5 px-3 text-right text-amber-400">
                      ₹{row.recovery_cost.toFixed(1)}
                    </td>
                    <td className="py-2.5 px-3 text-right font-bold text-slate-100">
                      ₹{row.net_recovered_amount.toFixed(1)}
                    </td>
                    <td className="py-2.5 px-3 text-center">
                      <StatusBadge status={row.executed_status} size="sm" />
                    </td>
                    <td className="py-2.5 px-3 text-center">
                      <StatusBadge status={row.verified ? 'Verified' : 'Failed'} size="sm" />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Footer */}
        <div className="p-3 bg-slate-950/60 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400 font-mono">
          <div>
            Showing {rows.length > 0 ? (page - 1) * pageSize + 1 : 0} to{' '}
            {Math.min(page * pageSize, rows.length)} of {rows.length} execution records
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="p-1 rounded bg-slate-800 border border-slate-700 text-slate-300 disabled:opacity-40 hover:bg-slate-700"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span>
              Page {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="p-1 rounded bg-slate-800 border border-slate-700 text-slate-300 disabled:opacity-40 hover:bg-slate-700"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
