import React, { useState, useMemo } from 'react';
import {
  FileSpreadsheet,
  Search,
  Filter,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Eye,
  Sparkles,
} from 'lucide-react';
import { FullBatchResult, PlanRecord, StrategyName, EVTableRow, PolicyVerdict } from '../../types/api';
import { ActionBadge } from '../common/ActionBadge';
import { StatusBadge } from '../common/StatusBadge';

interface Props {
  batch: FullBatchResult | null;
  onExplainTransaction: (txnId: string, strategy: StrategyName) => void;
}

export const RecoveryPlanView: React.FC<Props> = ({ batch, onExplainTransaction }) => {
  const [strategy, setStrategy] = useState<StrategyName>('rpa_optimizer');
  const [search, setSearch] = useState('');
  const [actionFilter, setActionFilter] = useState('ALL');
  const [sortBy, setSortBy] = useState<'amount' | 'net_ev' | 'prob'>('amount');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [page, setPage] = useState(1);
  const pageSize = 50;

  if (!batch) {
    return <div className="p-8 text-center text-slate-400">No batch loaded.</div>;
  }

  // Pre-index EV table rows and verdicts by `${transaction_id}:${action_id}` for fast lookup
  const evLookup = useMemo(() => {
    const map = new Map<string, EVTableRow>();
    (batch.ev_table || []).forEach((row) => {
      map.set(`${row.transaction_id}:${row.action_id}`, row);
    });
    return map;
  }, [batch.ev_table]);

  const verdictLookup = useMemo(() => {
    const map = new Map<string, PolicyVerdict>();
    (batch.verdicts || []).forEach((v) => {
      map.set(`${v.transaction_id}:${v.action_id}`, v);
    });
    return map;
  }, [batch.verdicts]);

  // Current plan records
  const planRecords: PlanRecord[] = batch.plans?.[strategy] || [];

  // Filter and sort
  const filteredRecords = useMemo(() => {
    return planRecords.filter((rec) => {
      if (search && !rec.transaction_id.toLowerCase().includes(search.toLowerCase())) {
        return false;
      }
      if (actionFilter !== 'ALL' && rec.action_id !== actionFilter && rec.action_type !== actionFilter) {
        return false;
      }
      return true;
    }).sort((a, b) => {
      const keyA = `${a.transaction_id}:${a.action_id}`;
      const keyB = `${b.transaction_id}:${b.action_id}`;
      const evA = evLookup.get(keyA);
      const evB = evLookup.get(keyB);

      let valA = 0;
      let valB = 0;

      if (sortBy === 'amount') {
        valA = evA?.amount ?? 0;
        valB = evB?.amount ?? 0;
      } else if (sortBy === 'net_ev') {
        valA = a.net_ev;
        valB = b.net_ev;
      } else if (sortBy === 'prob') {
        valA = evA?.p_recovery ?? 0;
        valB = evB?.p_recovery ?? 0;
      }

      return sortOrder === 'desc' ? valB - valA : valA - valB;
    });
  }, [planRecords, search, actionFilter, sortBy, sortOrder, evLookup]);

  const totalPages = Math.max(1, Math.ceil(filteredRecords.length / pageSize));
  const displayedRecords = filteredRecords.slice((page - 1) * pageSize, page * pageSize);

  const availableStrategies: StrategyName[] = Object.keys(batch.plans || {}) as StrategyName[];

  return (
    <div className="space-y-4 animate-in fade-in duration-200">
      {/* Header with Strategy Selector & Filters */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <FileSpreadsheet className="w-5 h-5 text-blue-400" />
              Recovery Allocation Plan
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Portfolio allocations determined for all {planRecords.length} transactions in batch.
            </p>
          </div>

          {/* Strategy Tabs */}
          <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-lg border border-slate-800 text-xs font-mono">
            {availableStrategies.map((sName) => (
              <button
                key={sName}
                onClick={() => {
                  setStrategy(sName);
                  setPage(1);
                }}
                className={`px-3 py-1.5 rounded-md font-medium transition-all ${
                  strategy === sName
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {sName === 'rpa_optimizer' ? '⭐ RPA (ILP)' : sName.replace('_', '-')}
              </button>
            ))}
          </div>
        </div>

        {/* Filter bar */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5 pt-2 border-t border-slate-800 text-xs">
          {/* Search */}
          <div className="relative flex-1">
            <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-2.5" />
            <input
              type="text"
              placeholder="Search by Transaction ID (e.g. txn_0000016)..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-9 pr-3 py-2 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 font-mono"
            />
          </div>

          {/* Action Filter */}
          <div className="flex items-center gap-1.5">
            <Filter className="w-3.5 h-3.5 text-slate-400 shrink-0" />
            <select
              value={actionFilter}
              onChange={(e) => {
                setActionFilter(e.target.value);
                setPage(1);
              }}
              className="bg-slate-950 border border-slate-800 text-slate-300 rounded-lg px-2.5 py-2 focus:outline-none focus:border-blue-500 font-mono"
            >
              <option value="ALL">All Assigned Actions</option>
              <option value="act_retry">Smart Retry</option>
              <option value="act_payment_link">Payment Link</option>
              <option value="act_customer_message">Customer Message</option>
              <option value="act_incentive">Incentive</option>
              <option value="act_human_escalation">Human Escalation</option>
              <option value="act_no_intervention">No Intervention</option>
            </select>
          </div>

          {/* Sort By */}
          <div className="flex items-center gap-1.5">
            <ArrowUpDown className="w-3.5 h-3.5 text-slate-400 shrink-0" />
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as any)}
              className="bg-slate-950 border border-slate-800 text-slate-300 rounded-lg px-2.5 py-2 focus:outline-none focus:border-blue-500 font-mono"
            >
              <option value="amount">Sort: Txn Amount</option>
              <option value="net_ev">Sort: Expected Net EV</option>
              <option value="prob">Sort: Recovery Probability</option>
            </select>
            <button
              onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
              className="px-2 py-2 bg-slate-950 border border-slate-800 text-slate-300 rounded-lg hover:bg-slate-800 font-mono"
              title="Toggle Sort Direction"
            >
              {sortOrder === 'desc' ? '↓' : '↑'}
            </button>
          </div>
        </div>
      </div>

      {/* Transactions Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950/80 text-slate-400 font-mono border-b border-slate-800 uppercase tracking-wider text-[11px]">
              <tr>
                <th className="py-2.5 px-3">Transaction ID</th>
                <th className="py-2.5 px-3 text-right">Amount</th>
                <th className="py-2.5 px-3">Chosen Action</th>
                <th className="py-2.5 px-3 text-right">P(Recovery)</th>
                <th className="py-2.5 px-3 text-right">Gross EV</th>
                <th className="py-2.5 px-3 text-right">Cost</th>
                <th className="py-2.5 px-3 text-right">Net EV</th>
                <th className="py-2.5 px-3 text-center">Policy Gate</th>
                <th className="py-2.5 px-3 text-center">Decision Audit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 font-mono">
              {displayedRecords.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-slate-500 font-sans">
                    No transactions match the selected filter.
                  </td>
                </tr>
              ) : (
                displayedRecords.map((rec) => {
                  const evKey = `${rec.transaction_id}:${rec.action_id}`;
                  const ev = evLookup.get(evKey);
                  const verdict = verdictLookup.get(evKey);

                  const amt = ev?.amount ?? 0;
                  const prob = ev?.p_recovery ? (ev.p_recovery * 100).toFixed(1) : '—';
                  const gross = ev?.gross_expected ?? 0;
                  const cost = ev?.total_cost ?? 0;

                  return (
                    <tr key={rec.transaction_id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="py-2.5 px-3 font-semibold text-slate-200">
                        {rec.transaction_id}
                      </td>
                      <td className="py-2.5 px-3 text-right font-medium text-slate-100">
                        ₹{amt.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                      </td>
                      <td className="py-2.5 px-3 font-sans">
                        <ActionBadge actionType={rec.action_type} actionId={rec.action_id} size="sm" />
                      </td>
                      <td className="py-2.5 px-3 text-right text-cyan-300">
                        {prob !== '—' ? `${prob}%` : '—'}
                      </td>
                      <td className="py-2.5 px-3 text-right text-slate-300">
                        ₹{gross.toLocaleString('en-IN', { maximumFractionDigits: 1 })}
                      </td>
                      <td className="py-2.5 px-3 text-right text-amber-400">
                        ₹{cost.toLocaleString('en-IN', { maximumFractionDigits: 1 })}
                      </td>
                      <td className="py-2.5 px-3 text-right font-bold text-emerald-400">
                        ₹{rec.net_ev.toLocaleString('en-IN', { maximumFractionDigits: 1 })}
                      </td>
                      <td className="py-2.5 px-3 text-center">
                        <StatusBadge status={verdict?.decision || 'ALLOW'} size="sm" />
                      </td>
                      <td className="py-2.5 px-3 text-center">
                        <button
                          onClick={() => onExplainTransaction(rec.transaction_id, strategy)}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 border border-blue-500/30 text-[11px] font-sans font-medium transition-colors"
                        >
                          <Eye className="w-3 h-3" />
                          <span>Explain</span>
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Footer */}
        <div className="p-3 bg-slate-950/60 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400 font-mono">
          <div>
            Showing {filteredRecords.length > 0 ? (page - 1) * pageSize + 1 : 0} to{' '}
            {Math.min(page * pageSize, filteredRecords.length)} of {filteredRecords.length} records
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="p-1 rounded bg-slate-800 border border-slate-700 text-slate-300 disabled:opacity-40 hover:bg-slate-700 transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span>
              Page {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="p-1 rounded bg-slate-800 border border-slate-700 text-slate-300 disabled:opacity-40 hover:bg-slate-700 transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
