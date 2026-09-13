"""Final adversarial verification: hardcode the dataset, recompute ground-truth
   probabilities (so planning == simulation model), run BOTH strategies, compare."""
from __future__ import annotations

import numpy as np

from config import Action, Resource
from data_generation import Transaction, logit_recovery_probability
from strategies import ev_greedy_strategy, rpa_strategy
from expected_value import expected_value_matrix
from outcome_simulator import generate_uniform_draws, simulate_outcomes_from_draws
from metrics import compute_batch_metrics


def T(i, amount, retry_count, overdue, ltv, sr, rr, beh):
    return Transaction(
        transaction_id=i, amount=float(amount), payment_method="upi", bank="HDFC",
        failure_reason="insufficient_funds", retry_count=int(retry_count),
        days_overdue=int(overdue), customer_ltv=float(ltv),
        historical_success_rate=float(sr), historical_recovery_rate=float(rr),
        customer_behavior_score=float(beh),
    )


TXNS = [
    T(0, 5000, 1, 107, 50000, 0.8922893364005569, 0.30341010807758545, 0.22432274714501765),
    T(1, 5000, 0, 79, 100000, 0.41279322734316004, 0.13072576548756742, -3.0),
    T(2, 2000, 1, 15, 10000, 0.3375627432763938, 0.42546382604156696, -0.7715284067303174),
    T(3, 150, 1, 48, 100000, 0.5174975849834642, 0.09636102371491767, 0.13250086324357713),
    T(4, 1000, 3, 37, 100000, 0.4179661320588838, 0.02, 0.4289445577523304),
    T(5, 2000, 1, 63, 500000, 0.4633511889134591, 0.450904698066803, -0.7619261130473642),
    T(6, 2000, 0, 113, 100000, 0.3950821213162807, 0.9210361822777519, -0.17789414735687446),
    T(7, 150, 1, 64, 100000, 0.4464405374312748, 0.8615979973405752, -2.298624962527061),
    T(8, 300, 1, 75, 500000, 0.5385591422717043, 0.2333970218614385, -2.945166234600891),
    T(9, 1000, 1, 21, 100000, 0.8855007271463483, 0.3052830850239612, -1.7354099231202365),
    T(10, 2000, 1, 105, 500000, 0.2934391715922132, 0.98, 1.0029747728091967),
    T(11, 500, 0, 111, 500000, 0.6470755194032332, 0.98, 0.5478874595721215),
    T(12, 5000, 1, 21, 500000, 0.3770055421128473, 0.34976088433044744, 1.1346420947473486),
    T(13, 5000, 3, 60, 100000, 0.5366019613461832, 0.31938600031578956, -3.0),
    T(14, 300, 0, 110, 500000, 0.6007826291913305, 0.11622804609854133, 1.5248367397252305),
    T(15, 5000, 1, 64, 10000, 0.322052745997112, 0.08235848410212337, 2.9377167205221753),
]

CAPS = {
    Resource.RETRY: 5.0,
    Resource.MESSAGING: 2.0,
    Resource.INCENTIVE_BUDGET: 150.0,
    Resource.HUMAN_SLOTS: 2.0,
}


def main():
    n = len(TXNS)
    probs = {a: logit_recovery_probability(TXNS, a) for a in Action}
    em = expected_value_matrix([t.amount for t in TXNS], probs,
                               [Action.NO_INTERVENTION, Action.RETRY, Action.PAYMENT_LINK,
                                Action.CUSTOMER_MESSAGE, Action.INCENTIVE, Action.HUMAN_ESCALATION])
    print("EV matrix (txn | noi retry plink msg inc human):")
    for i in range(n):
        print(f"  txn{i:2d} | " + " ".join(f"{em[i,k]:7.2f}" for k in range(6)))

    g = ev_greedy_strategy(TXNS, probs, CAPS)
    r = rpa_strategy(TXNS, probs, CAPS)

    print("\n=== PLANNED ALLOCATION ===")
    print("Greedy actions:", [a.value for a in g.actions])
    print("RPA    actions:", [a.value for a in r.actions])
    gev = float(sum(g.expected_values)); rev = float(sum(r.expected_values))
    print(f"Greedy planned net EV = {gev:.4f}")
    print(f"RPA    planned net EV = {rev:.4f}")
    print(f"Difference (RPA - Greedy) = {rev - gev:.4f}")
    print("RPA solve status:", r.solve_status)

    def counts(alloc):
        c = {a.value: 0 for a in Action}
        for a in alloc.actions:
            c[a.value] += 1
        return c
    print("\nGreedy action counts:", counts(g))
    print("RPA    action counts:", counts(r))

    def util(alloc, cap):
        f = {}
        rmap = {"retry": Resource.RETRY, "messaging": Resource.MESSAGING,
                "incentive": Resource.INCENTIVE_BUDGET, "human": Resource.HUMAN_SLOTS}
        for k, res in rmap.items():
            c = cap.get(res)
            f[k] = alloc.resource_used.get(k, 0.0) / c if (c is not None and c > 0) else None
        return f
    print("\nGreedy resource used:", {k: round(float(v), 3) for k, v in g.resource_used.items()})
    print("RPA    resource used:", {k: round(float(v), 3) for k, v in r.resource_used.items()})
    print("Greedy utilization:", {k: (round(v, 3) if v is not None else None) for k, v in util(g, CAPS).items()})
    print("RPA    utilization:", {k: (round(v, 3) if v is not None else None) for k, v in util(r, CAPS).items()})
    print("Greedy violations:", g.check_violations())
    print("RPA    violations:", r.check_violations())

    n_interv_g = sum(1 for a in g.actions if a != Action.NO_INTERVENTION)
    n_interv_r = sum(1 for a in r.actions if a != Action.NO_INTERVENTION)
    print(f"\nGreedy transactions receiving intervention: {n_interv_g}")
    print(f"RPA    transactions receiving intervention: {n_interv_r}")

    print("\n=== SIMULATED (actual) NET RECOVERY, shared seed=0 ===")
    u = generate_uniform_draws(n, 0)
    gm = compute_batch_metrics(TXNS, g, simulate_outcomes_from_draws(TXNS, g.actions, u), 0.0)
    rm = compute_batch_metrics(TXNS, r, simulate_outcomes_from_draws(TXNS, r.actions, u), 0.0)
    print(f"Greedy: actual={gm.actual_recovered:.2f} net={gm.net_recovered:.2f} cost={gm.total_action_cost:.2f} rate={gm.recovery_rate:.4f}")
    print(f"RPA    : actual={rm.actual_recovered:.2f} net={rm.net_recovered:.2f} cost={rm.total_action_cost:.2f} rate={rm.recovery_rate:.4f}")
    print("Greedy txn_counts:", gm.transaction_counts)
    print("RPA    txn_counts:", rm.transaction_counts)
    print(f"Greedy n_violations={gm.n_violations}  RPA n_violations={rm.n_violations}")

    print("\n=== VERDICT ===")
    print("Greedy actions == RPA actions?", g.actions == r.actions)
    print("RPA planned net EV > Greedy planned net EV?", rev > gev)
    print("Both feasible (no violations)?", (not g.check_violations()) and (not r.check_violations()))
    print("RPA optimal?", r.solve_status == "optimal")


if __name__ == "__main__":
    main()
