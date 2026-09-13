"""Adversarial regression: EV-Greedy is provably suboptimal vs the exact ILP under
shared resource constraints.

This test constructs a deterministic 16-transaction batch whose frozen ground-truth
recovery probabilities create a genuine shared-resource conflict across retry,
messaging, incentive and human capacities. Under these tight caps the capacity-
rationed greedy baseline commits the scarce resources to the wrong transactions
(it orders by *marginal value* and never re-optimizes globally), while the RPA ILP
optimizer re-arbitrates and achieves a strictly higher planned (expected) net EV.

No randomness is introduced: probabilities are the hidden ground-truth logistic
model evaluated on deterministic, hand-crafted transactions, and both strategies
are run on identical inputs (the fair-comparison contract).
"""

from __future__ import annotations

import numpy as np
import pytest

from config import Action, Resource
from data_generation import Transaction, logit_recovery_probability
from expected_value import expected_value_matrix
from metrics import compute_batch_metrics
from outcome_simulator import generate_uniform_draws, simulate_outcomes_from_draws
from strategies import ACTIONS_LIST, ev_greedy_strategy, rpa_strategy

AMOUNTS = [
    5000,
    5000,
    2000,
    150,
    1000,
    2000,
    2000,
    150,
    300,
    1000,
    2000,
    500,
    5000,
    5000,
    300,
    5000,
]
# (retry_count, days_overdue, customer_ltv, historical_success_rate, historical_recovery_rate, behavior)
TXN_FEATURES = [
    (1, 107, 50000, 0.8922893364005569, 0.30341010807758545, 0.22432274714501765),
    (0, 79, 100000, 0.41279322734316004, 0.13072576548756742, -3.0),
    (1, 15, 10000, 0.3375627432763938, 0.42546382604156696, -0.7715284067303174),
    (1, 48, 100000, 0.5174975849834642, 0.09636102371491767, 0.13250086324357713),
    (3, 37, 100000, 0.4179661320588838, 0.02, 0.4289445577523304),
    (1, 63, 500000, 0.4633511889134591, 0.450904698066803, -0.7619261130473642),
    (0, 113, 100000, 0.3950821213162807, 0.9210361822777519, -0.17789414735687446),
    (1, 64, 100000, 0.4464405374312748, 0.8615979973405752, -2.298624962527061),
    (1, 75, 500000, 0.5385591422717043, 0.2333970218614385, -2.945166234600891),
    (1, 21, 100000, 0.8855007271463483, 0.3052830850239612, -1.7354099231202365),
    (1, 105, 500000, 0.2934391715922132, 0.98, 1.0029747728091967),
    (0, 111, 500000, 0.6470755194032332, 0.98, 0.5478874595721215),
    (1, 21, 500000, 0.3770055421128473, 0.34976088433044744, 1.1346420947473486),
    (3, 60, 100000, 0.5366019613461832, 0.31938600031578956, -3.0),
    (0, 110, 500000, 0.6007826291913305, 0.11622804609854133, 1.5248367397252305),
    (1, 64, 10000, 0.322052745997112, 0.08235848410212337, 2.9377167205221753),
]

CAPS = {
    Resource.RETRY: 5.0,
    Resource.MESSAGING: 2.0,
    Resource.INCENTIVE_BUDGET: 150.0,
    Resource.HUMAN_SLOTS: 2.0,
}

# Tight capacities that the optimum saturates.
TIGHT_RETRY = 5.0
TIGHT_MESSAGING = 2.0
TIGHT_HUMAN = 2.0


def _build_txns():
    return [
        Transaction(
            transaction_id=i,
            amount=float(AMOUNTS[i]),
            payment_method="upi",
            bank="HDFC",
            failure_reason="insufficient_funds",
            retry_count=int(TXN_FEATURES[i][0]),
            days_overdue=int(TXN_FEATURES[i][1]),
            customer_ltv=float(TXN_FEATURES[i][2]),
            historical_success_rate=float(TXN_FEATURES[i][3]),
            historical_recovery_rate=float(TXN_FEATURES[i][4]),
            customer_behavior_score=float(TXN_FEATURES[i][5]),
        )
        for i in range(len(AMOUNTS))
    ]


def test_greedy_is_suboptimal_to_ilp_under_tight_resources():
    txns = _build_txns()
    # Ground-truth-consistent frozen predictions (no RNG, no leakage).
    probs = {a: logit_recovery_probability(txns, a) for a in Action}

    g = ev_greedy_strategy(txns, probs, CAPS)
    r = rpa_strategy(txns, probs, CAPS)

    # Core discovery: the two strategies commit DIFFERENT portfolios.
    assert g.actions != r.actions
    assert r.solve_status == "optimal"
    # Both respect every constraint (fail-closed fairness).
    assert g.check_violations() == []
    assert r.check_violations() == []

    g_planned = float(sum(g.expected_values))
    r_planned = float(sum(r.expected_values))
    # The exact ILP optimum strictly beats the greedy committed plan.
    assert r_planned > g_planned
    assert r_planned - g_planned == pytest.approx(386.2432, rel=1e-4)

    # Both deploy exactly the same number of interventions -- this is a pure
    # *re-allocation* under identical budgets, not extra capacity.
    n_interv_g = sum(1 for a in g.actions if a != Action.NO_INTERVENTION)
    n_interv_r = sum(1 for a in r.actions if a != Action.NO_INTERVENTION)
    assert n_interv_g == n_interv_r == 7

    # The tight shared resources are fully saturated in the optimal portfolio
    # (i.e. the constraints genuinely bite / bind).
    assert g.resource_used["retry"] == TIGHT_RETRY
    assert g.resource_used["messaging"] == TIGHT_MESSAGING
    assert g.resource_used["human"] == TIGHT_HUMAN
    assert r.resource_used["retry"] == TIGHT_RETRY
    assert r.resource_used["messaging"] == TIGHT_MESSAGING
    assert r.resource_used["human"] == TIGHT_HUMAN

    # Pin the discovered greedy mistake: under the marginal-value ordering
    # greedy hands the scarce human+ messaging slot to txn 1 (MV 1898) and
    # leaves txn 0 (MV 1887) on its poor retry fallback. The ILP instead gives
    # txn 0 the human slot (its larger regret: human-retry = +1487) and txn 1
    # the retry slot -- strictly better globally.
    assert g.actions[0] == Action.RETRY
    assert r.actions[0] == Action.HUMAN_ESCALATION
    assert g.actions[1] == Action.HUMAN_ESCALATION
    assert r.actions[1] == Action.RETRY

    # Sanity: the EV matrix actually makes human the best-EV action for those
    # two txns (so the "swap" is a genuine greedy blind spot, not noise).
    em = expected_value_matrix([t.amount for t in txns], probs, ACTIONS_LIST)
    assert (
        em[0, ACTIONS_LIST.index(Action.HUMAN_ESCALATION)]
        > em[0, ACTIONS_LIST.index(Action.RETRY)]
    )
    assert (
        em[1, ACTIONS_LIST.index(Action.HUMAN_ESCALATION)]
        > em[1, ACTIONS_LIST.index(Action.RETRY)]
    )


def test_rpa_also_wins_on_average_simulated_net_recovery():
    """Shared-draw (identical-realization) simulation: RPA's expected net exceeds
    greedy's averaged over many deterministic seeds. A single realization is
    too noisy (high-amount txns), so we average to recover the planned-EV edge."""
    txns = _build_txns()
    probs = {a: logit_recovery_probability(txns, a) for a in Action}
    g = ev_greedy_strategy(txns, probs, CAPS)
    r = rpa_strategy(txns, probs, CAPS)

    g_planned = float(sum(g.expected_values))
    r_planned = float(sum(r.expected_values))

    g_nets = []
    r_nets = []
    for s in range(200):
        u = generate_uniform_draws(len(txns), s)
        gm = compute_batch_metrics(
            txns, g, simulate_outcomes_from_draws(txns, g.actions, u), 0.0
        )
        rm = compute_batch_metrics(
            txns, r, simulate_outcomes_from_draws(txns, r.actions, u), 0.0
        )
        g_nets.append(gm.net_recovered)
        r_nets.append(rm.net_recovered)
    g_nets = np.array(g_nets)
    r_nets = np.array(r_nets)

    # Planning edge (deterministic, mathematically guaranteed by ILP optimality).
    assert r_planned > g_planned
    # Simulation, averaged over the 200 deterministic seeds, converges onto the
    # planned edge: RPA is better in expectation.
    assert r_nets.mean() > g_nets.mean()
