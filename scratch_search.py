"""Scratch exploration v4: randomized search over feature profiles to find a strict greedy < ILP
   instance using GROUND-TRUTH-consistent probabilities (injected == ground truth)."""
from __future__ import annotations

import numpy as np
from itertools import product

from config import Action, Resource
from data_generation import Transaction, logit_recovery_probability
from strategies import ev_greedy_strategy, rpa_strategy
from expected_value import expected_value_matrix, expected_net_recovery
from actions import action_cost

rng = np.random.default_rng(123)

ACTS = [Action.NO_INTERVENTION, Action.RETRY, Action.PAYMENT_LINK,
        Action.CUSTOMER_MESSAGE, Action.INCENTIVE, Action.HUMAN_ESCALATION]


def make_txns(n, seed):
    r = np.random.default_rng(seed)
    txns = []
    for i in range(n):
        txns.append(Transaction(
            transaction_id=i,
            amount=float(r.choice([150, 300, 500, 1000, 2000, 5000])),
            payment_method="upi",
            bank="HDFC",
            failure_reason="insufficient_funds",
            retry_count=int(r.integers(0, 4)),
            days_overdue=int(r.integers(0, 120)),
            customer_ltv=float(r.choice([10000, 50000, 100000, 500000])),
            historical_success_rate=float(np.clip(r.normal(0.4, 0.3), 0.02, 0.98)),
            historical_recovery_rate=float(np.clip(r.normal(0.4, 0.3), 0.02, 0.98)),
            customer_behavior_score=float(np.clip(r.normal(0, 1.5), -3, 3)),
        ))
    return txns


def gt_probs(txns):
    return {a: logit_recovery_probability(txns, a) for a in Action}


def make_cap(rc, mc, ic, hc):
    cap = {}
    if rc: cap[Resource.RETRY] = float(rc)
    if mc: cap[Resource.MESSAGING] = float(mc)
    if ic: cap[Resource.INCENTIVE_BUDGET] = float(ic)
    if hc: cap[Resource.HUMAN_SLOTS] = float(hc)
    return cap


def util_frac(alloc, cap):
    f = {}
    rmap = {"retry": Resource.RETRY, "messaging": Resource.MESSAGING,
            "incentive": Resource.INCENTIVE_BUDGET, "human": Resource.HUMAN_SLOTS}
    for r, res in rmap.items():
        c = cap.get(res)
        f[r] = alloc.resource_used.get(r, 0.0) / c if (c is not None and c > 0) else None
    return f


found = []
for trial in range(4000):
    n = int(rng.integers(8, 20))
    txns = make_txns(n, 1000 + trial)
    probs = gt_probs(txns)
    rc = int(rng.integers(1, 6))
    mc = int(rng.integers(1, 8))
    hc = int(rng.integers(1, 6))
    ic = int(rng.choice([50, 100, 150, 200, 300, 500]))
    cap = make_cap(rc, mc, ic, hc)
    g = ev_greedy_strategy(txns, probs, cap)
    r = rpa_strategy(txns, probs, cap)
    if g.actions == r.actions:
        continue
    if r.solve_status != "optimal":
        continue
    if g.check_violations() or r.check_violations():
        continue
    gev = float(sum(g.expected_values))
    rev = float(sum(r.expected_values))
    if rev <= gev + 1e-6:
        continue
    # require >=2 resources bind in RPA
    ru = util_frac(r, cap)
    binds = sum(1 for v in ru.values() if v is not None and v >= 0.999 - 1e-9)
    if binds < 2:
        continue
    found.append((rev - gev, len(txns), (rc, mc, ic, hc), gev, rev, binds,
                  [a.value for a in g.actions], [a.value for a in r.actions],
                  {k: (round(v,2) if v is not None else None) for k, v in util_frac(g, cap).items()},
                  {k: (round(v,2) if v is not None else None) for k, v in ru.items()},
                  trial))

found.sort(reverse=True)
print(f"found {len(found)} strict-greedy-suboptimal instances (ILP optimal + feasible)")
for d, n, caps, gev, rev, b, ga, ra, gu, ru, trial in found[:5]:
    print(f"\n*** TRIAL {trial}: n={n} caps(retry,msg,inc,hum)={caps} diff={d:.2f} ILP_binds={b}")
    print(f"  Greedy EV={gev:.2f}  RPA EV={rev:.2f}")
    print(f"  Greedy actions={ga}")
    print(f"  RPA    actions={ra}")
    print(f"  Greedy util={gu}")
    print(f"  RPA    util={ru}")
    # show EV matrix for this one
    print("  (saved trial for inspection)")
