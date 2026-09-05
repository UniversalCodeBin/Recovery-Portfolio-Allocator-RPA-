"""RPA Step 1 data foundation package.

This package implements the data-storage, cleaning, database and validation
foundation for the Revenue Recovery Portfolio Allocator (RPA) project.

It is intentionally self-contained and decoupled from the Step 2-5 model /
optimizer / strategy code that lives in the top-level experiment modules
(``model.py``, ``optimizer.py``, ``strategies.py``, ...). The Step 1 layer only
reuses the *stable, domain-level* constants from ``config`` (the ``Action`` /
``Resource`` enumerations, the canonical category vocabularies, the action
economics and the master data seed). It does **not** import the hidden
ground-truth model, the scenarios, the model hyper-parameters or any strategy
logic -- those remain the exclusive concern of later steps.

Public entry point: :class:`data_core.pipeline.Step1Pipeline`.
"""
from __future__ import annotations

__all__ = ["__version__"]
__version__ = "1.0.0"
