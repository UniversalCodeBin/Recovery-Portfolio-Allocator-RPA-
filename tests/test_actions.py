from __future__ import annotations

import pytest

from actions import (
    Resource,
    ResourceState,
    ResourceVector,
    action_resource_vector,
    capacity_dict_from_scenario,
)
from config import SCENARIOS, Action


def test_resource_vector_total_units():
    rv = ResourceVector(retry=1.0, messaging=1.0, incentive=50.0, human=1.0)
    # retry*1 + messaging*2 + incentive/50 + human*20
    assert rv.total_units() == pytest.approx(1 + 2 + 1 + 20)


def test_action_resource_vectors():
    assert action_resource_vector(Action.NO_INTERVENTION).total_units() == 0.0
    assert action_resource_vector(Action.INCENTIVE).incentive == 50.0
    assert action_resource_vector(Action.HUMAN_ESCALATION).human == 1.0
    assert action_resource_vector(Action.RETRY).retry == 1.0


def test_resource_state_capacity_tracking():
    rs = ResourceState(retry=2.0, messaging=None, incentive=None, human=1.0)
    assert rs.can_apply(ResourceVector(retry=1.0))
    assert rs.can_apply(ResourceVector(human=1.0))
    assert not rs.can_apply(ResourceVector(human=2.0))
    assert rs.can_apply(ResourceVector(retry=3.0)) is False
    rs.apply(ResourceVector(retry=1.0))
    assert rs.retry == pytest.approx(1.0)
    assert not rs.can_apply(ResourceVector(retry=1.0, human=2.0))  # human exceeds
    assert rs.can_apply(ResourceVector(retry=1.0, human=1.0))  # exactly fits


def test_resource_state_infinite_when_none():
    rs = ResourceState(retry=None, messaging=None, incentive=None, human=None)
    assert rs.can_apply(ResourceVector(retry=1e9, human=99, incentive=1e12))


def test_capacity_from_scenario():
    caps = capacity_dict_from_scenario(SCENARIOS["A"])
    assert caps.get(Resource.INCENTIVE_BUDGET) == pytest.approx(35 * 50.0)
    assert Resource.HUMAN_SLOTS not in caps  # unlimited


def test_utilization_from_capacity():
    state = ResourceState(retry=None, messaging=None, incentive=50.0, human=None)
    state.apply(ResourceVector(incentive=50.0))
    util = state.utilization({Resource.INCENTIVE_BUDGET: 50.0})
    assert util[Resource.INCENTIVE_BUDGET] == pytest.approx(1.0)


def test_scenarios_have_intended_capacity_fractions():
    caps_a = capacity_dict_from_scenario(SCENARIOS["A"])
    caps_c = capacity_dict_from_scenario(SCENARIOS["C"])
    caps_e = capacity_dict_from_scenario(SCENARIOS["E"])
    # A binds only incentive (35), C binds incentive (40) + human (8) + msg (60)
    assert caps_a[Resource.INCENTIVE_BUDGET] == pytest.approx(35 * 50.0)
    assert caps_c[Resource.INCENTIVE_BUDGET] == pytest.approx(40 * 50.0)
    assert Resource.HUMAN_SLOTS in caps_c
    assert Resource.MESSAGING in caps_c
    assert caps_e[Resource.INCENTIVE_BUDGET] > caps_c[Resource.INCENTIVE_BUDGET] * 2
