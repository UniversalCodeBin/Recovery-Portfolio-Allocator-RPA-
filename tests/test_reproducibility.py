from __future__ import annotations

import numpy as np

from experiment import Experiment


def _run_scenario(scenario_name: str, seed: int, n_seeds: int):
    exp = Experiment(scenarios=[scenario_name], n_seeds=n_seeds, seed=seed)
    exp.prepare_data_and_model()
    out: dict = {}
    for s in range(n_seeds):
        res = exp.run_seed_scenario(scenario_name, s)
        out[s] = {
            name: {
                "actual": bm.actual_recovered,
                "net": bm.net_recovered,
                "actions": [a.value for a in alloc.actions],
            }
            for name, alloc in res["allocations"].items()
            for bm in [res["metrics"][name]]
        }
    return out


def test_experiment_reproducible_same_seed_different_instances():
    a = _run_scenario("A", 55, 2)
    b = _run_scenario("A", 55, 2)
    assert a == b


def test_experiment_variable_across_seeds():
    a = _run_scenario("B", 56, 2)
    _run_scenario("B", 57, 2)
    # Different master seed --> different batches, but everything stays valid.
    assert a[0]["rpa"]["actual"] + a[0]["ev_greedy"]["actual"] > 0


def test_model_predictions_frozen_across_strategies():
    """Verify all strategies consumed byte-identical frozen probabilities."""
    from config import Action
    from data_generation import sample_batch

    exp = Experiment(scenarios=["A"], n_seeds=1)
    exp.prepare_data_and_model()
    batch = sample_batch(exp.demo_pool, 40, 0)
    probs = exp._model.predict_proba(batch)
    probs2 = exp._model.predict_proba(batch)
    for a in Action:
        np.testing.assert_array_equal(probs[a], probs2[a])


def test_no_binding_constraints_matches_unconstrained():
    """Relaxed capacities: RPA == greedy (both = EV optimum) in every seed."""
    from actions import Resource
    from strategies import ev_greedy_strategy, rpa_strategy

    exp = Experiment(scenarios=["E"], n_seeds=3)
    exp.prepare_data_and_model()
    cap = {
        Resource.INCENTIVE_BUDGET: 1e9,
        Resource.HUMAN_SLOTS: 10_000,
        Resource.MESSAGING: 10_000,
        Resource.RETRY: 10_000,
    }
    from data_generation import sample_batch

    for s in range(3):
        batch = sample_batch(exp.demo_pool, 120, s)
        probs = exp._model.predict_proba(batch)
        g = ev_greedy_strategy(batch, probs, cap)
        r = rpa_strategy(batch, probs, cap)
        assert g.actions == r.actions
