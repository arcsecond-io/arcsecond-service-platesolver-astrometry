"""Tests for how the solve request is put together.

`AstrometryServiceSolver.__init__` needs the index files, so these build the object without
running it and swap in a fake inner solver. That keeps the suite free of the 10 GB index set
while still pinning the parameters we hand to astrometry.
"""
from __future__ import annotations

import astrometry
import pytest

from arcsecond_service_platesolver.solver import AstrometryServiceSolver, SolverConfig

PEAKS = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]


class _FakeInnerSolver:
    """Captures the call and reports no match, which is enough to inspect the parameters."""

    def __init__(self):
        self.call = None

    def solve(self, *, stars, size_hint, position_hint, solution_parameters):
        self.call = {
            "stars": stars,
            "size_hint": size_hint,
            "position_hint": position_hint,
            "solution_parameters": solution_parameters,
        }
        return None

    def close(self):
        pass


@pytest.fixture
def solver():
    obj = AstrometryServiceSolver.__new__(AstrometryServiceSolver)
    obj.config = SolverConfig(cache_dir="/nonexistent", series_scales={})
    obj._solver = _FakeInnerSolver()
    return obj


def test_solver_stops_at_the_first_accepted_match(solver):
    """The single most expensive default in the library.

    Left alone, the solver keeps combing the search cone after it already has a solution and
    SIP-fits every further match it accepts. Measured on a clean 50-star field, that was 169
    matches in 40.0s versus 0.23s to stop at the first — same centre and scale to five decimals.
    Rich, well-exposed frames were the slow ones, which is what made real solves take 37-47s.
    """
    solver.solve(PEAKS)

    callback = solver._solver.call["solution_parameters"].logodds_callback
    # Whatever it is handed — the callback only ever fires once a match has been accepted.
    assert callback([305.7]) == astrometry.Action.STOP
    assert callback([305.7, 280.0]) == astrometry.Action.STOP


def test_both_hints_are_passed_when_available(solver):
    solver.solve(
        PEAKS,
        ra_deg=45.0,
        dec_deg=20.0,
        radius_deg=15.0,
        lower_arcsec_per_pixel=0.9,
        upper_arcsec_per_pixel=1.1,
    )
    call = solver._solver.call

    assert call["position_hint"].ra_deg == 45.0
    assert call["position_hint"].radius_deg == 15.0
    assert call["size_hint"].lower_arcsec_per_pixel == 0.9
    assert call["size_hint"].upper_arcsec_per_pixel == 1.1


def test_position_hint_needs_all_three_components(solver):
    """A centre without a radius is not a usable cone, so it must not be half-passed."""
    solver.solve(PEAKS, ra_deg=45.0, dec_deg=20.0)
    assert solver._solver.call["position_hint"] is None


def test_size_hint_needs_both_bounds(solver):
    solver.solve(PEAKS, lower_arcsec_per_pixel=0.9)
    assert solver._solver.call["size_hint"] is None


def test_no_hints_is_a_blind_solve(solver):
    solver.solve(PEAKS)
    call = solver._solver.call
    assert call["position_hint"] is None
    assert call["size_hint"] is None


def test_no_solution_is_reported_as_no_match(solver):
    result = solver.solve(PEAKS)
    assert result.has_match is False
    assert result.center_ra_deg is None
    assert result.wcs_header is None


def test_peaks_are_passed_through_as_a_list(solver):
    solver.solve(iter(PEAKS))
    assert solver._solver.call["stars"] == PEAKS
