"""Scratch exploration v3: ground-truth-consistent probs, 4 resource types, find clean greedy!=ILP."""
from __future__ import annotations

import numpy as np
from itertools import product

from config import Action, Resource, PROB_EPS
from data_generation import Transaction, logit_recovery_probability
from strategies import ev_greedy_strategy, rpa_strategy, ACTIONS_LIST
from expected_value import expected_value_matrix
from actions import action_cost, action_resource_vector
from outcome_simulator import generate_uniform_draws, simulate_outcomes_from_draws
from metrics import compute_batch_metrics

AMOUNT = 5000.0


def txn(i, amount, success, overdue, ltv, behavior, retries):
    return Transaction(
        transaction_id=i,
        amount=amount,
        payment_method="upi",
        bank="HDFC",
        failure_reason="insufficient_funds",
        retry_count=int(retries),
        days_overdue=int(overdue),
        customer_ltv=ltv,
        historical_success_rate=success,
        historical_recovery_rate=success,
        customer_behavior_score=behavior,
    )


def gt_probs(txns):
    return {a: logit_recovery_probability(txns, a) for a in Action}


def ev_for(txns, probs):
    em = expected_value_matrix([t.amount for t in txns], probs, ACTIONS_LIST)
    return em


def util_frac(alloc, cap):
    f = {}
    rmap = {"retry": Resource.RETRY, "messaging": Resource.MESSAGING,
            "incentive": Resource.INCENTIVE_BUDGET, "human": Resource.HUMAN_SLOTS}
    for r, res in rmap.items():
        c = cap.get(res)
        f[r] = alloc.resource_used.get(r, 0.0) / c if (c is not None and c > 0) else None
    return f


def make_cap(rc, mc, ic, hc):
    cap = {}
    if rc is not None:
        cap[Resource.RETRY] = float(rc)
    if mc is not None:
        cap[Resource.MESSAGING] = float(mc)
    if ic is not None:
        cap[Resource.INCENTIVE_BUDGET] = float(ic)
    if hc is not None:
        cap[Resource.HUMAN_SLOTS] = float(hc)
    return cap


def build_dataset():
    txns = []
    i = 0
    # Group C (4): high base -> human best, msg good alt
    for _ in range(4):
        txns.append(txn(i, 5000, 0.9, 0, 100000, -2.0, 0)); i += 1
    # Group D (4): mid base -> human best, msg weaker
    for _ in range(4):
        txns.append(txn(i, 5000, 0.5, 0, 100000, -2.0, 0)); i += 1
    # Group R (4): low base -> retry fallback when messaging exhausted
    for _ in range(4):
        txns.append(txn(i, 5000, 0.05, 60, 50000, 1.0, 0)); i += 1
    return txns


def main():
    txns = build_dataset()
    probs = gt_probs(txns)
    em = ev_for(txns, probs)
    labels = ["noi", "retry", "plink", "msg", "inc", "human"]
    print("Group | txn | " + " ".join(f"{l:>7}" for l in labels))
    grp = []
    for j, _ in enumerate(txns):
        g = "C" if j < 4 else "D" if j < 8 else "R"
        grp.append(g)
    for j, t in enumerate(txns):
        print(f"  {grp[j]}   {j:2d} | " + " ".join(f"{em[j,k]:7.2f}" for k in range(6)))

    # also print per-txn best action
    best = [ACTIONS_LIST[int(k)].value for k in em.argmax(axis=1)]
    print("best action per txn:", best)

    best_cfg = None
    sweep_r = [1, 2, 3, 4]
    sweep_m = [2, 3, 4, 5, 6]
    sweep_h = [1, 2, 3, 4]
    sweep_i = [50, 100, 200, 100000]  # 1,2,4 incentives or unlimited
    for rc, mc, ic, hc in product(sweep_r, sweep_m, sweep_i, sweep_h):
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
        if rev <= gev:
            continue
        ru = util_frac(r, cap)
        binds = sum(1 for v in ru.values() if v is not None and v >= 0.999 - 1e-9)
        if binds < 3:
            continue
        diff = rev - gev
        if best_cfg is None or diff > best_cfg[0]:
            best_cfg = (diff, rc, mc, ic, hc, gev, rev,
                        [a.value for a in g.actions], [a.value for a in r.actions],
                        util_frac(g, cap), util_frac(r, cap))
    if best_cfg:
        diff, rc, mc, ic, hc, gev, rev, ga, ra, gu, ru = best_cfg
        print(f"\n*** FOUND diff={diff:.2f} caps retry={rc} msg={mc} inc={ic} hum={hc}")
        print(f"  Greedy planned EV={gev:.2f}  RPA planned EV={rev:.2f}  ILP=optimal")
        print(f"  Greedy actions={ga}")
        print(f"  RPA    actions={ra}")
        print(f"  Greedy util={ {k:(round(v,2) if v is not None else None) for k,v in gu.items()} }")
        print(f"  RPA    util={ {k:(round(v,2) if v is not None else None) for k,v in ru.items()} }")
        # simulation
        u = generate_uniform_draws(len(txns), 0)
        from metrics import compute_batch_metrics
        gm = compute_batch_metrics(txns, g, simulate_outcomes_from_draws(txns, g.actions, u), 0.0)
        rm = compute_batch_metrics(txns, r, simulate_outcomes_from_draws(txns, r.actions, u), 0.0)
        print(f"  Sims: greedy actual={gm.actual_recovered:.2f} net={gm.net_recovered:.2f} cost={gm.total_action_cost:.2f}")
        print(f"  Sims: rpa    actual={rm.actual_recovered:.2f} net={rm.net_recovered:.2f} cost={rm.total_action_cost:.2f}")
        print(f"  Greedy txn counts={gm.transaction_counts}")
        print(f"  RPA    txn counts={rm.transaction_counts}")
    else:
        print("\nNo config found with >=3 binding resources.")


if __name__ == "__main__":
    main()
