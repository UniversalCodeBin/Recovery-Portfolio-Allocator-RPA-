import React from 'react';
import { AlertTriangle, ShieldCheck } from 'lucide-react';

interface Props {
  compact?: boolean;
}

export const SimulationDisclaimer: React.FC<Props> = ({ compact = false }) => {
  if (compact) {
    return (
      <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs font-medium">
        <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
        <span>Simulation Environment • Seeded Monte-Carlo execution</span>
      </div>
    );
  }

  return (
    <div className="bg-gradient-to-r from-amber-950/40 via-amber-900/20 to-slate-900 border border-amber-500/30 rounded-lg p-3.5 flex items-start gap-3 text-sm text-amber-200/90 shadow-sm">
      <div className="p-1.5 rounded-md bg-amber-500/20 text-amber-400 shrink-0 mt-0.5">
        <AlertTriangle className="w-4 h-4" />
      </div>
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-amber-300">Simulation Mode Active</span>
          <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 font-mono">
            <ShieldCheck className="w-3 h-3" /> Zero-Risk Money Path
          </span>
        </div>
        <p className="text-xs text-amber-200/70 mt-0.5 leading-relaxed">
          All recovery probabilities, expected values, and realization outcomes are computed using a deterministic mathematical model and seeded Monte-Carlo simulator. <strong>No actual customer payments have been processed or real funds transferred.</strong>
        </p>
      </div>
    </div>
  );
};
