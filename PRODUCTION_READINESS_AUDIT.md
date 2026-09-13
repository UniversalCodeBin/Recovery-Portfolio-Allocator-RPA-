# Production Readiness Audit

Audit date: 2026-09-11. Scope: complete checked-in repository, including the
FastAPI service, React dashboard, data/ML pipeline, database migrations,
tests, configuration, and deployment assets. This was a read-only audit; no
application code was changed before this document was created.

## Architecture observed

The product retains a clear prototype decision flow: `PredictionService`
(frozen Logistic Regression) → `EVEngine` → seven-gate `PolicyEngine` → exact
OR-Tools CBC `Optimizer` (with EV-greedy baseline) → deterministic
`ExecutionSimulator` → `VerificationLayer` → `AuditTrail`. The FastAPI API
invokes this flow synchronously. React/Vite consumes it directly. Synthetic
CSV data and artifacts are the normal input. PostgreSQL DDL exists, but the
runtime source of truth is `rpa_runs/<batch_id>/*.json`; DB writes are
best-effort and silently skipped.

## Findings

| Priority | Current behavior | Production risk | Recommended solution | Files affected | Implementation priority |
|---|---|---|---|---|---|
| CRITICAL | All API endpoints are unauthenticated and unauthorised. | Anyone with network access can read decisions/audits or trigger work. | Add server-side JWT authentication, revocation, RBAC, and default-deny route dependencies. | `rpa/api.py`, new auth modules/tests, frontend | P0 |
| CRITICAL | No merchant/tenant fields or query scoping exist. | Cross-merchant data disclosure and action execution are possible. | Add tenant-owned schema, claims, FK/index constraints and tenant-scoped repositories. | migrations, DB/repository/API/tests | P0 |
| CRITICAL | Runtime persistence is JSON; `_persist` suppresses errors. PostgreSQL is optional and failures print then continue. | Lost/non-atomic decisions, untrustworthy audit history, races and unsafe recovery after restart. | Make PostgreSQL mandatory in production, use a pool and atomic transactions; retain JSON only for explicit demo mode. | `rpa/db.py`, `data_core/db.py`, orchestrator/API, migrations | P0 |
| CRITICAL | `/recovery/execute` creates and executes a new simulated plan on every request, with no idempotency key/state machine. | Retried requests could duplicate real recovery action after an integration is introduced. | Persist executions, enforce idempotency/unique keys, and validate durable state transitions. | API, execution service, migrations/tests | P0 |
| CRITICAL | Resource limits are in request/default memory and have no reservation or row locks. | Concurrent batches can exceed retry, messaging, incentive or human limits. | Atomically reserve/release resources under tenant/batch rows with `FOR UPDATE`; fail closed. | migrations, resource repository/service/tests | P0 |
| CRITICAL | Production/demo mode is not a safety boundary; simulator is embedded in orchestration. | A future provider can be accidentally wired into a demo workflow. | Explicit validated `RPA_MODE`; provider interfaces; production must refuse simulator and require integration configuration. | config, orchestration, execution/provider modules | P0 |
| HIGH | API is unversioned; uses `Dict`, leaks exception strings, has no request limits, pagination, error envelope or request/correlation ID. | Contract instability, information leakage, resource abuse, weak incident investigation. | Create `/api/v1`, strict models, exception middleware, request IDs, bounded payloads/pagination and safe errors. | `rpa/api.py`, frontend client/tests | P1 |
| HIGH | HTTP requests synchronously score, solve and simulate batches. | Worker starvation/timeouts and client retry amplification. | Create persistent jobs and worker processing with status/progress/retry; API returns 202. | new jobs/worker modules, migrations, frontend/tests | P1 |
| HIGH | No payment-provider/webhook integration boundary or signature/replay protection. | Unsafe future integration and forged/replayed events. | Define provider/executor/outcome interfaces; persist deduplicated signed webhook events. Mark Razorpay adapter READY FOR INTEGRATION only. | new integration modules/API/migrations/tests | P1 |
| HIGH | Policy version is a constant; configs are mutable process defaults; executed decisions do not snapshot policy. | Historical decisions cannot be reliably reconstructed after policy change. | Version immutable policy snapshots and reference their IDs from decisions/executions. | policy/config/migrations/audit/tests | P1 |
| HIGH | CBC treats `FEASIBLE` timeout result as a selectable plan; no solver result metadata/fallback policy. | An incomplete/non-approved solve could be actioned. | Persist solver status/objective/bound/latency; default fail closed on timeout unless an explicit approved fallback policy exists. | optimizer/orchestrator/migrations/tests | P1 |
| HIGH | Model artifact loading has no digest/integrity enforcement; prediction persistence is optional and metadata omits dataset/calibration lineage. | Untraceable or tampered model inference. | Register immutable model metadata, hashes, feature/preprocessing/calibration/training data versions; validate before inference. | `ml/*`, prediction service, migrations/tests | P1 |
| HIGH | Logs use `print`; no structured logging, metrics or tracing. | PII leakage and inability to operate/investigate production failures. | JSON logging with redaction, metrics endpoint/instrumentation and propagated correlation IDs. | all backend services/config/tests | P1 |
| HIGH | Audit JSON is mutable/deletable; actor/tenant/correlation/version fields are incomplete. | Audit record is not trustworthy for compliance or incident response. | Append-only database audit with actor/tenant/version/correlation fields, permissions and retention controls. | audit/migrations/repositories/tests | P1 |
| HIGH | No PII classification, masking, retention or encryption configuration. Customer and bank fields are persisted and returned. | Privacy/regulatory exposure. | Data inventory, minimization/masking, access controls, retention jobs and documented transport/at-rest requirements. | schema/API/logging/docs | P1 |
| MEDIUM | DB config has permissive defaults and manually interpolates URL credentials; no `.env` loader/startup validation/pooling. | Misconfiguration, URL escaping bugs, connection exhaustion. | Typed environment settings, URL-safe connection configuration, startup validation and psycopg pool. | `data_core/config.py`, DB modules, `.env.example` | P2 |
| MEDIUM | Migration runner is ad hoc; identifiers/schema names are interpolated; no migration version ledger. | Unsafe schema administration and inconsistent environments. | Use a migration tool/ledger, validated identifiers, and migration tests. | `data_core/db.py`, `database/migrations` | P2 |
| MEDIUM | Existing tables use text IDs and omit tenant, UUID defaults, universal `updated_at`, execution transition constraints and webhook/jobs/model entities. | Weak integrity and missing operational data model. | Add incremental V003+ migrations with UUIDs where new entities are introduced, FKs/checks/indexes/triggers. | migrations/schema docs | P2 |
| MEDIUM | Frontend has no login/session handling, role-aware UX, pagination, accessibility audit, or consequential-action confirmation. | Poor operational safety and usability; UI cannot support auth lifecycle. | Add auth-aware API client/UI states, pagination, keyboard/accessibility checks, confirmation and session expiry flows. | `frontend/src/*`, Playwright tests | P2 |
| MEDIUM | Test suite is unit-heavy; Playwright spec is boilerplate and no DB/auth/webhook/concurrency/failure tests exist. | Production controls regress without detection. | Add isolated integration/security/concurrency/failure tests and real RPA Playwright paths. | `tests`, `frontend/tests` | P2 |
| MEDIUM | No Dockerfiles, compose, health/readiness split, graceful shutdown, worker, queue or CI workflow. | Cannot reproduce or safely deploy the system. | Add containers, Compose services, health checks, CI and deployment/runbook docs. | new Docker/CI/docs files | P2 |
| MEDIUM | Dependency versions are broad, no lockfile for Python, no SCA/security scanning. | Non-reproducible and vulnerable builds. | Pin/lock Python dependencies and add dependency/security checks in CI. | requirements/lock/CI | P2 |
| LOW | Root and `rpa` implementations coexist, which can confuse ownership. | Maintenance and import mistakes. | Document canonical production path (`rpa/`) and progressively isolate legacy experiment code. | README/docs | P3 |
| LOW | Performance claims have no repeatable benchmark harness/results. | Unsupported capacity planning. | Add representative benchmark command/results; report measurements, not claims. | tests/scripts/docs | P3 |

## Audit verification

- File inventory and code review completed for backend, ML/data modules,
  migrations, frontend, scripts, tests, config and ignore files.
- `pytest -q` from the system interpreter could not collect because `numpy` is
  not installed there (`ModuleNotFoundError`); this is an environment finding,
  not a test result. A project `.venv` exists and will be used for subsequent
  verification.
- No Docker, Compose, CI workflow, auth, JWT, provider adapter, queue or
  webhook implementation was found.
- `.env` patterns are ignored. `.env.example` contains placeholders only; the
  local frontend `.env` is ignored and was not inspected for secret values.

## Implementation order

P0 is the safety foundation: explicit configuration/modes, production database
and tenant model, authentication/authorization, durable idempotent execution,
and atomic resource reservation. P1 then hardens the API, asynchronous work,
providers, optimizer/model/audit observability. P2 adds deployment, frontend
and comprehensive integration coverage. P3 addresses maintainability and
measured performance.
