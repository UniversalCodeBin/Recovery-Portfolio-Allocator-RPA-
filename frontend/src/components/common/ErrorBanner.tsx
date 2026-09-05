import React from 'react';
import { AlertCircle, X } from 'lucide-react';

interface Props {
  message: string;
  onDismiss?: () => void;
}

export const ErrorBanner: React.FC<Props> = ({ message, onDismiss }) => {
  return (
    <div className="bg-rose-950/40 border border-rose-500/40 text-rose-300 rounded-lg p-3.5 flex items-start justify-between gap-3 text-sm animate-in fade-in">
      <div className="flex items-start gap-2.5">
        <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
        <div>
          <span className="font-semibold block text-rose-200">System Error</span>
          <p className="text-xs text-rose-300/80 mt-0.5">{message}</p>
        </div>
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="text-rose-400 hover:text-rose-200 p-1 rounded hover:bg-rose-500/10 transition-colors"
          aria-label="Dismiss error"
        >
          <X className="w-4 h-4" />
        </button>
      )}
    </div>
  );
};
