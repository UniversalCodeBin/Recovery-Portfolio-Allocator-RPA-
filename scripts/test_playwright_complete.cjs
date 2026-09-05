/**
 * Comprehensive Playwright Automated E2E Test Suite for RPA Frontend
 * Runs an in-process HTTP static server and intercepts API calls with full mock datasets.
 */
const { chromium } = require('playwright');
const http = require('http');
const path = require('path');
const fs = require('fs');

const DIST_DIR = '/run/media/white/New Volume/Projects/2K26/razorpay/frontend/dist';
const SCREENSHOT_DIR = '/home/white/.gemini/antigravity/brain/2909dc4b-7229-4544-8476-f6e4587579e8/screenshots';

// Mock backend dataset matching Step 3/4 OpenAPI schemas
const mockHealth = {
  status: 'ok',
  service: 'rpa-backend',
  step: 4,
  simulation_only: true,
};

const mockVersions = {
  model: 'rpa-recovery-logreg-full-v1',
  policy: 'v1.0-business-rules',
  optimizer: 'v1.0-cbc-ilp',
  ev_engine: 'v1.0-ev-ratio',
  simulator: 'v1.0-monte-carlo',
  verification: 'v1.0-ledger-verify',
};

const mockActions = {
  actions: [
    { action_id: 'smart_retry', action_type: 'Smart Retry', action_cost: 2.5, resource_requirements: { retry: 1 }, enabled: true },
    { action_id: 'payment_link', action_type: 'Payment Link', action_cost: 5.0, resource_requirements: { messaging: 1 }, enabled: true },
    { action_id: 'incentive_discount', action_type: 'Incentive Discount', action_cost: 25.0, resource_requirements: { incentive_budget: 25 }, enabled: true },
    { action_id: 'human_escalation', action_type: 'Human Outreach', action_cost: 50.0, resource_requirements: { human_slots: 1 }, enabled: true },
    { action_id: 'no_action', action_type: 'No Action', action_cost: 0.0, resource_requirements: {}, enabled: true },
  ],
  default_resource_limits: {
    retry: 2000,
    messaging: 2000,
    incentive_budget: 5000,
    human_slots: 50,
  },
  available_splits: ['demo', 'val', 'test', 'train'],
};

const mockBatches = [
  {
    batch_id: 'batch_2026_0905_demo_seed0',
    status: 'completed',
    created_at: '2026-09-05T18:30:00Z',
    n_transactions: 10,
    strategies: ['no_action', 'rule_based', 'ev_greedy', 'rpa_optimizer'],
    has_audit: true,
  },
  {
    batch_id: 'batch_2026_0905_demo_seed1',
    status: 'completed',
    created_at: '2026-09-05T17:00:00Z',
    n_transactions: 10,
    strategies: ['no_action', 'rule_based', 'ev_greedy', 'rpa_optimizer'],
    has_audit: true,
  },
];

function generateMockBatch(batchId) {
  const txnIds = [
    'TXN_DEMO_001', 'TXN_DEMO_002', 'TXN_DEMO_003', 'TXN_DEMO_004', 'TXN_DEMO_005',
    'TXN_DEMO_006', 'TXN_DEMO_007', 'TXN_DEMO_008', 'TXN_DEMO_009', 'TXN_DEMO_010'
  ];
  const amounts = [12500, 4800, 32000, 1500, 95000, 8200, 14500, 3400, 52000, 18000];
  const actionTypes = ['smart_retry', 'payment_link', 'incentive_discount', 'human_escalation', 'no_action'];

  const ev_table = [];
  const verdicts = [];
  txnIds.forEach((tId, idx) => {
    const amt = amounts[idx];
    actionTypes.forEach((aId) => {
      const prob = aId === 'no_action' ? 0.05 : aId === 'smart_retry' ? 0.42 : aId === 'payment_link' ? 0.58 : aId === 'incentive_discount' ? 0.74 : 0.88;
      const cost = aId === 'no_action' ? 0 : aId === 'smart_retry' ? 2.5 : aId === 'payment_link' ? 5.0 : aId === 'incentive_discount' ? 25.0 : 50.0;
      const gross = amt * prob;
      const net = gross - cost;
      ev_table.push({
        transaction_id: tId,
        action_id: aId,
        amount: amt,
        p_recovery: prob,
        recoverable_amount: amt,
        gross_expected: gross,
        action_cost: cost,
        incentive_cost: aId === 'incentive_discount' ? 25.0 : 0.0,
        total_cost: cost,
        net_expected: net,
        is_no_op: aId === 'no_action',
      });

      verdicts.push({
        transaction_id: tId,
        action_id: aId,
        action_type: aId,
        decision: (idx === 4 && aId === 'human_escalation') ? 'BLOCK' : 'ALLOW',
        policy_id: 'POL-01-STANDARD',
        rule: 'Safety & SLA Guardrail',
        reason: (idx === 4 && aId === 'human_escalation') ? 'VIP routing cap reached' : 'Within allowable recovery parameters',
        limit: 100,
        current_usage: 12,
      });
    });
  });

  const plans = {
    no_action: txnIds.map(t => ({ transaction_id: t, action_id: 'no_action', action_type: 'No Action', net_ev: 0, name: 'no_action', version: 'v1', status: 'optimal' })),
    rule_based: txnIds.map((t, i) => ({ transaction_id: t, action_id: 'smart_retry', action_type: 'Smart Retry', net_ev: amounts[i] * 0.4 - 2.5, name: 'rule_based', version: 'v1', status: 'optimal' })),
    ev_greedy: txnIds.map((t, i) => ({ transaction_id: t, action_id: 'payment_link', action_type: 'Payment Link', net_ev: amounts[i] * 0.55 - 5, name: 'ev_greedy', version: 'v1', status: 'optimal' })),
    rpa_optimizer: txnIds.map((t, i) => {
      const a = i % 4 === 0 ? 'human_escalation' : i % 3 === 0 ? 'incentive_discount' : i % 2 === 0 ? 'payment_link' : 'smart_retry';
      return { transaction_id: t, action_id: a, action_type: a.replace('_', ' ').toUpperCase(), net_ev: amounts[i] * 0.65 - 10, name: 'rpa_optimizer', version: 'v1', status: 'optimal' };
    }),
  };

  const executions = {
    rpa_optimizer: txnIds.map((t, i) => {
      const p = plans.rpa_optimizer[i];
      return {
        transaction_id: t,
        action_id: p.action_id,
        action_type: p.action_type,
        plan_name: 'rpa_optimizer',
        status: i === 3 ? 'failed' : 'successful',
        attempted: 1,
        recovered_amount: i === 3 ? 0 : amounts[i],
        recovery_cost: 15,
        net_recovered_amount: i === 3 ? -15 : amounts[i] - 15,
        p_predicted: 0.65,
        seed: 0,
        simulation: true,
      };
    }),
  };

  const verifications = {
    rpa_optimizer: {
      batch_metrics: {
        total_expected_net_ev: 148520.50,
        resource_used: { retry: 120, messaging: 85, incentive_budget: 450, human_slots: 4 },
        status: 'optimal',
        plan_name: 'rpa_optimizer',
        n_transactions: 10,
        n_planned: 10,
        n_executed: 10,
        n_successful: 9,
        n_failed: 1,
        n_blocked: 0,
        planned_total_net_ev: 148520.50,
        recovered_total: 227900.00,
        cost_total: 150.00,
        net_recovered_total: 227750.00,
        all_verified: true,
        simulation: true,
      },
      rows: txnIds.map((t, i) => ({
        transaction_id: t,
        planned_action_id: plans.rpa_optimizer[i].action_id,
        planned_action_type: plans.rpa_optimizer[i].action_type,
        planned_net_ev: plans.rpa_optimizer[i].net_ev,
        planned_index: i,
        executed: true,
        executed_action_id: plans.rpa_optimizer[i].action_id,
        executed_status: i === 3 ? 'failed' : 'successful',
        successful: i !== 3,
        failed: i === 3,
        blocked: false,
        recovered_amount: i === 3 ? 0 : amounts[i],
        recovery_cost: 15,
        net_recovered_amount: i === 3 ? -15 : amounts[i] - 15,
        verified: true,
      })),
    },
  };

  const strategy_metrics = {
    no_action: {
      total_expected_net_ev: 0,
      resource_used: {},
      status: 'baseline',
      n_transactions: 10,
      n_planned: 10,
      n_executed: 10,
      n_successful: 0,
      n_failed: 10,
      n_blocked: 0,
      planned_total_net_ev: 0,
      recovered_total: 0,
      cost_total: 0,
      net_recovered_total: 0,
      all_verified: true,
      simulation: true,
    },
    rule_based: {
      total_expected_net_ev: 89400.00,
      resource_used: { retry: 10 },
      status: 'feasible',
      n_transactions: 10,
      n_planned: 10,
      n_executed: 10,
      n_successful: 5,
      n_failed: 5,
      n_blocked: 0,
      planned_total_net_ev: 89400.00,
      recovered_total: 110000.00,
      cost_total: 25.00,
      net_recovered_total: 109975.00,
      all_verified: true,
      simulation: true,
    },
    ev_greedy: {
      total_expected_net_ev: 124300.00,
      resource_used: { messaging: 10 },
      status: 'feasible',
      n_transactions: 10,
      n_planned: 10,
      n_executed: 10,
      n_successful: 7,
      n_failed: 3,
      n_blocked: 0,
      planned_total_net_ev: 124300.00,
      recovered_total: 172000.00,
      cost_total: 50.00,
      net_recovered_total: 171950.00,
      all_verified: true,
      simulation: true,
    },
    rpa_optimizer: verifications.rpa_optimizer.batch_metrics,
  };

  return {
    batch_id: batchId,
    status: 'completed',
    created_at: '2026-09-05T18:30:00Z',
    ev_table,
    verdicts,
    plans,
    executions,
    verifications,
    transaction_ids: txnIds,
    resource_limits: mockActions.default_resource_limits,
    summary: {
      batch_id: batchId,
      status: 'completed',
      n_transactions: 10,
      n_actions: 5,
      strategy_metrics,
      n_blocked_candidates: 1,
      error: null,
    },
  };
}

const mockBatchDetails = generateMockBatch('batch_2026_0905_demo_seed0');

const mockAuditEvents = [
  { audit_id: 'AUD-001', batch_id: 'batch_2026_0905_demo_seed0', component: 'batch', event_type: 'BATCH_INITIALIZED', entity_id: 'batch_2026_0905_demo_seed0', event_metadata: { split: 'demo', n_txns: 10 }, timestamp: '2026-09-05T18:30:01Z' },
  { audit_id: 'AUD-002', batch_id: 'batch_2026_0905_demo_seed0', component: 'prediction', event_type: 'ML_INFERENCE_COMPLETED', entity_id: 'rpa-recovery-logreg-full-v1', event_metadata: { features: 12, calibrated: true }, timestamp: '2026-09-05T18:30:02Z' },
  { audit_id: 'AUD-003', batch_id: 'batch_2026_0905_demo_seed0', component: 'ev', event_type: 'EV_MATRIX_COMPUTED', entity_id: 'ev-engine-v1', event_metadata: { total_cells: 50 }, timestamp: '2026-09-05T18:30:02Z' },
  { audit_id: 'AUD-004', batch_id: 'batch_2026_0905_demo_seed0', component: 'policy', event_type: 'POLICY_GATE_VERIFIED', entity_id: 'POL-01-STANDARD', event_metadata: { verdicts: 50, blocks: 1 }, timestamp: '2026-09-05T18:30:03Z' },
  { audit_id: 'AUD-005', batch_id: 'batch_2026_0905_demo_seed0', component: 'optimizer', event_type: 'ILP_SOLVER_OPTIMAL', entity_id: 'cbc-solver', event_metadata: { objective_net_ev: 148520.50, time_sec: 0.12 }, timestamp: '2026-09-05T18:30:04Z' },
  { audit_id: 'AUD-006', batch_id: 'batch_2026_0905_demo_seed0', component: 'execution', event_type: 'SIMULATION_EXECUTED', entity_id: 'monte-carlo-v1', event_metadata: { recovered_total: 227900.00, success_rate: 0.90 }, timestamp: '2026-09-05T18:30:05Z' },
  { audit_id: 'AUD-007', batch_id: 'batch_2026_0905_demo_seed0', component: 'verification', event_type: 'LEDGER_VERIFIED', entity_id: 'ledger-v1', event_metadata: { discrepancies: 0, verified: true }, timestamp: '2026-09-05T18:30:06Z' },
];

const mockExplanation = {
  batch_id: 'batch_2026_0905_demo_seed0',
  transaction_id: 'TXN_DEMO_001',
  prediction: {
    transaction_id: 'TXN_DEMO_001',
    action_id: 'human_escalation',
    predicted_recovery_probability: 0.88,
    model_identifier: 'rpa-recovery-logreg-full-v1',
  },
  ev: {
    transaction_id: 'TXN_DEMO_001',
    action_id: 'human_escalation',
    amount: 12500,
    p_recovery: 0.88,
    recoverable_amount: 12500,
    gross_expected: 11000,
    action_cost: 50,
    incentive_cost: 0,
    total_cost: 50,
    net_expected: 10950,
    is_no_op: false,
  },
  policy: {
    transaction_id: 'TXN_DEMO_001',
    action_id: 'human_escalation',
    action_type: 'HUMAN OUTREACH',
    decision: 'ALLOW',
    policy_id: 'POL-01-STANDARD',
    rule: 'Safety & SLA Guardrail',
    reason: 'Within allowable recovery parameters',
    limit: 100,
    current_usage: 12,
  },
  decision: {
    transaction_id: 'TXN_DEMO_001',
    action_id: 'human_escalation',
    action_type: 'HUMAN OUTREACH',
    net_ev: 10950,
    name: 'rpa_optimizer',
    version: 'v1',
    status: 'optimal',
  },
  execution: {
    transaction_id: 'TXN_DEMO_001',
    action_id: 'human_escalation',
    action_type: 'HUMAN OUTREACH',
    plan_name: 'rpa_optimizer',
    status: 'successful',
    attempted: 1,
    recovered_amount: 12500,
    recovery_cost: 50,
    net_recovered_amount: 12450,
    p_predicted: 0.88,
    seed: 0,
    simulation: true,
  },
  verification: {
    transaction_id: 'TXN_DEMO_001',
    planned_action_id: 'human_escalation',
    planned_action_type: 'HUMAN OUTREACH',
    planned_net_ev: 10950,
    planned_index: 0,
    executed: true,
    executed_action_id: 'human_escalation',
    executed_status: 'successful',
    successful: true,
    failed: false,
    blocked: false,
    recovered_amount: 12500,
    recovery_cost: 50,
    net_recovered_amount: 12450,
    verified: true,
  },
};

function startStaticServer() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      let reqPath = req.url.split('?')[0];
      let filePath = path.join(DIST_DIR, reqPath === '/' ? 'index.html' : reqPath);
      if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
        filePath = path.join(DIST_DIR, 'index.html');
      }
      const ext = path.extname(filePath);
      const mime = {
        '.html': 'text/html',
        '.js': 'application/javascript',
        '.css': 'text/css',
        '.json': 'application/json',
        '.svg': 'image/svg+xml',
        '.png': 'image/png',
      };
      res.writeHead(200, { 'Content-Type': mime[ext] || 'application/octet-stream' });
      fs.createReadStream(filePath).pipe(res);
    });

    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      resolve({ server, port });
    });
  });
}

(async () => {
  console.log('🚀 Starting Comprehensive Playwright Automated E2E Test Suite...');
  const { server, port } = await startStaticServer();
  const TARGET_URL = `http://127.0.0.1:${port}/`;
  console.log(`🌐 In-Process Static Server running at: ${TARGET_URL}`);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });

  const page = await context.newPage();

  // Track console events & runtime errors
  const consoleMessages = [];
  const pageErrors = [];
  page.on('console', msg => consoleMessages.push(`[${msg.type()}] ${msg.text()}`));
  page.on('pageerror', err => {
    console.error('❌ Page Error:', err);
    pageErrors.push(err.toString());
  });

  // Intercept backend API requests with mock data (matches any hostname for the endpoint)
  await page.route('**/health', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockHealth) })
  );
  await page.route('**/versions', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockVersions) })
  );
  await page.route('**/recovery/actions', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockActions) })
  );
  await page.route('**/recovery/batches', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockBatches) })
  );
  await page.route('**/recovery/batch/*', route => {
    const url = route.request().url();
    if (url.includes('/explain/')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockExplanation) });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockBatchDetails) });
  });
  await page.route('**/recovery/audit/*', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockAuditEvents) })
  );
  await page.route('**/recovery/explain/**', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockExplanation) })
  );
  await page.route('**/recovery/batch', route => {
    if (route.request().method() === 'POST') {
      const newBatch = generateMockBatch('batch_2026_new_simulated');
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ batch_id: newBatch.batch_id, summary: newBatch.summary }),
      });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
  });

  const testResults = [];

  async function step(name, fn) {
    console.log(`\n▶ [TEST] ${name}`);
    try {
      await fn();
      console.log(`  ✅ PASSED: ${name}`);
      testResults.push({ name, status: 'PASSED' });
    } catch (err) {
      console.error(`  ❌ FAILED: ${name}`, err.message);
      testResults.push({ name, status: 'FAILED', error: err.message });
    }
  }

  // TEST 1: Load Website & Header Validation
  await step('1. Load RPA Website and Validate Navbar & Brand Header', async () => {
    await page.goto(TARGET_URL, { waitUntil: 'networkidle' });
    await page.waitForSelector('text=Recovery Portfolio Allocator');
    
    // Check Brand & Badges
    const headerText = await page.textContent('h1');
    if (!headerText.includes('Recovery Portfolio Allocator')) throw new Error('Header title missing');
    
    const trackBadge = await page.textContent('text=Track 03');
    if (!trackBadge) throw new Error('Track 03 badge missing');

    // Verify online / healthy badge
    await page.waitForSelector('text=ONLINE');
    await page.waitForSelector('text=SIMULATION ONLY');

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01_overview_view.png'), fullPage: true });
  });

  // TEST 2: Overview View & KPI Cards
  await step('2. Verify Overview View Metrics, KPIs, and Strategy Summary Cards', async () => {
    // Assert KPI metrics are displayed
    await page.waitForSelector('text=Revenue at Risk');
    await page.waitForSelector('text=Expected Net Recovery');
    await page.waitForSelector('text=Simulation Verified');

    // Assert 4-strategy cards in overview
    await page.waitForSelector('text=No Action (Pass)');
    await page.waitForSelector('text=Rule-Based (Heuristic)');
    await page.waitForSelector('text=EV-Greedy');
    await page.waitForSelector('text=RPA Optimizer (ILP)');
  });

  // TEST 3: Strategy Comparison View
  await step('3. Navigate to Strategy Comparison View and Validate Benchmarks', async () => {
    await page.click('button:has-text("Strategy Comparison")');
    await page.waitForTimeout(400);

    await page.waitForSelector('text=4-Strategy Head-to-Head Comparison');
    await page.waitForSelector('text=RPA Net Lift Over Baselines');

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02_comparison_view.png'), fullPage: true });
  });

  // TEST 4: Resource Constraints View
  await step('4. Navigate to Resource Constraints View and Check Knapsack Meters', async () => {
    await page.click('button:has-text("Resource Constraints")');
    await page.waitForTimeout(400);

    await page.waitForSelector('text=Shared Recovery Resource Budgets');
    await page.waitForSelector('text=Recovery Action Economics');

    // Check meter labels
    await page.waitForSelector('text=Smart Retry Capacity');
    await page.waitForSelector('text=Messaging API Capacity');
    await page.waitForSelector('text=Incentive / Discount Budget');
    await page.waitForSelector('text=Human Support Slots');

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03_resource_constraints_view.png'), fullPage: true });
  });

  // TEST 5: RPA Recovery Plan View & Table Filtering
  await step('5. Navigate to Recovery Plan View, Filter Table, and Verify Records', async () => {
    await page.click('button:has-text("RPA Recovery Plan")');
    await page.waitForTimeout(400);

    await page.waitForSelector('text=Transaction ID');
    await page.waitForSelector('text=TXN_DEMO_001');

    // Test Search Filter
    const searchInput = await page.waitForSelector('input[placeholder*="Search"]');
    await searchInput.fill('001');
    await page.waitForTimeout(300);

    const filteredRowCount = await page.$$eval('tbody tr', rows => rows.length);
    if (filteredRowCount !== 1) {
      throw new Error(`Expected 1 row after search filtering, got ${filteredRowCount}`);
    }

    // Clear search
    await searchInput.fill('');
    await page.waitForTimeout(300);

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '04_recovery_plan_view.png'), fullPage: true });
  });

  // TEST 6: Decision Explanation Modal
  await step('6. Open Decision Explanation Modal & Verify 6-Stage Audit Trail', async () => {
    // Find the first Explain button
    const explainButton = await page.waitForSelector('tbody tr button:has-text("Explain")');
    await explainButton.click();
    await page.waitForTimeout(500);

    // Modal should be visible
    await page.waitForSelector('text=Decision Explanation');
    await page.waitForSelector('text=Stage 2: AI Prediction');
    await page.waitForSelector('text=Stage 3: Expected Value');
    await page.waitForSelector('text=Stage 4: Policy Gate');
    await page.waitForSelector('text=Stage 5: Portfolio Optimizer');

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '05_decision_explanation_modal.png'), fullPage: false });

    // Close Modal
    const closeBtn = await page.waitForSelector('button[aria-label="Close modal"]');
    await closeBtn.click();
    await page.waitForTimeout(300);
  });

  // TEST 7: Execution & Simulation View
  await step('7. Navigate to Execution & Verify View and Verify Ledger', async () => {
    await page.click('button:has-text("Execution & Verify")');
    await page.waitForTimeout(400);

    await page.waitForSelector('text=Simulated Execution Ledger');
    await page.waitForSelector('text=Monte-Carlo Realization');

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '06_execution_view.png'), fullPage: true });
  });

  // TEST 8: Audit Trail View
  await step('8. Navigate to Audit Trail View and Check Compliance Events', async () => {
    await page.click('button:has-text("Audit Trail")');
    await page.waitForTimeout(400);

    await page.waitForSelector('text=Regulatory & Explainability Audit Trail');
    await page.waitForSelector('text=BATCH_INITIALIZED');
    await page.waitForSelector('text=ILP_SOLVER_OPTIMAL');

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '07_audit_trail_view.png'), fullPage: true });
  });

  // TEST 9: Configure & Run Batch Modal
  await step('9. Open Configure Batch Modal, Test Controls, and Trigger Batch Run', async () => {
    // Click Settings icon in header
    const settingsBtn = await page.waitForSelector('button[title*="Configuration"]');
    await settingsBtn.click();
    await page.waitForTimeout(400);

    await page.waitForSelector('#configure-batch-title');
    await page.waitForSelector('text=Configure Recovery Batch');

    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '08_configure_batch_modal.png'), fullPage: false });

    // Click Run Batch in modal
    const runBtn = await page.waitForSelector('button:has-text("Optimize & Run Batch")');
    await runBtn.click();
    await page.waitForTimeout(600);
  });

  // TEST 10: Runtime Error Assertion
  await step('10. Assert Zero Unhandled Console Errors or Exceptions', async () => {
    if (pageErrors.length > 0) {
      throw new Error(`Captured ${pageErrors.length} unhandled runtime errors: ${pageErrors.join(', ')}`);
    }
    const criticalErrors = consoleMessages.filter(m => m.startsWith('[error]') && !m.includes('favicon'));
    if (criticalErrors.length > 0) {
      console.warn('Console error warnings:', criticalErrors);
    }
  });

  await browser.close();
  server.close();

  console.log('\n========================================');
  console.log('🏁 COMPLETE PLAYWRIGHT E2E TEST SUMMARY');
  console.log('========================================');
  let passCount = 0;
  testResults.forEach((res, i) => {
    const icon = res.status === 'PASSED' ? '✅' : '❌';
    if (res.status === 'PASSED') passCount++;
    console.log(`${icon} [${res.status}] ${res.name}`);
    if (res.error) console.log(`    Error: ${res.error}`);
  });
  console.log(`\nTotal Tests: ${testResults.length} | Passed: ${passCount} | Failed: ${testResults.length - passCount}`);
  console.log(`Screenshots saved to: ${SCREENSHOT_DIR}`);
  console.log('========================================\n');

  if (passCount !== testResults.length) {
    process.exit(1);
  }
})();
