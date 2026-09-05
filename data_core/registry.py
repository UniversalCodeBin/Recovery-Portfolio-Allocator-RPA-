"""Configuration-as-data registry for recovery actions and resource constraints.

Recovery actions are represented as *data* (rows of ``recovery_actions``) rather
than scattered hard-coded strings, so the action vocabulary can be changed by
editing one place (``config`` / this registry) and reloading. The same principle
applies to resource constraints.

This module is the bridge between the experiment's ``Action``/``Resource``
enumerations and the relational tables: it converts ``config.ACTION_SPECS`` into
``RecoveryAction`` rows and provides sensible default resource constraints,
without importing any Step 2-5 logic.
"""
from __future__ import annotations

from typing import Dict, List

from config import ACTION_SPECS, Action, Resource

from .config import ACTIONS_ENABLED
from .models import RecoveryAction, ResourceConstraint

# Human-readable descriptions for each action type (configuration, not logic).
_ACTION_DESCRIPTIONS: Dict[str, str] = {
    Action.NO_INTERVENTION.value: "No recovery attempt; leave the transaction as-is.",
    Action.RETRY.value: "Automatically retry the failed payment with the acquirer.",
    Action.PAYMENT_LINK.value: "Send a fresh payment link to the customer.",
    Action.CUSTOMER_MESSAGE.value: "Notify the customer about the failed payment.",
    Action.INCENTIVE.value: "Offer a monetary incentive/discount on retry.",
    Action.HUMAN_ESCALATION.value: "Hand the case to a human agent for follow-up.",
}

# Stable, human-friendly action_id keys (1:1 with Action enum, in order).
_ACTION_IDS: Dict[str, str] = {
    Action.NO_INTERVENTION.value: "act_no_intervention",
    Action.RETRY.value: "act_retry",
    Action.PAYMENT_LINK.value: "act_payment_link",
    Action.CUSTOMER_MESSAGE.value: "act_customer_message",
    Action.INCENTIVE.value: "act_incentive",
    Action.HUMAN_ESCALATION.value: "act_human_escalation",
}


def build_recovery_actions() -> List[RecoveryAction]:
    """Materialize the canonical recovery-action configuration as data rows.

    Cost and per-action resource consumption come from ``config.ACTION_SPECS``
    (single source of truth). The ``enabled`` flag and the ordering are
    configurable, but the set is intentionally extensible: to add an action,
    extend the ``Action`` enum and ``ACTION_SPECS`` in ``config``.
    """
    actions: List[RecoveryAction] = []
    for action in Action:  # preserves enum definition order
        spec = ACTION_SPECS[action]
        resource_req: Dict[str, float] = {
            res.value: getattr(spec, attr)
            for res, attr in [
                (Resource.RETRY, "res_retry"),
                (Resource.MESSAGING, "res_messaging"),
                (Resource.INCENTIVE_BUDGET, "res_incentive"),
                (Resource.HUMAN_SLOTS, "res_human"),
            ]
            if getattr(spec, attr) > 0
        }
        actions.append(
            RecoveryAction(
                action_id=_ACTION_IDS[action.value],
                action_type=action.value,
                description=_ACTION_DESCRIPTIONS.get(action.value, ""),
                action_cost=float(spec.rupee_cost),
                resource_requirements=resource_req,
                enabled=ACTIONS_ENABLED.get(action.value, True),
            )
        )
    return actions


def action_lookup() -> Dict[str, RecoveryAction]:
    return {a.action_type: a for a in build_recovery_actions()}


def default_resource_constraints() -> List[ResourceConstraint]:
    """Sensible default resource limits (independent of experiment scenarios).

    These are *reference* constraints that document the resource vocabulary.
    Per-experiment/per-scenario limits belong to Step 5 (the optimizer) and are
    intentionally NOT encoded here as a single "right" answer.
    """
    limits: Dict[str, float] = {
        Resource.INCENTIVE_BUDGET.value: 5000.0,
        Resource.HUMAN_SLOTS.value: 50.0,
        Resource.MESSAGING.value: 2000.0,
        Resource.RETRY.value: 2000.0,
    }
    descriptions: Dict[str, str] = {
        Resource.INCENTIVE_BUDGET.value: "Total incentive budget (rupees).",
        Resource.HUMAN_SLOTS.value: "Human-agent escalation slots (count).",
        Resource.MESSAGING.value: "Outbound messaging channel capacity (count).",
        Resource.RETRY.value: "Automated retry capacity (count).",
    }
    return [
        ResourceConstraint(
            constraint_id=f"rc_{res}",
            resource_type=res,
            limit_value=float(limits[res]),
            description=descriptions[res],
        )
        for res in limits
    ]


__all__ = ["build_recovery_actions", "action_lookup", "default_resource_constraints"]
