import React from 'react';
import { RefreshCw, Link2, MessageSquare, Gift, UserCheck, ShieldOff } from 'lucide-react';

interface Props {
  actionType: string;
  actionId?: string;
  size?: 'sm' | 'md';
}

export const ActionBadge: React.FC<Props> = ({ actionType, actionId, size = 'md' }) => {
  const norm = (actionType || actionId || '').toLowerCase().replace('act_', '');
  const px = size === 'sm' ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs';

  if (norm.includes('retry')) {
    return (
      <span className={`inline-flex items-center gap-1 font-medium rounded-md bg-blue-500/15 text-blue-400 border border-blue-500/30 ${px}`}>
        <RefreshCw className="w-3 h-3" />
        <span>Smart Retry</span>
      </span>
    );
  }

  if (norm.includes('payment_link')) {
    return (
      <span className={`inline-flex items-center gap-1 font-medium rounded-md bg-purple-500/15 text-purple-400 border border-purple-500/30 ${px}`}>
        <Link2 className="w-3 h-3" />
        <span>Payment Link</span>
      </span>
    );
  }

  if (norm.includes('customer_message') || norm.includes('messaging')) {
    return (
      <span className={`inline-flex items-center gap-1 font-medium rounded-md bg-cyan-500/15 text-cyan-400 border border-cyan-500/30 ${px}`}>
        <MessageSquare className="w-3 h-3" />
        <span>Customer Message</span>
      </span>
    );
  }

  if (norm.includes('incentive')) {
    return (
      <span className={`inline-flex items-center gap-1 font-medium rounded-md bg-amber-500/15 text-amber-300 border border-amber-500/30 ${px}`}>
        <Gift className="w-3 h-3" />
        <span>Discount Incentive</span>
      </span>
    );
  }

  if (norm.includes('human') || norm.includes('escalation')) {
    return (
      <span className={`inline-flex items-center gap-1 font-medium rounded-md bg-indigo-500/15 text-indigo-400 border border-indigo-500/30 ${px}`}>
        <UserCheck className="w-3 h-3" />
        <span>Human Escalation</span>
      </span>
    );
  }

  return (
    <span className={`inline-flex items-center gap-1 font-medium rounded-md bg-slate-800 text-slate-400 border border-slate-700 ${px}`}>
      <ShieldOff className="w-3 h-3" />
      <span>No Intervention</span>
    </span>
  );
};
