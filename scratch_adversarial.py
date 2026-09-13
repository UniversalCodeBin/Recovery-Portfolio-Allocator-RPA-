"""Scratch exploration: find a clean adversarial dataset where EV-Greedy != RPA ILP."""
from __future__ import annotations

import numpy as np

from config import Action, Resource
from data_generation import Transaction
from strategies import ev_greedy_strategy, rpa_strategy
from expected_value import expected_value_matrix
from actions import action_cost

AMOUNT = 5000.0


def make_txn(i: int) -> Transaction:
    return Transaction(
        transaction_id=i,
        amount=AMOUNT,
        payment_method="upi",
        bank="HDFC",
        failure_reason="insufficient_funds",
        retry_count=0,
        days_overdue=10,
        customer_ltv=50000.0,
        historical_success_rate=0.3,
        historical_recovery_rate=0.3,
        customer_behavior_score=0.0,
    )


def p_for_target_ev(target_ev: float, cost: float) -> float:
    # EV = amount*p - cost  =>  p = (EV + cost)/amount
    p = (target_ev + cost) / AMOUNT
    return float(min(max(p, 0.0), 1.0))


def build_probs(n, p_retry_list, p_msg_list, p_other=0.0):
    """Return {Action: np.ndarray}. Other actions get p_other (=> negative EV, never chosen)."""
    p = {
        Action.NO_INTERVENTION: np.full(n, 0.0),
        Action.RETRY: np.array(p_retry_list, dtype=float),
        Action.PAYMENT_LINK: np.full(n, p_other),
        Action.CUSTOMER_MESSAGE: np.array(p_msg_list, dtype=float),
        Action.INCENTIVE: np.full(n, p_other),
        Action.HUMAN_ESCALATION: np.full(n, p_other),
    }
    return p


def ev_summary(alloc, amounts):
    ev = float(sum(alloc.expected_values))
    counts = {a.value: 0 for a in Action}
    for a in alloc.actions:
        counts[a.value] += 1
    return ev, counts, alloc.resource_used, alloc.solve_status


def explore():
    # Group A: high-MV, retry(50) + message(40)
    # Group B: lower-MV, retry(49), no message alternative
    n_a, n_b = 4, 4
    n = n_a + n_b
    txns = [make_txn(i) for i in range(n)]

    p_retry = [p_for_target_ev(50, action_cost(Action.RETRY))] * n_a + \
              [p_for_target_ev(49, action_cost(Action.RETRY))] * n_b
    p_msg = [p_for_target_ev(40, action_cost(Action.CUSTOMER_MESSAGE))] * n_a + \
            [0.0] * n_b  # B has no useful message

    probs = build_probs(n, p_retry, p_msg)

    # Verify EVs
    ev_mat = expected_value_matrix([t.amount for t in txns], probs,
                                   [Action.NO_INTERVENTION, Action.RETRY, Action.PAYMENT_LINK,
                                    Action.CUSTOMER_MESSAGE, Action.INCENTIVE, Action.HUMAN_ESCALATION])
    print("EV matrix (rows=txn, cols=NOI,RETRY,PL,MSG,INC,HUM):")
    for i in range(n):
        print(f"  txn{i:2d} ({'A' if i<n_a else 'B'}): " + " ".join(f"{v:7.2f}" for v in ev_mat[i]))

    import itertools
    retry_caps = [1, 2]
    msg_caps = [2, 3, 4, 5]
    inc_caps = [0, 500, 10000]
    hum_caps = [0, 2, 10000]
    best = None
    for rc in retry_caps:
        for mc in msg_caps:
            for ic in inc_caps:
                for hc in hum_caps:
                    cap = {}
                    if rc is not None and rc > 0:
                        cap[Resource.RETRY] = float(rc)
                    if mc is not None and mc > 0:
                        cap[Resource.MESSAGING] = float(mc)
                    if ic is not None and ic > 0:
                        cap[Resource.INCENTIVE_BUDGET] = float(ic)
                    if hc is not None and hc > 0:
                        cap[Resource.HUMAN_SLOTS] = float(hc)
                    g = ev_greedy_strategy(txns, probs, cap)
                    r = rpa_strategy(txns, probs, cap)
                    gev, _, _, _ = ev_summary(g, [t.amount for t in txns])
                    rev, _, _, rstatus = ev_summary(r, [t.amount for t in txns])
                    if g.actions != r.actions and rstatus == "optimal":
                        diff = rev - gev
                        if best is None or diff > best[0]:
                            best = (diff, rc, mc, ic, hc, gev, rev, g.actions, r.actions,
                                    g.resource_used, r.resource_used, len(g.check_violations()), len(r.check_violations()))
    if best:
        diff, rc, mc, ic, hc, gev, rev, ga, ra, gru, rru, gv, rv = best
        print(f"\n*** FOUND diff={diff:.2f} caps retry={rc} msg={mc} inc={ic} hum={hc}")
        print(f"  Greedy net EV={gev:.2f} | RPA net EV={rev:.2f} | status=rpa optimal")
        print(f"  Greedy actions={[a.value for a in ga]}")
        print(f"  RPA    actions={[a.value for a in ra]}")
        print(f"  Greedy res_used={gru} violations={gv}")
        print(f"  RPA    res_used={rru} violations={rv}")
    else:
        print("\nNo clean (optimal, differing) case found in this sweep.")


if __name__ == "__main__":
    explore()
