"""Tests for the /platesolve response contract.

The route is called directly rather than through TestClient: the app's lifespan builds a real
solver over the 10 GB index set, which is exactly what these tests must not need.
"""
from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException

from arcsecond_service_platesolver import main
from arcsecond_service_platesolver.deadline import SolveDeadlineExceeded
from arcsecond_service_platesolver.models import PlateSolveRequest
from arcsecond_service_platesolver.solver import SolveResult

# The route rejects anything under 10 peaks before it reaches the solver.
PEAKS = [[float(i), float(i * 2)] for i in range(12)]


class _StubSolver:
    def __init__(self, result=None, raises=None):
        self._result = result
        self._raises = raises
        self.calls: list[dict] = []

    def solve(self, peaks_xy, **kwargs):
        self.calls.append({"peaks_xy": peaks_xy, **kwargs})
        if self._raises is not None:
            raise self._raises
        return self._result


@pytest.fixture
def install_solver(monkeypatch):
    def _install(stub):
        monkeypatch.setattr(main, "_SOLVER", stub)
        return stub

    return _install


def test_deadline_returns_no_match_not_an_error(install_solver, caplog):
    """A deadline is 'could not solve in time', not a service fault.

    The client renders a 5xx to the observer as a broken plate solver, but treats no_match as
    'try another frame' — which is the truthful outcome when a field simply will not solve.
    """
    install_solver(_StubSolver(raises=SolveDeadlineExceeded("Solve exceeded the 50s deadline")))

    with caplog.at_level(logging.WARNING, logger="arcsecond.platesolver"):
        response = main.platesolve(PlateSolveRequest(peaks_xy=PEAKS))

    assert response.status == "no_match"
    assert response.center_ra_deg is None
    assert response.wcs_header is None
    assert "reason=deadline" in caplog.text


def test_solver_crash_is_still_a_500(install_solver):
    """Only the deadline is downgraded to no_match; a genuine fault must stay a fault."""
    install_solver(_StubSolver(raises=RuntimeError("solver blew up")))

    with pytest.raises(HTTPException) as excinfo:
        main.platesolve(PlateSolveRequest(peaks_xy=PEAKS))
    assert excinfo.value.status_code == 500


def test_match_is_returned_in_full(install_solver):
    install_solver(_StubSolver(result=SolveResult(
        has_match=True,
        center_ra_deg=202.4,
        center_dec_deg=47.2,
        scale_arcsec_per_pixel=1.23,
        wcs_header={"CTYPE1": "RA---TAN"},
    )))

    response = main.platesolve(PlateSolveRequest(peaks_xy=PEAKS))

    assert response.status == "match"
    assert response.center_ra_deg == 202.4
    assert response.scale_arcsec_per_pixel == 1.23
    assert response.wcs_header == {"CTYPE1": "RA---TAN"}


def test_no_match_is_returned_as_no_match(install_solver):
    install_solver(_StubSolver(result=SolveResult(has_match=False)))
    assert main.platesolve(PlateSolveRequest(peaks_xy=PEAKS)).status == "no_match"


def test_too_few_peaks_never_reaches_the_solver(install_solver):
    stub = install_solver(_StubSolver(result=SolveResult(has_match=False)))
    response = main.platesolve(PlateSolveRequest(peaks_xy=[[1.0, 2.0], [3.0, 4.0]]))
    assert response.status == "no_match"
    assert stub.calls == []


def test_hints_are_forwarded_to_the_solver(install_solver):
    stub = install_solver(_StubSolver(result=SolveResult(has_match=False)))
    main.platesolve(PlateSolveRequest(
        peaks_xy=PEAKS,
        ra_deg=10.0,
        dec_deg=41.0,
        radius_deg=15.0,
        lower_arcsec_per_pixel=0.9,
        upper_arcsec_per_pixel=1.1,
    ))
    call = stub.calls[0]
    assert call["ra_deg"] == 10.0
    assert call["radius_deg"] == 15.0
    assert call["lower_arcsec_per_pixel"] == 0.9


def test_uninitialised_solver_is_a_503(monkeypatch):
    monkeypatch.setattr(main, "_SOLVER", None)
    with pytest.raises(HTTPException) as excinfo:
        main.platesolve(PlateSolveRequest(peaks_xy=PEAKS))
    assert excinfo.value.status_code == 503
