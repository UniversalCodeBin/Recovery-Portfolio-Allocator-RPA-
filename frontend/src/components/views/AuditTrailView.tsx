import React, { useState, useEffect } from 'react';
import {
  FileCheck2,
  Search,
  Filter,
  Download,
  ChevronDown,
  ChevronUp,
  Clock,
  Layers,
  Cpu,
  CheckCircle2,
} from 'lucide-react';
import { AuditEvent } from '../../types/api';
import { api } from '../../services/api';
import { LoadingSpinner } from '../common/LoadingSpinner';
import { StatusBadge } from '../common/StatusBadge';

interface Props {
  batchId: string | null;
}

export const AuditTrailView: React.FC<Props> = ({ batchId }) => {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [componentFilter, setComponentFilter] = useState('ALL');
  const [expandedEvents, setExpandedEvents] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!batchId) return;

    let mounted = true;
    setIsLoading(true);
    setError(null);

    api
      .getAuditTrail(batchId)
      .then((data) => {
        if (mounted) {
          setEvents(data);
          // Auto-expand first 2 events
          if (data.length > 0) {
            setExpandedEvents(new Set([data[0].audit_id, data[1]?.audit_id].filter(Boolean)));
          }
        }
      })
      .catch((err) => {
        if (mounted) {
          setError(err.message || 'Failed to fetch audit trail');
        }
      })
      .finally(() => {
        if (mounted) setIsLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [batchId]);

  const toggleExpand = (auditId: string) => {
    setExpandedEvents((prev) => {
      const next = new Set(prev);
      if (next.has(auditId)) {
        next.delete(auditId);
      } else {
        next.add(auditId);
      }
      return next;
    });
  };

  const filteredEvents = events.filter((ev) => {
    if (componentFilter !== 'ALL' && ev.component !== componentFilter) {
      return false;
    }
    if (search) {
      const s = search.toLowerCase();
      const matchId = ev.audit_id.toLowerCase().includes(s);
      const matchType = ev.event_type.toLowerCase().includes(s);
      const matchEntity = (ev.entity_id || '').toLowerCase().includes(s);
      return matchId || matchType || matchEntity;
    }
    return true;
  });

  const handleExportJSON = () => {
    const blob = new Blob([JSON.stringify(events, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `rpa_audit_${batchId || 'trail'}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (!batchId) {
    return <div className="p-8 text-center text-slate-400">No active batch loaded.</div>;
  }

  if (isLoading) {
    return <LoadingSpinner message="Retrieving append-only audit trail from backend..." />;
  }

  if (error) {
    return (
      <div className="p-6 bg-rose-950/40 border border-rose-500/40 rounded-xl text-rose-300 text-sm">
        <p className="font-semibold mb-1">Failed to load audit trail</p>
        <p className="text-xs text-rose-400">{error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-bold text-white flex items-center gap-2">
            <FileCheck2 className="w-5 h-5 text-blue-400" />
            Append-Only Audit Trail
          </h2>
          <p className="text-xs text-slate-400 mt-1 font-mono">
            Batch ID: <strong className="text-slate-200">{batchId}</strong> • Logged events:{' '}
            <strong className="text-blue-400">{events.length}</strong>
          </p>
        </div>

        <button
          onClick={handleExportJSON}
          className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-medium transition-colors"
        >
          <Download className="w-3.5 h-3.5 text-blue-400" />
          <span>Export Audit JSON</span>
        </button>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row items-center gap-3 text-xs">
        <div className="relative flex-1 w-full">
          <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-2.5" />
          <input
            type="text"
            placeholder="Search by Audit ID or Event Type..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-slate-900 border border-slate-800 rounded-lg pl-9 pr-3 py-2 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 font-mono"
          />
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto">
          <Filter className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          <select
            value={componentFilter}
            onChange={(e) => setComponentFilter(e.target.value)}
            className="w-full sm:w-auto bg-slate-900 border border-slate-800 text-slate-300 rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 font-mono"
          >
            <option value="ALL">All Components</option>
            <option value="batch">batch</option>
            <option value="prediction">prediction</option>
            <option value="ev">ev</option>
            <option value="policy">policy</option>
            <option value="optimizer">optimizer</option>
            <option value="execution">execution</option>
            <option value="verification">verification</option>
          </select>
        </div>
      </div>

      {/* Audit Timeline / Event Cards */}
      <div className="space-y-3">
        {filteredEvents.length === 0 ? (
          <div className="p-8 text-center text-slate-500 font-mono text-xs bg-slate-900 border border-slate-800 rounded-xl">
            No audit events matched the filter.
          </div>
        ) : (
          filteredEvents.map((ev, idx) => {
            const isExpanded = expandedEvents.has(ev.audit_id);
            return (
              <div
                key={ev.audit_id || idx}
                className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm transition-all"
              >
                <div
                  onClick={() => toggleExpand(ev.audit_id)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      toggleExpand(ev.audit_id);
                    }
                  }}
                  role="button"
                  tabIndex={0}
                  aria-expanded={isExpanded}
                  aria-label={`Toggle audit event ${ev.event_type}`}
                  className="p-4 flex items-center justify-between cursor-pointer hover:bg-slate-800/50 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <span className="w-6 h-6 rounded-full bg-blue-500/10 border border-blue-500/30 text-blue-400 text-xs font-mono flex items-center justify-center font-bold shrink-0">
                      {idx + 1}
                    </span>
                    <div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-bold text-white font-mono text-xs">
                          {ev.event_type}
                        </span>
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700 uppercase">
                          {ev.component}
                        </span>
                        {ev.entity_id && (
                          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-blue-500/10 text-blue-400">
                            entity: {ev.entity_id}
                          </span>
                        )}
                      </div>
                      <span className="text-[11px] text-slate-500 font-mono block mt-0.5">
                        ID: {ev.audit_id} • {ev.timestamp}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 text-slate-400">
                    <span className="text-[11px] font-mono hidden md:inline">
                      {Object.keys(ev.event_metadata || {}).length} fields
                    </span>
                    {isExpanded ? (
                      <ChevronUp className="w-4 h-4" />
                    ) : (
                      <ChevronDown className="w-4 h-4" />
                    )}
                  </div>
                </div>

                {isExpanded && (
                  <div className="p-4 bg-slate-950 border-t border-slate-800 text-xs font-mono overflow-x-auto max-h-96">
                    <pre className="text-slate-300 leading-relaxed">
                      {JSON.stringify(ev.event_metadata, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
