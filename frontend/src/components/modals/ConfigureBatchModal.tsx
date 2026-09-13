import React, { useState, useRef, useCallback } from 'react';
import { X, Play, Sliders, Settings2, Upload, FileText, Download, AlertCircle, CheckCircle2 } from 'lucide-react';
import { BatchRequestPayload, ResourceLimits, CSVIngestionMetadata } from '../../types/api';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (payload: BatchRequestPayload) => void;
  onCsvSubmit: (file: File, params: { batch_seed?: number; resource_limits?: ResourceLimits; strategies?: string[] }) => void;
  isLoading: boolean;
  defaultLimits: ResourceLimits;
  availableSplits: string[];
}

export const ConfigureBatchModal: React.FC<Props> = ({
  isOpen,
  onClose,
  onSubmit,
  onCsvSubmit,
  isLoading,
  defaultLimits,
  availableSplits,
}) => {
  const [dataSource, setDataSource] = useState<'split' | 'csv'>('split');
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

  // CSV upload state
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvPreview, setCsvPreview] = useState<string[][]>([]);
  const [csvError, setCsvError] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const parseCsvPreview = useCallback((content: string): string[][] => {
    const lines = content.split('\n').filter((l) => l.trim());
    if (lines.length === 0) return [];
    const headers = lines[0].split(',').map((h) => h.trim());
    const rows = lines.slice(1, 6).map((line) => line.split(',').map((c) => c.trim()));
    return [headers, ...rows];
  }, []);

  const handleFileChange = useCallback((file: File | null) => {
    setCsvError(null);
    if (!file) {
      setCsvFile(null);
      setCsvPreview([]);
      return;
    }
    if (!file.name.endsWith('.csv') && file.type !== 'text/csv') {
      setCsvError('Please upload a CSV file');
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setCsvError('File size must be under 10 MB');
      return;
    }
    setCsvFile(file);
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      setCsvPreview(parseCsvPreview(text));
    };
    reader.readAsText(file);
  }, [parseCsvPreview]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const file = e.dataTransfer.files[0];
    handleFileChange(file);
  }, [handleFileChange]);

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
    if (dataSource === 'csv' && csvFile) {
      onCsvSubmit(csvFile, {
        batch_seed: seed,
        resource_limits: limits,
        strategies: selectedStrategies,
      });
    } else {
      onSubmit({
        split,
        batch_seed: seed,
        resource_limits: limits,
        strategies: selectedStrategies,
      });
    }
  };

  const downloadTemplate = () => {
    const headers = 'payment_id,customer_id,amount,currency,status,method,bank,failure_reason,error_code,created_at,retry_count,due_date';
    const blob = new Blob([headers + '\n'], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'razorpay_template.csv';
    a.click();
    URL.revokeObjectURL(url);
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
          {/* Payment Data Source Toggle */}
          <div className="space-y-1.5">
            <label className="text-slate-300 font-semibold block">Payment Data Source</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setDataSource('split')}
                className={`flex items-center justify-center gap-2 p-2.5 rounded-lg border font-medium transition-colors ${
                  dataSource === 'split'
                    ? 'bg-blue-500/10 border-blue-500/40 text-blue-300'
                    : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-600'
                }`}
              >
                <Settings2 className="w-3.5 h-3.5" />
                Use Dataset Split
              </button>
              <button
                type="button"
                onClick={() => setDataSource('csv')}
                className={`flex items-center justify-center gap-2 p-2.5 rounded-lg border font-medium transition-colors ${
                  dataSource === 'csv'
                    ? 'bg-blue-500/10 border-blue-500/40 text-blue-300'
                    : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-600'
                }`}
              >
                <Upload className="w-3.5 h-3.5" />
                Upload CSV File
              </button>
            </div>
          </div>

          {/* Split Selection (only when dataSource === 'split') */}
          {dataSource === 'split' && (
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
          )}

          {/* CSV Upload (only when dataSource === 'csv') */}
          {dataSource === 'csv' && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-slate-300 font-semibold block">Upload CSV File</label>
                <button
                  type="button"
                  onClick={downloadTemplate}
                  className="flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-300"
                >
                  <Download className="w-3 h-3" />
                  Download Template
                </button>
              </div>

              <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-colors ${
                  isDragOver
                    ? 'border-blue-500 bg-blue-500/5'
                    : csvFile
                    ? 'border-green-500/40 bg-green-500/5'
                    : 'border-slate-700 hover:border-slate-500'
                }`}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
                  className="hidden"
                />
                {csvFile ? (
                  <div className="flex items-center justify-center gap-2">
                    <FileText className="w-4 h-4 text-green-400" />
                    <span className="text-white font-medium">{csvFile.name}</span>
                    <span className="text-slate-400">({(csvFile.size / 1024).toFixed(1)} KB)</span>
                  </div>
                ) : (
                  <div>
                    <Upload className="w-6 h-6 mx-auto mb-1 text-slate-500" />
                    <p className="text-slate-400">Drag & drop or click to browse</p>
                    <p className="text-[10px] text-slate-500 mt-1">CSV files up to 10 MB</p>
                  </div>
                )}
              </div>

              {csvError && (
                <div className="flex items-center gap-1.5 text-red-400 text-[11px]">
                  <AlertCircle className="w-3.5 h-3.5" />
                  {csvError}
                </div>
              )}

              {/* CSV Preview */}
              {csvPreview.length > 0 && (
                <div className="space-y-1">
                  <p className="text-[11px] text-slate-400 font-medium">
                    Preview ({csvPreview[0]?.length} columns, {csvPreview.length - 1} rows shown):
                  </p>
                  <div className="overflow-x-auto max-h-32 overflow-y-auto rounded border border-slate-800">
                    <table className="w-full text-[10px] font-mono">
                      <thead>
                        <tr className="bg-slate-950">
                          {csvPreview[0]?.map((h, i) => (
                            <th key={i} className="px-1.5 py-1 text-left text-slate-400 whitespace-nowrap">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {csvPreview.slice(1).map((row, i) => (
                          <tr key={i} className="border-t border-slate-800/50">
                            {row.map((cell, j) => (
                              <td key={j} className="px-1.5 py-1 text-slate-300 whitespace-nowrap">{cell}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}

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
              disabled={isLoading || (dataSource === 'csv' && !csvFile)}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold shadow-md shadow-blue-500/20 disabled:opacity-50"
            >
              <Play className="w-3.5 h-3.5" />
              <span>{isLoading ? 'Running Optimization...' : 'Run Recovery Optimization'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
