import React, { useState } from 'react';
import {
  Activity,
  CheckCircle2,
  XCircle,
  Layers,
  ChevronDown,
  Play,
  Settings,
  Info,
  Sparkles,
} from 'lucide-react';
import { BatchListItem, HealthResponse, VersionInfo } from '../../types/api';

interface Props {
  health: HealthResponse | null;
  versions: VersionInfo | null;
  batches: BatchListItem[];
  currentBatchId: string | null;
  onSelectBatch: (batchId: string) => void;
  onOpenConfigModal: () => void;
  onLoadDemo: () => void;
  isLoading: boolean;
}

export const Navbar: React.FC<Props> = ({
  health,
  versions,
  batches,
  currentBatchId,
  onSelectBatch,
  onOpenConfigModal,
  onLoadDemo,
  isLoading,
}) => {
  const [showVersions, setShowVersions] = useState(false);
  const [showBatches, setShowBatches] = useState(false);

  const isOnline = health?.status === 'ok';

  return (
    <header className="h-16 bg-slate-900 border-b border-slate-800 px-4 md:px-6 flex items-center justify-between z-30 sticky top-0">
      {/* Brand & Title */}
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-gradient-to-tr from-blue-700 via-blue-600 to-cyan-500 text-white font-black text-lg shadow-md shadow-blue-500/20">
          R
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-sm md:text-base font-bold text-white tracking-tight flex items-center gap-1.5">
              Recovery Portfolio Allocator
            </h1>
          </div>
        </div>
      </div>

      {/* Center / Right controls */}
      <div className="flex items-center gap-2.5 md:gap-4">
        {/* Batch selector dropdown */}
        <div className="relative">
          <button
            onClick={() => setShowBatches(!showBatches)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/90 hover:bg-slate-800 text-slate-200 border border-slate-700 text-xs font-mono transition-colors"
            title="Switch Recovery Batch"
          >
            <Layers className="w-3.5 h-3.5 text-blue-400" />
            <span className="max-w-[140px] truncate font-medium">
              {currentBatchId ? currentBatchId : 'No Batch Loaded'}
            </span>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
          </button>

          {showBatches && (
            <div className="absolute right-0 mt-2 w-72 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl py-1.5 z-50 text-xs divide-y divide-slate-800">
              <div className="px-3 py-2 text-slate-400 font-sans font-semibold flex items-center justify-between">
                <span>Available Runs ({batches.length})</span>
                <span className="text-[10px] text-slate-500">Persisted Runs</span>
              </div>
              <div className="max-h-60 overflow-y-auto py-1">
                {batches.length === 0 ? (
                  <div className="px-3 py-3 text-slate-500 text-center font-sans">
                    No runs found. Run a new batch below.
                  </div>
                ) : (
                  batches.map((b) => (
                    <button
                      key={b.batch_id}
                      onClick={() => {
                        onSelectBatch(b.batch_id);
                        setShowBatches(false);
                      }}
                      className={`w-full text-left px-3 py-2 hover:bg-slate-800/80 transition-colors flex items-center justify-between font-mono ${
                        b.batch_id === currentBatchId ? 'bg-blue-500/10 text-blue-400 font-semibold' : 'text-slate-300'
                      }`}
                    >
                      <div className="truncate">
                        <span className="block truncate">{b.batch_id}</span>
                        <span className="text-[10px] text-slate-500 font-sans block">
                          {b.n_transactions} transactions • {b.strategies.length} strategies
                        </span>
                      </div>
                      {b.batch_id === currentBatchId && (
                        <CheckCircle2 className="w-3.5 h-3.5 text-blue-400 shrink-0 ml-2" />
                      )}
                    </button>
                  ))
                )}
              </div>
              <div className="p-2 bg-slate-950/50">
                <button
                  onClick={() => {
                    setShowBatches(false);
                    onOpenConfigModal();
                  }}
                  className="w-full py-1.5 px-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-sans font-semibold text-center transition-colors flex items-center justify-center gap-1.5"
                >
                  <Play className="w-3 h-3" /> Run New Batch
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Quick Demo CTA */}
        <button
          onClick={onLoadDemo}
          disabled={isLoading}
          className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-semibold shadow-sm shadow-blue-500/20 transition-all disabled:opacity-50"
        >
          <Sparkles className="w-3.5 h-3.5 text-amber-300" />
          <span>Load Demo Batch</span>
        </button>

        {/* Configure Button */}
        <button
          onClick={onOpenConfigModal}
          className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
          title="Batch & Resource Configuration"
        >
          <Settings className="w-4 h-4" />
        </button>

        {/* System Version info button */}
        <div className="relative">
          <button
            onClick={() => setShowVersions(!showVersions)}
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
            title="System Component Versions"
          >
            <Info className="w-4 h-4" />
          </button>

          {showVersions && versions && (
            <div className="absolute right-0 mt-2 w-80 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl p-3 z-50 text-xs space-y-2">
              <div className="font-semibold text-slate-200 border-b border-slate-800 pb-1.5 flex items-center justify-between">
                <span>RPA Component Pipeline</span>
                <span className="text-[10px] text-emerald-400 font-mono">Step 3 Verified</span>
              </div>
              <div className="space-y-1.5 font-mono text-[11px]">
                <div className="flex justify-between text-slate-400">
                  <span>Model:</span>
                  <span className="text-slate-200 font-semibold">{versions.model}</span>
                </div>
                <div className="flex justify-between text-slate-400">
                  <span>Optimizer:</span>
                  <span className="text-slate-200">{versions.optimizer}</span>
                </div>
                <div className="flex justify-between text-slate-400">
                  <span>Policy Gate:</span>
                  <span className="text-slate-200">{versions.policy}</span>
                </div>
                <div className="flex justify-between text-slate-400">
                  <span>EV Engine:</span>
                  <span className="text-slate-200">{versions.ev_engine}</span>
                </div>
                <div className="flex justify-between text-slate-400">
                  <span>Simulator:</span>
                  <span className="text-slate-200">{versions.simulator}</span>
                </div>
                <div className="flex justify-between text-slate-400">
                  <span>Verifier:</span>
                  <span className="text-slate-200">{versions.verification}</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Backend health status badge */}
        <div
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${
            isOnline
              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
              : 'bg-rose-500/10 text-rose-400 border-rose-500/30'
          }`}
          title={isOnline ? 'FastAPI Backend Online (Step 3)' : 'Backend Connection Offline'}
        >
          <span className={`w-2 h-2 rounded-full ${isOnline ? 'bg-emerald-400 animate-pulse' : 'bg-rose-500'}`} />
          <span className="hidden md:inline font-mono">{isOnline ? 'API Connected' : 'Backend Offline'}</span>
        </div>
      </div>
    </header>
  );
};
