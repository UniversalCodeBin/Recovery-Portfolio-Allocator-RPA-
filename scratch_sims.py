"""Multi-seed simulation comparison (deterministic shared draws, seeds 0..19)."""
from __future__ import annotations

import numpy as np

from config import Action, Resource
from data_generation import Transaction, logit_recovery_probability
from strategies import ev_greedy_strategy, rpa_strategy
from outcome_simulator import generate_uniform_draws, simulate_outcomes_from_draws
from metrics import compute_batch_metrics
import scratch_verify as V


def main():
    n = len(V.TXNS)
    probs = {a: logit_recovery_probability(V.TXNS, a) for a in Action}
    g = ev_greedy_strategy(V.TXNS, probs, V.CAPS)
    r = rpa_strategy(V.TXNS, probs, V.CAPS)
    gev = float(sum(g.expected_values)); rev = float(sum(r.expected_values))
    print(f"Planned net EV: greedy={gev:.2f}  rpa={rev:.2f}  diff={rev-gev:.2f}")

    gnets = []; rnets = []; gacts = []; racts = []
    for s in range(200):
        u = generate_uniform_draws(n, s)
        gm = compute_batch_metrics(V.TXNS, g, simulate_outcomes_from_draws(V.TXNS, g.actions, u), 0.0)
        rm = compute_batch_metrics(V.TXNS, r, simulate_outcomes_from_draws(V.TXNS, r.actions, u), 0.0)
        gnets.append(gm.net_recovered); rnets.append(rm.net_recovered)
        gacts.append(gm.actual_recovered); racts.append(rm.actual_recovered)

    gnets = np.array(gnets); rnets = np.array(rnets)
    gacts = np.array(gacts); racts = np.array(racts)
    print(f"Avg simulated net   (200 seeds): greedy={gnets.mean():.2f}  rpa={rnets.mean():.2f}  diff={rnets.mean()-gnets.mean():.2f}")
    print(f"Avg simulated gross (200 seeds): greedy={gacts.mean():.2f}  rpa={racts.mean():.2f}  diff={racts.mean()-gacts.mean():.2f}")
    print(f"Planned net EV (expectation):    greedy={gev:.2f}  rpa={rev:.2f}  diff={rev-gev:.2f}")
    print(f"Std of per-seed net diff: {np.std(rnets-gnets):.2f}")
    print(f"RPA wins/ties/losses nets: wins={int((rnets>gnets+1e-9).sum())} ties={int((abs(rnets-gnets)<=1e-9).sum())} losses={int((rnets<gnets-1e-9).sum())}")


if __name__ == "__main__":
    main()
