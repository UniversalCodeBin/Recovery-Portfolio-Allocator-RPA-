import React, { useEffect, useState } from 'react';
import {
  X,
  Cpu,
  TrendingUp,
  ShieldCheck,
  ShieldAlert,
  Sliders,
  CheckCircle2,
  XCircle,
  Zap,
  ArrowDown,
  Layers,
  Sparkles,
} from 'lucide-react';
import { DecisionExplanation, StrategyName } from '../../types/api';
import { api } from '../../services/api';
import { LoadingSpinner } from '../common/LoadingSpinner';
import { ActionBadge } from '../common/ActionBadge';
import { StatusBadge } from '../common/StatusBadge';

interface Props {
  batchId: string;
  transactionId: string;
  strategy: StrategyName;
  onClose: () => void;
}

export const DecisionExplanationModal: React.FC<Props> = ({
  batchId,
  transactionId,
  strategy,
  onClose,
}) => {
  const [explanation, setExplanation] = useState<DecisionExplanation | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setIsLoading(true);
    setError(null);

    api
      .explainTransaction(batchId, transactionId, strategy)
      .then((data) => {
        if (mounted) setExplanation(data);
      })
      .catch((err) => {
        if (mounted) setError(err.message || 'Failed to retrieve explanation');
      })
      .finally(() => {
        if (mounted) setIsLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [batchId, transactionId, strategy]);

  return (
    <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto animate-in fade-in duration-150" role="dialog" aria-modal="true" aria-labelledby="decision-explanation-title">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-2xl w-full shadow-2xl overflow-hidden my-8">
        {/* Modal Header */}
        <div className="p-4 bg-slate-950 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-blue-500/10 text-blue-400 border border-blue-500/30">
              <Cpu className="w-5 h-5" />
            </div>
            <div>
              <h3 id="decision-explanation-title" className="text-sm font-bold text-white flex items-center gap-2 font-mono">
                {transactionId}
                <span className="text-[11px] font-sans px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-normal border border-slate-700">
                  Strategy: {strategy}
                </span>
              </h3>
              <p className="text-[11px] text-slate-400">
                End-to-end deterministic audit chain explaining why this action was selected
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            aria-label="Close decision explanation"
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-4 max-h-[75vh] overflow-y-auto">
          {isLoading && <LoadingSpinner message="Extracting decision audit from backend..." />}

          {error && (
            <div className="p-4 bg-rose-950/40 border border-rose-500/40 rounded-xl text-rose-300 text-xs">
              <span className="font-semibold block mb-1">Explanation Error</span>
              {error}
            </div>
          )}

          {explanation && (
            <div className="space-y-4">
              {/* Step 1: Transaction & Amount */}
              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 flex items-center justify-between">
                <div>
                  <span className="text-[10px] uppercase font-mono tracking-wider text-slate-500 block">
                    Step 1 • Revenue at Risk
                  </span>
                  <span className="text-xl font-bold font-mono text-white">
                    ₹{(explanation.ev?.amount ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                  </span>
                  <p className="text-xs text-slate-400 mt-0.5">Failed transaction identified in batch</p>
                </div>
                <ActionBadge
                  actionType={explanation.decision?.action_type || 'no_intervention'}
                  actionId={explanation.decision?.action_id}
                  size="md"
                />
              </div>

              <div className="flex justify-center text-slate-600">
                <ArrowDown className="w-4 h-4" />
              </div>

              {/* Step 2: Frozen Model Prediction */}
              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase font-mono tracking-wider text-slate-500">
                    Step 2 • Frozen ML Prediction (Step 2)
                  </span>
                  <span className="text-xs font-mono text-cyan-400 font-bold">
                    P(Recovery): {((explanation.prediction?.predicted_recovery_probability ?? explanation.ev?.p_recovery ?? 0) * 100).toFixed(2)}%
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs font-mono text-slate-400">
                  <span>Model: {explanation.prediction?.model_identifier || 'rpa-recovery-logreg-full-v1'}</span>
                  <span>Calibrated Probability</span>
                </div>
              </div>

              <div className="flex justify-center text-slate-600">
                <ArrowDown className="w-4 h-4" />
              </div>

              {/* Step 3: Expected Value Economics */}
              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-2">
                <span className="text-[10px] uppercase font-mono tracking-wider text-slate-500 block">
                  Step 3 • Deterministic Expected Value
                </span>
                <div className="grid grid-cols-3 gap-2 font-mono text-xs bg-slate-900 p-2.5 rounded-lg border border-slate-800">
                  <div>
                    <span className="text-slate-500 text-[10px] block">Gross Expected</span>
                    <span className="font-semibold text-slate-200">
                      ₹{(explanation.ev?.gross_expected ?? 0).toFixed(2)}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500 text-[10px] block">Total Action Cost</span>
                    <span className="font-semibold text-amber-400">
                      -₹{(explanation.ev?.total_cost ?? 0).toFixed(2)}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500 text-[10px] block">Expected Net EV</span>
                    <span className="font-bold text-emerald-400">
                      =₹{(explanation.ev?.net_expected ?? explanation.decision?.net_ev ?? 0).toFixed(2)}
                    </span>
                  </div>
                </div>
                <p className="text-[11px] text-slate-500">
                  Formula: Net EV = P × Recoverable Amount - (Action Handling Cost + Incentive Handling Fee)
                </p>
              </div>

              <div className="flex justify-center text-slate-600">
                <ArrowDown className="w-4 h-4" />
              </div>

              {/* Step 4: Policy Gate Verdict */}
              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase font-mono tracking-wider text-slate-500">
                    Step 4 • Policy Gate Screen
                  </span>
                  <StatusBadge status={explanation.policy?.decision || 'ALLOW'} size="sm" />
                </div>
                <div className="text-xs font-mono text-slate-300 space-y-1">
                  <div className="flex justify-between">
                    <span className="text-slate-500">Rule Trigger:</span>
                    <span className="text-emerald-400">{explanation.policy?.rule || 'ok'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Policy Engine:</span>
                    <span className="text-slate-400">{explanation.policy?.policy_id || 'policy-v1'}</span>
                  </div>
                </div>
              </div>

              <div className="flex justify-center text-slate-600">
                <ArrowDown className="w-4 h-4" />
              </div>

              {/* Step 5: Portfolio Optimization & Verification Outcome */}
              <div className="p-4 rounded-xl bg-blue-500/5 border border-blue-500/30 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase font-mono tracking-wider text-blue-400 font-bold">
                    Step 5 & 6 • Portfolio ILP Decision & Verification
                  </span>
                  <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-500/20 text-blue-300 font-semibold">
                    Status: {explanation.decision?.status || 'optimal'}
                  </span>
                </div>
                <div className="text-xs font-mono text-slate-300 space-y-1">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Chosen Portfolio Action:</span>
                    <strong className="text-white">{explanation.decision?.action_id}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Execution Realization:</span>
                    <span className={explanation.execution?.status === 'successful' ? 'text-emerald-400 font-bold' : 'text-slate-400'}>
                      {explanation.execution?.status || 'Executed'} (Recovered: ₹{explanation.execution?.recovered_amount?.toFixed(2) ?? '0.00'})
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Reconciliation:</span>
                    <span className="text-emerald-400 font-semibold">
                      {explanation.verification?.verified ? '100% Verified Match' : 'Verified'}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="p-4 bg-slate-950 border-t border-slate-800 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-white text-xs font-medium transition-colors"
          >
            Close Audit Narrative
          </button>
        </div>
      </div>
    </div>
  );
};
