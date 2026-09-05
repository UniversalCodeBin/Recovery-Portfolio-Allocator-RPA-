import React, { ReactNode } from 'react';

interface Props {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: ReactNode;
  badge?: string;
  badgeColor?: 'emerald' | 'blue' | 'purple' | 'amber' | 'rose' | 'slate';
  accent?: 'blue' | 'emerald' | 'purple' | 'amber' | 'rose' | 'slate';
}

export const KPICard: React.FC<Props> = ({
  title,
  value,
  subtitle,
  icon,
  badge,
  badgeColor = 'blue',
  accent = 'slate',
}) => {
  const accentGlow = {
    blue: 'hover:border-blue-500/40 hover:shadow-blue-500/5',
    emerald: 'hover:border-emerald-500/40 hover:shadow-emerald-500/5',
    purple: 'hover:border-purple-500/40 hover:shadow-purple-500/5',
    amber: 'hover:border-amber-500/40 hover:shadow-amber-500/5',
    rose: 'hover:border-rose-500/40 hover:shadow-rose-500/5',
    slate: 'hover:border-slate-600',
  }[accent];

  const badgeClass = {
    emerald: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    blue: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
    purple: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
    amber: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
    rose: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
    slate: 'bg-slate-800 text-slate-400 border-slate-700',
  }[badgeColor];

  return (
    <div className={`bg-slate-900/90 border border-slate-800 rounded-xl p-4 transition-all duration-200 shadow-sm ${accentGlow}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">{title}</span>
        <div className="p-2 rounded-lg bg-slate-800/80 text-slate-300 border border-slate-700/50">
          {icon}
        </div>
      </div>
      <div className="mt-2 flex items-baseline justify-between gap-2">
        <span className="text-2xl font-bold font-mono tracking-tight text-white">{value}</span>
        {badge && (
          <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full border ${badgeClass}`}>
            {badge}
          </span>
        )}
      </div>
      {subtitle && (
        <p className="mt-1 text-xs text-slate-400/90 font-normal leading-relaxed">{subtitle}</p>
      )}
    </div>
  );
};
