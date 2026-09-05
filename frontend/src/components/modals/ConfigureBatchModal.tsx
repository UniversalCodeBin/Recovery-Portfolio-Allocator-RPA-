import React, { useState } from 'react';
import { X, Play, Sliders, Settings2, Sparkles } from 'lucide-react';
import { BatchRequestPayload, ResourceLimits } from '../../types/api';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (payload: BatchRequestPayload) => void;
  isLoading: boolean;
  defaultLimits: ResourceLimits;
  availableSplits: string[];
}

export const ConfigureBatchModal: React.FC<Props> = ({
  isOpen,
  onClose,
  onSubmit,
  isLoading,
  defaultLimits,
  availableSplits,
}) => {
  const [split, setSplit] = useState('demo');
  const [seed, setSeed] = useState(0);
  const [limits, setLimits] = useState<ResourceLimits>({
    retry: defaultLimits.retry ?? 2000,
    messaging: defaultLimits.messaging ?? 2000,
    incentive_budget: defaultLimits.incentive_budget ?? 5000,
    human_slots: defaultLimits.human_slots ?? 50,
  });
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([
    'no_action',
    'rule_based',
    'ev_greedy',
    'rpa_optimizer',
  ]);

  if (!isOpen) return null;

  const toggleStrategy = (strat: string) => {
    if (selectedStrategies.includes(strat)) {
      if (selectedStrategies.length > 1) {
        setSelectedStrategies(selectedStrategies.filter((s) => s !== strat));
      }
    } else {
      setSelectedStrategies([...selectedStrategies, strat]);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      split,
      batch_seed: seed,
      resource_limits: limits,
      strategies: selectedStrategies,
    });
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto animate-in fade-in duration-150" role="dialog" aria-modal="true" aria-labelledby="configure-batch-title">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-lg w-full shadow-2xl overflow-hidden my-8">
        <div className="p-4 bg-slate-950 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-blue-500/10 text-blue-400 border border-blue-500/30">
              <Settings2 className="w-5 h-5" />
            </div>
            <div>
              <h3 id="configure-batch-title" className="text-sm font-bold text-white">Configure Recovery Batch</h3>
              <p className="text-[11px] text-slate-400">
                Tune resource constraints and test portfolio optimization
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close batch configuration"
            className="p-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4 text-xs">
          {/* Split Selection */}
          <div className="space-y-1.5">
            <label className="text-slate-300 font-semibold block">Dataset Split</label>
            <select
              value={split}
              onChange={(e) => setSplit(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-white font-mono focus:outline-none focus:border-blue-500"
            >
              {(availableSplits.length > 0 ? availableSplits : ['demo', 'val', 'test', 'train']).map((s) => (
                <option key={s} value={s}>
                  {s.toUpperCase()} split {s === 'demo' ? '(370 txns - Recommended)' : ''}
                </option>
              ))}
            </select>
          </div>

          {/* Random Seed */}
          <div className="space-y-1.5">
            <label className="text-slate-300 font-semibold block">Simulation Random Seed</label>
            <input
              type="number"
              value={seed}
              onChange={(e) => setSeed(parseInt(e.target.value) || 0)}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-white font-mono focus:outline-none focus:border-blue-500"
              placeholder="0"
            />
            <p className="text-[11px] text-slate-500">
              Derives Monte-Carlo outcome realizations; identical seeds reproduce exact results across strategies.
            </p>
          </div>

          {/* Resource Constraints Inputs */}
          <div className="space-y-2 pt-2 border-t border-slate-800">
            <label className="text-slate-300 font-semibold flex items-center gap-1.5">
              <Sliders className="w-3.5 h-3.5 text-cyan-400" />
              Shared Resource Limits (Knapsack Constraints)
            </label>
            <div className="grid grid-cols-2 gap-3 font-mono">
              <div>
                <span className="text-slate-400 text-[10px] block mb-1">Retry Quota</span>
                <input
                  type="number"
                  value={limits.retry ?? 2000}
                  onChange={(e) => setLimits({ ...limits, retry: parseFloat(e.target.value) || 0 })}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg p-2 text-white"
                />
              </div>
              <div>
                <span className="text-slate-400 text-[10px] block mb-1">Messaging Quota</span>
                <input
                  type="number"
                  value={limits.messaging ?? 2000}
                  onChange={(e) => setLimits({ ...limits, messaging: parseFloat(e.target.value) || 0 })}
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg p-2 text-white"
                />
              </div>
              <div>
                <span className="text-slate-400 text-[10px] block mb-1">Incentive Budget (₹)</span>
                <input
                  type="number"
                  value={limits.incentive_budget ?? 5000}
                  onChange={(e) =>
                    setLimits({ ...limits, incentive_budget: parseFloat(e.target.value) || 0 })
                  }
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg p-2 text-white"
                />
              </div>
              <div>
                <span className="text-slate-400 text-[10px] block mb-1">Human Slots</span>
                <input
                  type="number"
                  value={limits.human_slots ?? 50}
                  onChange={(e) =>
                    setLimits({ ...limits, human_slots: parseFloat(e.target.value) || 0 })
                  }
                  className="w-full bg-slate-950 border border-slate-700 rounded-lg p-2 text-white"
                />
              </div>
            </div>
          </div>

          {/* Strategies to Execute */}
          <div className="space-y-2 pt-2 border-t border-slate-800">
            <label className="text-slate-300 font-semibold block">Strategies to Run in Parallel</label>
            <div className="grid grid-cols-2 gap-2 font-mono text-[11px]">
              {['no_action', 'rule_based', 'ev_greedy', 'rpa_optimizer'].map((strat) => (
                <label
                  key={strat}
                  className={`flex items-center gap-2 p-2 rounded-lg border cursor-pointer transition-colors ${
                    selectedStrategies.includes(strat)
                      ? 'bg-blue-500/10 border-blue-500/40 text-blue-300'
                      : 'bg-slate-950 border-slate-800 text-slate-400'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedStrategies.includes(strat)}
                    onChange={() => toggleStrategy(strat)}
                    className="rounded bg-slate-800 border-slate-700 text-blue-600 focus:ring-0"
                  />
                  <span>{strat}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Buttons */}
          <div className="pt-3 border-t border-slate-800 flex justify-end gap-2.5">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold shadow-md shadow-blue-500/20 disabled:opacity-50"
            >
              <Play className="w-3.5 h-3.5" />
              <span>{isLoading ? 'Running Optimization...' : 'Run Recovery Batch'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
