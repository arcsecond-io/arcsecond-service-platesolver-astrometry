"""Stub solvers for the deadline tests.

These live in their own importable module, not in the test file, because `DeadlineSolver`
uses the `spawn` start method: the factory is pickled by qualified name and re-imported in
the worker process, so it has to be resolvable there.
"""
from __future__ import annotations

import os
import time

from arcsecond_service_platesolver.solver import SolveResult, SolverConfig


class HangingSolver:
    """Never returns within any test's patience — stands in for a runaway C solve."""

    def __init__(self, config: SolverConfig):
        self.config = config

    def solve(self, peaks_xy, **kwargs) -> SolveResult:
        time.sleep(3600)
        raise AssertionError("unreachable")

    def close(self) -> None:
        pass


class EchoSolver:
    """Returns immediately, encoding what it received so the parent can assert on it.

    `center_ra_deg` carries the peak count and `center_dec_deg` the number of non-None
    kwargs, which is enough to prove the request crossed the pipe intact.
    """

    def __init__(self, config: SolverConfig):
        self.config = config

    def solve(self, peaks_xy, **kwargs) -> SolveResult:
        return SolveResult(
            has_match=True,
            center_ra_deg=float(len(peaks_xy)),
            center_dec_deg=float(sum(1 for v in kwargs.values() if v is not None)),
            scale_arcsec_per_pixel=kwargs.get("lower_arcsec_per_pixel"),
            wcs_header={"PID": os.getpid()},
        )

    def close(self) -> None:
        pass


class RaisingSolver:
    """Blows up inside the worker, to check the failure crosses the pipe as an error."""

    def __init__(self, config: SolverConfig):
        self.config = config

    def solve(self, peaks_xy, **kwargs) -> SolveResult:
        raise ValueError("stub solver exploded")

    def close(self) -> None:
        pass


class SlowSolver:
    """Takes a second — long enough to outlive a sub-second deadline, short enough for a test."""

    def __init__(self, config: SolverConfig):
        self.config = config

    def solve(self, peaks_xy, **kwargs) -> SolveResult:
        time.sleep(1.0)
        return SolveResult(has_match=True, center_ra_deg=1.0, center_dec_deg=2.0)

    def close(self) -> None:
        pass


class UnbuildableSolver:
    """Fails in its constructor, i.e. before the worker ever signals readiness."""

    def __init__(self, config: SolverConfig):
        raise RuntimeError("no index files")

    def solve(self, peaks_xy, **kwargs) -> SolveResult:  # pragma: no cover - never built
        raise AssertionError("unreachable")

    def close(self) -> None:  # pragma: no cover - never built
        pass
