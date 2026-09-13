import {
  ActionsResponse,
  AuditEvent,
  BatchListItem,
  BatchRequestPayload,
  BatchSummary,
  CSVBatchResponse,
  DecisionExplanation,
  FullBatchResult,
  HealthResponse,
  ResourceLimits,
  StrategyMetric,
  StrategyName,
  VersionInfo,
} from '../types/api';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

class ApiError extends Error {
  status: number;
  data: any;

  constructor(message: string, status: number, data?: any) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${BASE_URL}${endpoint}`;
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> || {}),
  };

  // Don't set Content-Type for FormData — browser sets multipart/form-data with boundary
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 45000); // 45s timeout for ILP optimization

    const response = await fetch(url, {
      ...options,
      headers,
      signal: options.signal || controller.signal,
    });
    clearTimeout(timeoutId);

    if (!response.ok) {
      let errorMessage = `HTTP Error ${response.status}: ${response.statusText}`;
      let errorData: any = null;
      try {
        errorData = await response.json();
        if (errorData?.detail) {
          errorMessage = typeof errorData.detail === 'string' ? errorData.detail : JSON.stringify(errorData.detail);
        }
      } catch {
        // Response wasn't JSON
      }
      throw new ApiError(errorMessage, response.status, errorData);
    }

    return await response.json();
  } catch (error: any) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error.name === 'AbortError') {
      throw new ApiError('Request timed out after 45 seconds. The optimizer or server may be busy.', 408);
    }
    throw new ApiError(
      `Unable to connect to backend at ${BASE_URL}. Ensure the FastAPI server is running. (${error.message})`,
      0
    );
  }
}

export const api = {
  getHealth: () => request<HealthResponse>('/health'),

  getVersions: () => request<VersionInfo>('/versions'),

  getActions: () => request<ActionsResponse>('/recovery/actions'),

  deleteBatch: (batchId: string) =>
    request<{ deleted: string }>(`/recovery/batch/${encodeURIComponent(batchId)}`, {
      method: 'DELETE',
    }),

  getBatches: () => request<BatchListItem[]>('/recovery/batches'),

  getBatch: (batchId: string) => request<FullBatchResult>(`/recovery/batch/${encodeURIComponent(batchId)}`),

  runBatch: (payload: BatchRequestPayload) =>
    request<{ batch_id: string; summary: BatchSummary }>('/recovery/batch', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  compareStrategies: (payload: BatchRequestPayload) =>
    request<{
      batch_id: string;
      batch_seed: number;
      simulation: boolean;
      strategies: Record<StrategyName, StrategyMetric>;
    }>('/recovery/compare', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  runStrategy: (
    strategy: StrategyName,
    payload: { split?: string; batch_seed?: number; resource_limits?: any }
  ) =>
    request<{
      batch_id: string;
      strategy: string;
      plan: any[];
      metrics: StrategyMetric;
      execution: any[];
      verification: any;
      simulation: boolean;
    }>(`/recovery/strategy/${strategy}`, {
      method: 'POST',
      body: JSON.stringify({
        split: payload.split || 'demo',
        strategy,
        batch_seed: payload.batch_seed ?? 0,
        resource_limits: payload.resource_limits,
      }),
    }),

  executePlan: (payload: { split?: string; strategy?: StrategyName; batch_seed?: number; batch_id?: string; resource_limits?: any }) =>
    request<{
      batch_id: string;
      strategy: string;
      simulation: boolean;
      batch_metrics: StrategyMetric;
      executions: any[];
    }>('/recovery/execute', {
      method: 'POST',
      body: JSON.stringify({
        split: payload.split || 'demo',
        strategy: payload.strategy || 'rpa_optimizer',
        batch_seed: payload.batch_seed ?? 0,
        batch_id: payload.batch_id,
        resource_limits: payload.resource_limits,
      }),
    }),

  getPlan: (batchId: string) =>
    request<{ batch_id: string; status: string; plans: Record<string, any[]> }>(
      `/recovery/plan/${encodeURIComponent(batchId)}`
    ),

  getMetrics: (batchId: string) =>
    request<{ batch_id: string; status: string; verifications: Record<string, any> }>(
      `/recovery/metrics/${encodeURIComponent(batchId)}`
    ),

  getAuditTrail: (batchId: string) =>
    request<AuditEvent[]>(`/recovery/audit/${encodeURIComponent(batchId)}`),

  explainTransaction: (batchId: string, transactionId: string, strategy: StrategyName = 'rpa_optimizer') =>
    request<DecisionExplanation>(
      `/recovery/explain/${encodeURIComponent(batchId)}/${encodeURIComponent(transactionId)}?strategy=${encodeURIComponent(strategy)}`
    ),

  uploadCsvBatch: (
    file: File,
    params: { batch_seed?: number; resource_limits?: ResourceLimits; strategies?: string[] } = {}
  ) => {
    const url = new URL(`${BASE_URL}/recovery/batch/csv`);
    if (params.batch_seed !== undefined) url.searchParams.set('batch_seed', String(params.batch_seed));
    if (params.resource_limits) url.searchParams.set('resource_limits', JSON.stringify(params.resource_limits));
    if (params.strategies) url.searchParams.set('strategies', JSON.stringify(params.strategies));

    const formData = new FormData();
    formData.append('file', file);

    return request<CSVBatchResponse>(url.pathname + url.search, {
      method: 'POST',
      body: formData,
      headers: {},
    });
  },
};
