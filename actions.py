"""Action definitions, costs, resource consumption and resource-state helpers.

An action is one of config.Action. Each has a rupee cost and a per-unit
consumption of shared resources (see config.ACTION_SPECS). This module also
implements a small ResourceState container used by strategies to track
capacity during allocation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence

from config import ACTION_SPECS, Action, Resource, action_consumption


@dataclass(frozen=True)
class ResourceVector:
    """Immutable per-units vector of resource consumption."""

    retry: float = 0.0
    messaging: float = 0.0
    incentive: float = 0.0
    human: float = 0.0

    def total_units(self) -> float:
        """Weighted scalar 'size' of resource consumption for EV-ratio tie-breaks.

        Uses rupee-equivalent weights so units are commensurable.
        """
        return (
            self.retry * 1.0
            + self.messaging * 2.0
            + self.incentive / 50.0
            + self.human * 20.0
        )


def action_cost(action: Action) -> float:
    """Rupee cost of applying an action once (0 for no intervention)."""
    return ACTION_SPECS[action].rupee_cost


def action_resource_vector(action: Action) -> ResourceVector:
    cons = ACTION_SPECS[action]
    return ResourceVector(
        retry=cons.res_retry,
        messaging=cons.res_messaging,
        incentive=cons.res_incentive,
        human=cons.res_human,
    )


@dataclass
class ResourceState:
    """Mutable running state of remaining resource capacity during allocation."""

    retry: Optional[float]
    messaging: Optional[float]
    incentive: Optional[float]
    human: Optional[float]

    def can_apply(self, rv: ResourceVector) -> bool:
        if self.retry is not None and rv.retry > self.retry + 1e-9:
            return False
        if self.messaging is not None and rv.messaging > self.messaging + 1e-9:
            return False
        if self.incentive is not None and rv.incentive > self.incentive + 1e-9:
            return False
        if self.human is not None and rv.human > self.human + 1e-9:
            return False
        return True

    def apply(self, rv: ResourceVector) -> None:
        if self.retry is not None:
            self.retry -= rv.retry
        if self.messaging is not None:
            self.messaging -= rv.messaging
        if self.incentive is not None:
            self.incentive -= rv.incentive
        if self.human is not None:
            self.human -= rv.human

    def snapshot(self) -> Dict[Resource, float]:
        out: Dict[Resource, float] = {}
        if self.retry is not None:
            out[Resource.RETRY] = self.retry
        if self.messaging is not None:
            out[Resource.MESSAGING] = self.messaging
        if self.incentive is not None:
            out[Resource.INCENTIVE_BUDGET] = self.incentive
        if self.human is not None:
            out[Resource.HUMAN_SLOTS] = self.human
        return out

    def utilization(self, capacity: Dict[Resource, float]) -> Dict[Resource, float]:
        """Fraction of each resource consumed (0..1), based on original capacity."""
        used: Dict[Resource, float] = {}
        for res, cap in capacity.items():
            remaining = self.snapshot().get(res, 0.0)
            used_count = max(0.0, cap - remaining)
            used[res] = used_count / cap if cap > 0 else 0.0
        return used


def build_initial_resource_state(
    capacity: Dict[Resource, float],
) -> ResourceState:
    return ResourceState(
        retry=capacity.get(Resource.RETRY),
        messaging=capacity.get(Resource.MESSAGING),
        incentive=capacity.get(Resource.INCENTIVE_BUDGET),
        human=capacity.get(Resource.HUMAN_SLOTS),
    )


def capacity_dict_from_scenario(scenario) -> Dict[Resource, float]:
    """Build a Resource->capacity dict from a config.Scenario.

    None capacity entries are omitted (unlimited).
    """
    caps: Dict[Resource, float] = {}
    if scenario.retry_capacity is not None:
        caps[Resource.RETRY] = float(scenario.retry_capacity)
    if scenario.messaging_capacity is not None:
        caps[Resource.MESSAGING] = float(scenario.messaging_capacity)
    if scenario.incentive_budget is not None:
        caps[Resource.INCENTIVE_BUDGET] = float(scenario.incentive_budget)
    if scenario.human_slots is not None:
        caps[Resource.HUMAN_SLOTS] = float(scenario.human_slots)
    return caps


def all_capacity_resources(scenario) -> Sequence[Resource]:
    return sorted(capacity_dict_from_scenario(scenario).keys(), key=lambda r: r.value)
