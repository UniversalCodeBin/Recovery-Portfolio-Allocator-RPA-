"""Scratch exploration v2: 4-group adversarial dataset, sweep all tight capacities."""
from __future__ import annotations

import numpy as np

from config import Action, Resource
from data_generation import Transaction
from strategies import ev_greedy_strategy, rpa_strategy
from expected_value import expected_value_matrix
from actions import action_cost, action_resource_vector

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


def p_for_ev(target_ev, cost):
    return float(min(max((target_ev + cost) / AMOUNT, 0.0), 1.0))


def build_probs(n, rows):
    p = {a: np.zeros(n) for a in Action}
    for i, (pr, pm, pi, ph) in enumerate(rows):
        p[Action.RETRY][i] = pr
        p[Action.CUSTOMER_MESSAGE][i] = pm
        p[Action.INCENTIVE][i] = pi
        p[Action.HUMAN_ESCALATION][i] = ph
    return p


def ev_summary(alloc):
    ev = float(sum(alloc.expected_values))
    counts = {a.value: 0 for a in Action}
    for a in alloc.actions:
        counts[a.value] += 1
    return ev, counts, dict(alloc.resource_used), alloc.solve_status


def groups():
    # A: high MV, retry(50)/msg(40)  [swap-capable, retry-best]
    a = 4
    # B: lower MV, retry(49)/no-msg  [retry-only]
    b = 4
    # C: high MV, human(80)/msg(60) [swap-capable, human-best]
    c = 3
    # D: lower MV, human(79)/no-msg  [human-only]
    d = 3
    n = a + b + c + d
    rows = []
    for _ in range(a):
        rows.append((p_for_ev(50, action_cost(Action.RETRY)), p_for_ev(40, action_cost(Action.CUSTOMER_MESSAGE)), 0.0, 0.0))
    for _ in range(b):
        rows.append((p_for_ev(49, action_cost(Action.RETRY)), 0.0, 0.0, 0.0))
    for _ in range(c):
        rows.append((0.0, p_for_ev(60, action_cost(Action.CUSTOMER_MESSAGE)), 0.0, p_for_ev(80, action_cost(Action.HUMAN_ESCALATION))))
    for _ in range(d):
        rows.append((0.0, 0.0, 0.0, p_for_ev(79, action_cost(Action.HUMAN_ESCALATION))))
    return n, rows, a, b, c, d


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


def util_frac(alloc, cap):
    f = {}
    for r in ["retry", "messaging", "incentive", "human"]:
        c = cap.get({"retry": Resource.RETRY, "messaging": Resource.MESSAGING,
                     "incentive": Resource.INCENTIVE_BUDGET, "human": Resource.HUMAN_SLOTS}[r])
        f[r] = alloc.resource_used.get(r, 0.0) / c if (c is not None and c > 0) else None
    return f


def explore():
    n, rows, a, b, c, d = groups()
    txns = [make_txn(i) for i in range(n)]
    probs = build_probs(n, rows)
    em = expected_value_matrix([t.amount for t in txns], probs,
                               [Action.NO_INTERVENTION, Action.RETRY, Action.PAYMENT_LINK,
                                Action.CUSTOMER_MESSAGE, Action.INCENTIVE, Action.HUMAN_ESCALATION])
    print("EV matrix:")
    for i in range(n):
        grp = "A" if i<a else "B" if i<a+b else "C" if i<a+b+c else "D"
        print(f"  txn{i:2d} ({grp}): " + " ".join(f"{v:7.2f}" for v in em[i]))

    import itertools
    rcs = [1, 2, 3]
    mcs = [2, 3, 4, 5, 6]
    ics = [50, 100, 150]     # 1,2,3 incentives (each costs 50 budget)
    hcs = [1, 2, 3]
    cands = []
    for rc, mc, ic, hc in itertools.product(rcs, mcs, ics, hcs):
        cap = make_cap(rc, mc, ic, hc)
        g = ev_greedy_strategy(txns, probs, cap)
        r = rpa_strategy(txns, probs, cap)
        if g.actions == r.actions:
            continue
        if r.solve_status != "optimal":
            continue
        if g.check_violations() or r.check_violations():
            continue
        gev, gct, gru, _ = ev_summary(g)
        rev, rct, rru, _ = ev_summary(r)
        gu = util_frac(g, cap)
        ru = util_frac(r, cap)
        # require at least retry+messaging bind in ILP, plus human or incentive binds
        ilp_bind = sum(1 for v in ru.values() if v is not None and v >= 0.999 - 1e-9)
        if ilp_bind < 3:
            continue
        cands.append((rev - gev, rc, mc, ic, hc, gev, rev,
                      [a.value for a in g.actions], [a.value for a in r.actions],
                      gu, ru, ilp_bind))
    cands.sort(reverse=True)
    print(f"\n{len(cands)} candidate configs (greedy!=ILP, ILP optimal, feasible, >=3 resources bind in ILP)")
    for diff, rc, mc, ic, hc, gev, rev, ga, ra, gu, ru, ib in cands[:8]:
        print(f"\n*** diff={diff:.2f} caps retry={rc} msg={mc} inc={ic} hum={hc} (ILP binds {ib} res)")
        print(f"  Greedy EV={gev:.2f}  RPA EV={rev:.2f}  status=rpa optimal")
        print(f"  Greedy actions={ga}")
        print(f"  RPA    actions={ra}")
        print(f"  Greedy util={ {k:round(v,2) if v is not None else None for k,v in gu.items()} }")
        print(f"  RPA    util={ {k:round(v,2) if v is not None else None for k,v in ru.items()} }")


if __name__ == "__main__":
    explore()
