"""Shared pytest fixtures for the RPA experiment test suite."""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pytest

from actions import Resource, capacity_dict_from_scenario
from config import Action, GROUND_TRUTH, SCENARIOS
from data_generation import SyntheticDataGenerator
from model import ActionAwareLogistic
from strategies import ACTIONS_LIST


@pytest.fixture(scope="session")
def small_pool() -> List:
    gen = SyntheticDataGenerator(42)
    return gen.generate(60, prefix="test_pool")


@pytest.fixture(scope="session")
def train_txns() -> List:
    gen = SyntheticDataGenerator(7)
    return gen.generate(120, prefix="train")


@pytest.fixture(scope="session")
def val_txns() -> List:
    gen = SyntheticDataGenerator(8)
    return gen.generate(60, prefix="val")


@pytest.fixture(scope="session")
def frozen_model(train_txns, val_txns) -> ActionAwareLogistic:
    model = ActionAwareLogistic()
    model.fit(train_txns, val_txns)
    return model


@pytest.fixture()
def proba_lookup(frozen_model, small_pool) -> Dict[Action, np.ndarray]:
    return frozen_model.predict_proba(small_pool)


def capacity_for(
    incentive: float | None = None,
    human: int | None = None,
    messaging: int | None = None,
    retry: int | None = None,
) -> Dict[Resource, float]:
    """Build a capacity dict on demand (None => unlimited)."""
    caps: Dict[Resource, float] = {}
    if incentive is not None:
        caps[Resource.INCENTIVE_BUDGET] = float(incentive)
    if human is not None:
        caps[Resource.HUMAN_SLOTS] = float(human)
    if messaging is not None:
        caps[Resource.MESSAGING] = float(messaging)
    if retry is not None:
        caps[Resource.RETRY] = float(retry)
    return caps


def scenario_capacity(name: str) -> Dict[Resource, float]:
    return capacity_dict_from_scenario(SCENARIOS[name])