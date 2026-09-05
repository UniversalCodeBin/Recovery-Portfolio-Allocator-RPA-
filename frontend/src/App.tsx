import React, { useState, useEffect, useCallback } from 'react';
import {
  ActionSpec,
  BatchListItem,
  BatchRequestPayload,
  FullBatchResult,
  HealthResponse,
  ResourceLimits,
  StrategyName,
  VersionInfo,
} from './types/api';
import { api } from './services/api';
import { Navbar } from './components/common/Navbar';
import { Sidebar, ActiveTab } from './components/common/Sidebar';
import { ErrorBanner } from './components/common/ErrorBanner';
import { LoadingSpinner } from './components/common/LoadingSpinner';
import { OverviewView } from './components/views/OverviewView';
import { ComparisonView } from './components/views/ComparisonView';
import { ResourceConstraintsView } from './components/views/ResourceConstraintsView';
import { RecoveryPlanView } from './components/views/RecoveryPlanView';
import { ExecutionView } from './components/views/ExecutionView';
import { AuditTrailView } from './components/views/AuditTrailView';
import { DecisionExplanationModal } from './components/modals/DecisionExplanationModal';
import { ConfigureBatchModal } from './components/modals/ConfigureBatchModal';

export const App: React.FC = () => {
  // Global System State
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [versions, setVersions] = useState<VersionInfo | null>(null);
  const [actions, setActions] = useState<ActionSpec[]>([]);
  const [defaultLimits, setDefaultLimits] = useState<ResourceLimits>({
    retry: 2000,
    messaging: 2000,
    incentive_budget: 5000,
    human_slots: 50,
  });
  const [availableSplits, setAvailableSplits] = useState<string[]>(['demo', 'val', 'test', 'train']);

  // Batch & Data State
  const [batches, setBatches] = useState<BatchListItem[]>([]);
  const [currentBatchId, setCurrentBatchId] = useState<string | null>(null);
  const [currentBatch, setCurrentBatch] = useState<FullBatchResult | null>(null);

  // UI State
  const [activeTab, setActiveTab] = useState<ActiveTab>('overview');
  const [isLoading, setIsLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  // Modals
  const [isConfigModalOpen, setIsConfigModalOpen] = useState(false);
  const [explainingTxn, setExplainingTxn] = useState<{ txnId: string; strategy: StrategyName } | null>(null);

  // 1. Initial System Check & Batch List
  useEffect(() => {
    let mounted = true;

    async function init() {
      try {
        const [h, v, acts, batchList] = await Promise.allSettled([
          api.getHealth(),
          api.getVersions(),
          api.getActions(),
          api.getBatches(),
        ]);

        if (!mounted) return;

        if (h.status === 'fulfilled') setHealth(h.value);
        if (v.status === 'fulfilled') setVersions(v.value);
        if (acts.status === 'fulfilled') {
          setActions(acts.value.actions);
          if (acts.value.default_resource_limits) setDefaultLimits(acts.value.default_resource_limits);
          if (acts.value.available_splits) setAvailableSplits(acts.value.available_splits);
        }
        if (batchList.status === 'fulfilled' && batchList.value.length > 0) {
          setBatches(batchList.value);
          // Prefer demo batch or first batch
          const demoBatch = batchList.value.find((b) => b.n_transactions === 370) || batchList.value[0];
          if (demoBatch) {
            loadBatchById(demoBatch.batch_id);
          }
        }
      } catch (err: any) {
        if (mounted) setError(err.message || 'System initialization failed');
      }
    }

    init();

    return () => {
      mounted = false;
    };
  }, []);

  // 2. Load Batch by ID
  const loadBatchById = useCallback(async (batchId: string) => {
    setIsLoading(true);
    setLoadingMessage(`Loading recovery batch ${batchId}...`);
    setError(null);
    try {
      const data = await api.getBatch(batchId);
      setCurrentBatchId(batchId);
      setCurrentBatch(data);
    } catch (err: any) {
      setError(`Failed to load batch ${batchId}: ${err.message}`);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // 3. Load / Run Demo Batch
  const handleLoadDemo = useCallback(async () => {
    // Check if demo batch exists in batches list
    const existingDemo = batches.find((b) => b.n_transactions === 370);
    if (existingDemo) {
      await loadBatchById(existingDemo.batch_id);
      return;
    }

    // Otherwise run a demo batch
    setIsLoading(true);
    setLoadingMessage('Executing full demo recovery batch (370 transactions, all 4 strategies)...');
    setError(null);
    try {
      const res = await api.runBatch({
        split: 'demo',
        batch_seed: 0,
        strategies: ['no_action', 'rule_based', 'ev_greedy', 'rpa_optimizer'],
      });
      // Refresh batch list
      const freshList = await api.getBatches();
      setBatches(freshList);
      await loadBatchById(res.batch_id);
    } catch (err: any) {
      setError(`Demo batch execution failed: ${err.message}`);
    } finally {
      setIsLoading(false);
    }
  }, [batches, loadBatchById]);

  // 4. Run Custom Configured Batch
  const handleRunConfiguredBatch = async (payload: BatchRequestPayload) => {
    setIsConfigModalOpen(false);
    setIsLoading(true);
    setLoadingMessage(`Running exact ILP portfolio optimization on split '${payload.split || 'demo'}'...`);
    setError(null);
    try {
      const res = await api.runBatch(payload);
      const freshList = await api.getBatches();
      setBatches(freshList);
      await loadBatchById(res.batch_id);
      setActiveTab('overview');
    } catch (err: any) {
      setError(`Batch execution error: ${err.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  // 5. Re-run Comparison
  const handleRunComparison = async (seed: number) => {
    if (!currentBatchId) return;
    setIsLoading(true);
    setLoadingMessage(`Re-running fair strategy comparison with seed ${seed}...`);
    setError(null);
    try {
      const res = await api.compareStrategies({
        split: 'demo',
        batch_seed: seed,
      });
      // Refresh current batch data
      const updated = await api.getBatch(res.batch_id);
      setCurrentBatch(updated);
      const freshList = await api.getBatches();
      setBatches(freshList);
    } catch (err: any) {
      setError(`Strategy comparison failed: ${err.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  // 6. Execute Simulation
  const handleExecute = async (strategy: StrategyName, seed: number) => {
    if (!currentBatchId) return;
    setIsLoading(true);
    setLoadingMessage(`Executing seeded Monte-Carlo simulation for strategy '${strategy}'...`);
    setError(null);
    try {
      const res = await api.executePlan({
        split: 'demo',
        strategy,
        batch_seed: seed,
      });
      const updated = await api.getBatch(res.batch_id);
      setCurrentBatch(updated);
      const freshList = await api.getBatches();
      setBatches(freshList);
    } catch (err: any) {
      setError(`Simulation execution failed: ${err.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Navigation */}
      <Navbar
        health={health}
        versions={versions}
        batches={batches}
        currentBatchId={currentBatchId}
        onSelectBatch={loadBatchById}
        onOpenConfigModal={() => setIsConfigModalOpen(true)}
        onLoadDemo={handleLoadDemo}
        isLoading={isLoading}
      />

      {/* Main Container */}
      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar */}
        <Sidebar
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          hasBatch={!!currentBatch}
        />

        {/* Content Area */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8 space-y-6">
          {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

          {isLoading && <LoadingSpinner message={loadingMessage} />}

          {!isLoading && (
            <>
              {activeTab === 'overview' && (
                <OverviewView
                  batch={currentBatch}
                  onNavigate={setActiveTab}
                  onLoadDemo={handleLoadDemo}
                  isLoading={isLoading}
                />
              )}

              {activeTab === 'comparison' && (
                <ComparisonView
                  batch={currentBatch}
                  onRunComparison={handleRunComparison}
                  isLoading={isLoading}
                />
              )}

              {activeTab === 'resources' && (
                <ResourceConstraintsView batch={currentBatch} />
              )}

              {activeTab === 'plan' && (
                <RecoveryPlanView
                  batch={currentBatch}
                  onExplainTransaction={(txnId, strat) =>
                    setExplainingTxn({ txnId, strategy: strat })
                  }
                />
              )}

              {activeTab === 'execution' && (
                <ExecutionView
                  batch={currentBatch}
                  onExecute={handleExecute}
                  isLoading={isLoading}
                />
              )}

              {activeTab === 'audit' && (
                <AuditTrailView batchId={currentBatchId} />
              )}
            </>
          )}
        </main>
      </div>

      {/* Decision Explanation Modal */}
      {explainingTxn && currentBatchId && (
        <DecisionExplanationModal
          batchId={currentBatchId}
          transactionId={explainingTxn.txnId}
          strategy={explainingTxn.strategy}
          onClose={() => setExplainingTxn(null)}
        />
      )}

      {/* Configure Batch Modal */}
      <ConfigureBatchModal
        isOpen={isConfigModalOpen}
        onClose={() => setIsConfigModalOpen(false)}
        onSubmit={handleRunConfiguredBatch}
        isLoading={isLoading}
        defaultLimits={defaultLimits}
        availableSplits={availableSplits}
      />
    </div>
  );
};

export default App;
