import React from 'react';
import { Loader2 } from 'lucide-react';

interface Props {
  message?: string;
  size?: 'sm' | 'md' | 'lg';
}

export const LoadingSpinner: React.FC<Props> = ({ message = 'Processing...', size = 'md' }) => {
  const iconSize = {
    sm: 'w-4 h-4',
    md: 'w-6 h-6',
    lg: 'w-10 h-10',
  }[size];

  return (
    <div className="flex flex-col items-center justify-center p-8 text-center space-y-3">
      <Loader2 className={`${iconSize} animate-spin text-blue-500`} />
      <span className="text-sm text-slate-400 font-medium">{message}</span>
    </div>
  );
};
