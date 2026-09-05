import React from 'react';

interface Props {
  name: string;
  consumed: number;
  capacity: number;
  unit?: string;
  description?: string;
}

export const ResourceMeter: React.FC<Props> = ({
  name,
  consumed,
  capacity,
  unit = 'units',
  description,
}) => {
  const percentage = capacity > 0 ? Math.min(100, Math.round((consumed / capacity) * 100)) : 0;
  const remaining = Math.max(0, capacity - consumed);

  let barColor = 'bg-blue-500';
  let badgeColor = 'text-blue-400 bg-blue-500/10 border-blue-500/30';
  if (percentage >= 95) {
    barColor = 'bg-rose-500';
    badgeColor = 'text-rose-400 bg-rose-500/10 border-rose-500/30';
  } else if (percentage >= 75) {
    barColor = 'bg-amber-500';
    badgeColor = 'text-amber-300 bg-amber-500/10 border-amber-500/30';
  }

  return (
    <div className="bg-slate-900/80 border border-slate-800 rounded-lg p-3.5 space-y-2.5">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-sm font-semibold text-slate-200 capitalize">{name.replace('_', ' ')}</span>
          {description && <p className="text-xs text-slate-500 mt-0.5">{description}</p>}
        </div>
        <span className={`text-xs font-mono font-semibold px-2 py-0.5 rounded border ${badgeColor}`}>
          {percentage}% Used
        </span>
      </div>

      <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${percentage}%` }}
        />
      </div>

      <div className="flex items-center justify-between text-xs font-mono text-slate-400 pt-0.5">
        <span>
          Consumed: <strong className="text-slate-200">{consumed.toLocaleString()}</strong> / {capacity.toLocaleString()} {unit}
        </span>
        <span className="text-slate-500">
          Remaining: <span className="text-emerald-400 font-medium">{remaining.toLocaleString()}</span>
        </span>
      </div>
    </div>
  );
};
