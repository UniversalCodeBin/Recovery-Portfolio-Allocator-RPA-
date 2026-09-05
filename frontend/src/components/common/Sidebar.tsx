import React from 'react';
import {
  LayoutDashboard,
  GitCompare,
  Sliders,
  FileSpreadsheet,
  PlayCircle,
  FileCheck2,
  ArrowRight,
  TrendingUp,
  Cpu,
} from 'lucide-react';

export type ActiveTab = 'overview' | 'comparison' | 'resources' | 'plan' | 'execution' | 'audit';

interface Props {
  activeTab: ActiveTab;
  setActiveTab: (tab: ActiveTab) => void;
  hasBatch: boolean;
}

export const Sidebar: React.FC<Props> = ({ activeTab, setActiveTab, hasBatch }) => {
  const navItems = [
    {
      id: 'overview' as ActiveTab,
      label: 'Overview & Metrics',
      icon: <LayoutDashboard className="w-4 h-4" />,
      tag: 'Core',
    },
    {
      id: 'comparison' as ActiveTab,
      label: 'Strategy Comparison',
      icon: <GitCompare className="w-4 h-4" />,
      tag: '4 Strategies',
    },
    {
      id: 'resources' as ActiveTab,
      label: 'Resource Constraints',
      icon: <Sliders className="w-4 h-4" />,
      tag: 'ILP Budgets',
    },
    {
      id: 'plan' as ActiveTab,
      label: 'RPA Recovery Plan',
      icon: <FileSpreadsheet className="w-4 h-4" />,
      tag: 'Decisions',
    },
    {
      id: 'execution' as ActiveTab,
      label: 'Execution & Verify',
      icon: <PlayCircle className="w-4 h-4" />,
      tag: 'Simulation',
    },
    {
      id: 'audit' as ActiveTab,
      label: 'Audit Trail',
      icon: <FileCheck2 className="w-4 h-4" />,
      tag: 'Explainable',
    },
  ];

  return (
    <aside className="w-64 bg-slate-900/95 border-r border-slate-800 flex flex-col justify-between shrink-0 select-none">
      {/* Navigation list */}
      <div className="p-3 space-y-1">
        <div className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">
          Navigation
        </div>
        {navItems.map((item) => {
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                isActive
                  ? 'bg-blue-600 text-white shadow-sm shadow-blue-500/30'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
              }`}
            >
              <div className="flex items-center gap-2.5">
                <span className={isActive ? 'text-white' : 'text-slate-400'}>{item.icon}</span>
                <span>{item.label}</span>
              </div>
              <span
                className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                  isActive
                    ? 'bg-white/20 text-white'
                    : 'bg-slate-800 text-slate-400'
                }`}
              >
                {item.tag}
              </span>
            </button>
          );
        })}
      </div>

      {/* 30-Second Recovery Pipeline Concept */}
      <div className="p-3 m-3 bg-slate-950/60 border border-slate-800/80 rounded-xl space-y-2">
        <div className="flex items-center justify-between text-[11px] font-semibold text-slate-300">
          <span className="flex items-center gap-1.5 text-blue-400">
            <Cpu className="w-3.5 h-3.5" /> Recovery Flow
          </span>
          <span className="text-[10px] text-slate-500">30s Logic</span>
        </div>
        <div className="space-y-1 text-[10px] font-mono text-slate-400 leading-tight">
          <div className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
            <span>Revenue at Risk</span>
          </div>
          <div className="text-slate-600 pl-2 text-[9px]">↓ ML Model Predictions</div>
          <div className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
            <span>Expected Value Engine</span>
          </div>
          <div className="text-slate-600 pl-2 text-[9px]">↓ Hard Policy Gates</div>
          <div className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
            <span>Exact ILP Optimizer</span>
          </div>
          <div className="text-slate-600 pl-2 text-[9px]">↓ Seeded Monte-Carlo</div>
          <div className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            <span>Reconciled Audit Trail</span>
          </div>
        </div>
      </div>
    </aside>
  );
};
