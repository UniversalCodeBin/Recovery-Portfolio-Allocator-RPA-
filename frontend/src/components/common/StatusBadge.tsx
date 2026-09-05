import React from 'react';
import { CheckCircle2, XCircle, AlertCircle, Clock, ShieldAlert, Check } from 'lucide-react';

interface Props {
  status: string;
  size?: 'sm' | 'md';
}

export const StatusBadge: React.FC<Props> = ({ status, size = 'md' }) => {
  const normalized = (status || '').toLowerCase();
  const px = size === 'sm' ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs';

  if (normalized === 'allow' || normalized === 'approved' || normalized === 'optimal' || normalized === 'verified' || normalized === 'successful') {
    return (
      <span className={`inline-flex items-center gap-1 font-medium rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 ${px}`}>
        <CheckCircle2 className="w-3 h-3" />
        <span className="capitalize">{status}</span>
      </span>
    );
  }

  if (normalized === 'block' || normalized === 'blocked' || normalized === 'failed' || normalized === 'error') {
    return (
      <span className={`inline-flex items-center gap-1 font-medium rounded-full bg-rose-500/15 text-rose-400 border border-rose-500/30 ${px}`}>
        <XCircle className="w-3 h-3" />
        <span className="capitalize">{status}</span>
      </span>
    );
  }

  if (normalized === 'pending' || normalized === 'attempted' || normalized === 'running') {
    return (
      <span className={`inline-flex items-center gap-1 font-medium rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30 ${px}`}>
        <Clock className="w-3 h-3 animate-spin" />
        <span className="capitalize">{status}</span>
      </span>
    );
  }

  return (
    <span className={`inline-flex items-center gap-1 font-medium rounded-full bg-slate-800 text-slate-300 border border-slate-700 ${px}`}>
      <AlertCircle className="w-3 h-3 text-slate-400" />
      <span className="capitalize">{status}</span>
    </span>
  );
};
