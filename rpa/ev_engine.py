"""Expected Value Engine (deterministic economics).

Computes the net expected recovery value for every (transaction, action) pair.

Explicit, auditable formula (no hidden economics):

    recoverable_amount(action, txn) = amount * (1 - recovery_friction)
    gross_expected(action, txn)     = P * recoverable_amount
    action_cost(action)             = action's rupee handling cost (Step 1)
    incentive_cost(action, txn)     = incentive_budget_units * incentive_handling_fee
                                      (0 if the action is not an incentive)
    total_cost(action, txn)         = action_cost + incentive_cost
    net_expected(action, txn)       = gross_expected - total_cost

The formula is configurable through :class:`rpa.config.EVEngineConfig`. Every
component (gross, recoverable, each cost line, net) is returned so it can be
reported and audited — nothing is hidden.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from rpa.config import EVEngineConfig
from rpa.loading import ActionSpec

# Resource keys that identify an incentive component.
INCENTIVE_RESOURCE_KEY = "incentive_budget"


@dataclass
class EVRow:
    """Fully-expanded economics for ONE (transaction, action) pair."""

    transaction_id: str
    action_id: str
    amount: float
    p_recovery: float
    recoverable_amount: float
    gross_expected: float
    action_cost: float
    incentive_cost: float
    total_cost: float
    net_expected: float
    is_no_op: bool = False

    def to_dict(self) -> dict:
        return {
            "transaction_id": self.transaction_id,
            "action_id": self.action_id,
            "amount": round(self.amount, 4),
            "p_recovery": round(self.p_recovery, 6),
            "recoverable_amount": round(self.recoverable_amount, 4),
            "gross_expected": round(self.gross_expected, 4),
            "action_cost": round(self.action_cost, 4),
            "incentive_cost": round(self.incentive_cost, 4),
            "total_cost": round(self.total_cost, 4),
            "net_expected": round(self.net_expected, 4),
            "is_no_op": self.is_no_op,
        }


@dataclass
class EVTable:
    """Full EV table for a batch (deterministic)."""

    rows: list[EVRow]
    actions: list[ActionSpec]
    config: EVEngineConfig

    n_transactions: int | None = None
    n_actions: int | None = None

    def __post_init__(self) -> None:
        if self.n_transactions is None or self.n_actions is None:
            ids = {r.transaction_id for r in self.rows}
            self.n_transactions = len(ids)
            self.n_actions = len(self.actions)
        self._txn_order = list(dict.fromkeys(r.transaction_id for r in self.rows))

    def row_index(self, transaction_id: str) -> int:
        """Return the matrix row index of a transaction (in `transactions` order)."""
        try:
            return self._txn_order.index(transaction_id)
        except ValueError:
            raise KeyError(f"transaction {transaction_id} not in table")

    # -- matrix view: net EV, shape (n_txn, n_action) ----------------------
    @property
    def net_ev_matrix(self) -> np.ndarray:
        return np.array([r.net_expected for r in self.rows]).reshape(
            self.n_transactions,  # type: ignore[arg-type]
            self.n_actions,  # type: ignore[arg-type]
        )

    @property
    def probability_matrix(self) -> np.ndarray:
        return np.array([r.p_recovery for r in self.rows]).reshape(
            self.n_transactions,  # type: ignore[arg-type]
            self.n_actions,  # type: ignore[arg-type]
        )

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([r.to_dict() for r in self.rows])


class EVEngine:
    """Deterministic expected-value calculator."""

    def __init__(self, config: EVEngineConfig = EVEngineConfig()) -> None:  # noqa: B008
        self.config = config

    def _recoverable_amount(self, amount: float) -> float:
        return amount * (1.0 - self.config.recovery_friction)

    def _incentive_cost(self, action: ActionSpec) -> float:
        """Incentive budget consumed times a handling fee; 0 for non-incentives."""
        units = action.resource_units(INCENTIVE_RESOURCE_KEY)
        if units <= 0:
            return 0.0
        return units * self.config.incentive_handling_fee

    def compute_row(
        self,
        txn_id: str,
        amount: float,
        action: ActionSpec,
        p_recovery: float,
    ) -> EVRow:
        p = float(np.clip(p_recovery, self.config.prob_floor, self.config.prob_ceil))
        recoverable = self._recoverable_amount(float(amount))
        gross = p * recoverable
        action_cost = float(action.action_cost)
        incentive_cost = self._incentive_cost(action)
        total_cost = action_cost + incentive_cost
        net = gross - total_cost
        return EVRow(
            transaction_id=txn_id,
            action_id=action.action_id,
            amount=float(amount),
            p_recovery=p,
            recoverable_amount=recoverable,
            gross_expected=gross,
            action_cost=action_cost,
            incentive_cost=incentive_cost,
            total_cost=total_cost,
            net_expected=net,
            is_no_op=action.is_no_op,
        )

    def compute(
        self,
        transactions: pd.DataFrame,
        probabilities: np.ndarray,
        actions: list[ActionSpec],
    ) -> EVTable:
        """Compute EV for a full batch.

        ``probabilities`` is (n_transactions, n_actions), columns aligned to
        ``actions`` order, rows to ``transactions`` order.
        """
        if probabilities.shape != (len(transactions), len(actions)):
            raise ValueError(
                f"probability shape {probabilities.shape} != "
                f"{(len(transactions), len(actions))}"
            )
        txn_ids = transactions["transaction_id"].tolist()
        amounts = transactions["amount"].astype(float).tolist()
        rows: list[EVRow] = []
        for i, txn_id in enumerate(txn_ids):
            for j, action in enumerate(actions):
                rows.append(
                    self.compute_row(txn_id, amounts[i], action, probabilities[i, j])
                )
        return EVTable(
            rows=rows,
            actions=actions,
            config=self.config,
            n_transactions=len(txn_ids),
            n_actions=len(actions),
        )


__all__ = ["EVEngine", "EVEngineConfig", "EVRow", "EVTable"]
