"""Tests for the solve deadline.

The point under test is the one thing the astrometry library cannot do for us: abandon a solve
that will not finish. Every test here uses a stub solver, so the suite needs no index files.
"""
from __future__ import annotations

import threading
import time

import pytest

from arcsecond_service_platesolver.deadline import (
    DEFAULT_DEADLINE_SECONDS,
    ENV_DEADLINE,
    DeadlineSolver,
    SolveDeadlineExceeded,
    resolve_deadline_seconds,
)
from arcsecond_service_platesolver.solver import SolverConfig

from .stubs import EchoSolver, HangingSolver, RaisingSolver, SlowSolver, UnbuildableSolver

CONFIG = SolverConfig(cache_dir="/nonexistent", series_scales={})

PEAKS = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]


@pytest.fixture
def make_solver():
    """Build DeadlineSolvers and guarantee their workers are reaped even if a test fails."""
    built: list[DeadlineSolver] = []

    def _make(factory, deadline_seconds: float | None = 1.0) -> DeadlineSolver:
        solver = DeadlineSolver(CONFIG, deadline_seconds=deadline_seconds, solver_factory=factory)
        built.append(solver)
        return solver

    yield _make

    for solver in built:
        solver.close()


# --- resolve_deadline_seconds -------------------------------------------------------------

def test_deadline_defaults_when_unset(monkeypatch):
    monkeypatch.delenv(ENV_DEADLINE, raising=False)
    assert resolve_deadline_seconds() == DEFAULT_DEADLINE_SECONDS


def test_default_deadline_leaves_room_under_the_client_timeout():
    # The backend client allows 60s. The deadline has to fire first, otherwise the client sees a
    # dead connection instead of the structured no_match this whole mechanism exists to return.
    assert DEFAULT_DEADLINE_SECONDS < 60.0


@pytest.mark.parametrize("raw,expected", [("12", 12.0), ("7.5", 7.5), ("  30  ", 30.0)])
def test_deadline_read_from_env(monkeypatch, raw, expected):
    monkeypatch.setenv(ENV_DEADLINE, raw)
    assert resolve_deadline_seconds() == expected


@pytest.mark.parametrize("raw", ["", "   ", "0"])
def test_deadline_disabled_by_empty_or_zero(monkeypatch, raw):
    monkeypatch.setenv(ENV_DEADLINE, raw)
    assert resolve_deadline_seconds() is None


@pytest.mark.parametrize("raw", ["soon", "-5"])
def test_deadline_rejects_nonsense(monkeypatch, raw):
    monkeypatch.setenv(ENV_DEADLINE, raw)
    with pytest.raises(ValueError, match=ENV_DEADLINE):
        resolve_deadline_seconds()


# --- the deadline itself ------------------------------------------------------------------

def test_hanging_solve_is_abandoned_at_the_deadline(make_solver):
    solver = make_solver(HangingSolver, deadline_seconds=1.0)
    solver.start()

    started = time.monotonic()
    with pytest.raises(SolveDeadlineExceeded):
        solver.solve(PEAKS)
    elapsed = time.monotonic() - started

    # Without the deadline this call sleeps for an hour. The upper bound is generous because CI
    # is slow, but it still proves we returned on the deadline rather than on the solve.
    assert 1.0 <= elapsed < 15.0


def test_hanging_worker_is_actually_killed(make_solver):
    solver = make_solver(HangingSolver, deadline_seconds=1.0)
    solver.start()
    proc = solver._proc
    assert proc is not None and proc.is_alive()

    with pytest.raises(SolveDeadlineExceeded):
        solver.solve(PEAKS)

    # The whole point: the process is gone, not merely abandoned still burning a core.
    assert not proc.is_alive()
    assert solver._proc is None


def test_service_recovers_after_a_breach(make_solver):
    """A deadline must cost one request, not the service."""
    solver = make_solver(HangingSolver, deadline_seconds=1.0)
    solver.start()
    first_pid = solver._proc.pid

    with pytest.raises(SolveDeadlineExceeded):
        solver.solve(PEAKS)

    # The breach killed the worker, so the next request builds a fresh one — which is what lets
    # this swap take effect at all, and is precisely the recovery being asserted.
    solver._solver_factory = EchoSolver
    result = solver.solve(PEAKS)

    assert result.has_match
    assert solver._proc.pid != first_pid


def test_repeated_breaches_do_not_wedge_the_solver(make_solver):
    solver = make_solver(HangingSolver, deadline_seconds=1.0)
    for _ in range(3):
        with pytest.raises(SolveDeadlineExceeded):
            solver.solve(PEAKS)
        assert solver._proc is None


def test_solve_completing_inside_the_deadline_is_untouched(make_solver):
    solver = make_solver(SlowSolver, deadline_seconds=30.0)
    result = solver.solve(PEAKS)
    assert result.has_match
    assert (result.center_ra_deg, result.center_dec_deg) == (1.0, 2.0)


def test_deadline_can_be_disabled(make_solver):
    """deadline_seconds=None must wait indefinitely, not treat None as 'expire immediately'."""
    solver = make_solver(SlowSolver, deadline_seconds=None)
    result = solver.solve(PEAKS)
    assert result.has_match


# --- request/response plumbing ------------------------------------------------------------

def test_request_crosses_the_pipe_intact(make_solver):
    solver = make_solver(EchoSolver, deadline_seconds=10.0)
    result = solver.solve(
        PEAKS,
        ra_deg=10.0,
        dec_deg=41.0,
        radius_deg=15.0,
        lower_arcsec_per_pixel=1.0,
        upper_arcsec_per_pixel=1.1,
    )
    assert result.center_ra_deg == len(PEAKS)   # peaks arrived, all of them
    assert result.center_dec_deg == 5.0          # all five hints arrived
    assert result.scale_arcsec_per_pixel == 1.0


def test_solve_runs_in_another_process(make_solver):
    solver = make_solver(EchoSolver, deadline_seconds=10.0)
    import os

    result = solver.solve(PEAKS)
    assert result.wcs_header["PID"] not in (os.getpid(), None)


def test_non_list_peaks_are_normalised(make_solver):
    """Callers hand us numpy rows; tuples stand in for them here. They must still pickle."""
    solver = make_solver(EchoSolver, deadline_seconds=10.0)
    result = solver.solve(((1.0, 2.0), (3.0, 4.0)))
    assert result.center_ra_deg == 2.0


def test_worker_exception_surfaces_as_an_error(make_solver):
    solver = make_solver(RaisingSolver, deadline_seconds=10.0)
    with pytest.raises(RuntimeError, match="stub solver exploded"):
        solver.solve(PEAKS)


def test_worker_that_cannot_be_built_fails_loudly(make_solver):
    solver = make_solver(UnbuildableSolver, deadline_seconds=10.0)
    with pytest.raises(RuntimeError, match="failed to start|no index files"):
        solver.start()


# --- lifecycle ----------------------------------------------------------------------------

def test_start_is_idempotent(make_solver):
    solver = make_solver(EchoSolver, deadline_seconds=10.0)
    solver.start()
    pid = solver._proc.pid
    solver.start()
    assert solver._proc.pid == pid


def test_close_reaps_the_worker(make_solver):
    solver = make_solver(EchoSolver, deadline_seconds=10.0)
    solver.start()
    proc = solver._proc
    solver.close()
    assert not proc.is_alive()
    assert solver._proc is None
    solver.close()  # idempotent


def test_concurrent_solves_are_serialised(make_solver):
    """Two threads must both get correct answers, never a crossed or half-read pipe."""
    solver = make_solver(EchoSolver, deadline_seconds=30.0)
    solver.start()

    results: dict[int, object] = {}
    errors: list[BaseException] = []

    def run(n: int) -> None:
        try:
            results[n] = solver.solve([[float(i), float(i)] for i in range(n)])
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(n,)) for n in (11, 12, 13, 14)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    assert not errors
    # Each thread's own peak count came back to it — no interleaving on the shared pipe.
    assert {n: r.center_ra_deg for n, r in results.items()} == {11: 11.0, 12: 12.0, 13: 13.0, 14: 14.0}
