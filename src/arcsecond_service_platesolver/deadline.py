from __future__ import annotations

import logging
import multiprocessing as mp
import os
import threading
from multiprocessing.connection import Connection
from typing import Iterable

from .solver import AstrometryServiceSolver, SolveResult, SolverConfig

log = logging.getLogger("arcsecond.platesolver")

# Wall-clock ceiling on a single solve. Must stay below the backend client's HTTP timeout
# (60s) so a hopeless solve comes back as a structured `no_match` rather than as a connection
# timeout, which the client can only report as a service error.
DEFAULT_DEADLINE_SECONDS = 50.0

ENV_DEADLINE = "ARCSECOND_PLATESOLVER_SOLVE_DEADLINE_SECONDS"


def resolve_deadline_seconds() -> float | None:
    """Read the deadline from the environment. Empty string or 0 disables it entirely."""
    raw = os.environ.get(ENV_DEADLINE)
    if raw is None:
        return DEFAULT_DEADLINE_SECONDS
    raw = raw.strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{ENV_DEADLINE} must be a number of seconds (got {raw!r}): {exc}") from exc
    if value < 0:
        raise ValueError(f"{ENV_DEADLINE} must be positive or 0 to disable (got {value})")
    return value or None


class SolveDeadlineExceeded(RuntimeError):
    pass


def _worker(conn: Connection, config: SolverConfig, solver_factory) -> None:
    """Own the astrometry solver and answer solve requests one at a time, forever.

    Runs in a separate process for exactly one reason: this is the only way to abort a solve.
    `Solver.solve()` is a single call into a C extension with no timeout parameter and no
    cancellation point we can reach — see the class docstring on `DeadlineSolver`.
    """
    solver = solver_factory(config)
    conn.send(("ready", None))
    try:
        while True:
            try:
                request = conn.recv()
            except EOFError:
                return
            if request is None:
                return
            peaks_xy, kwargs = request
            try:
                result = solver.solve(peaks_xy, **kwargs)
                conn.send(("ok", result))
            except Exception as exc:  # noqa: BLE001 — reported to the parent, which re-raises.
                conn.send(("error", repr(exc)))
    finally:
        solver.close()


class DeadlineSolver:
    """Runs solves in a killable worker process so a runaway solve cannot pin a core forever.

    Why a process and not a thread or a callback: `astrometry.SolutionParameters` has no
    timeout field, and its only escape hatch — `logodds_callback` — is invoked *when a match
    is found*. Measured against the real index set, a hopeless 50-star field ran 70s and called
    the callback zero times, so a callback-based deadline would fail in precisely the runaway
    case it is meant to bound. `maximum_quads` bounds work by count, not wall clock. That
    leaves killing the OS process as the only mechanism that actually enforces a deadline.

    Solves are serialised: a solve is CPU-bound anyway, and single-flight keeps the kill
    unambiguous (we can never destroy a second request's in-flight solve). A killed worker is
    respawned lazily on the next request; that costs ~0.7s of cold start against a 10 GB index
    set, since the index files are mmapped rather than read.
    """

    def __init__(
            self,
            config: SolverConfig,
            deadline_seconds: float | None,
            solver_factory=AstrometryServiceSolver,
    ):
        self._config = config
        self._deadline_seconds = deadline_seconds
        # Injectable so the tests can exercise the deadline machinery against a stub solver
        # instead of the 10 GB index set. Must be picklable (a module-level class or function),
        # since `spawn` sends it to the worker.
        self._solver_factory = solver_factory
        # `spawn` rather than `fork`: the parent holds a C solver with mmapped index files, and
        # forking that mid-flight would hand the child an inconsistent copy of any internal lock.
        self._ctx = mp.get_context("spawn")
        self._lock = threading.Lock()
        self._proc: mp.process.BaseProcess | None = None
        self._conn: Connection | None = None

    def start(self) -> None:
        """Build the worker eagerly so startup failures surface at startup, not on first solve."""
        with self._lock:
            self._ensure_worker()

    def _ensure_worker(self) -> None:
        if self._proc is not None and self._proc.is_alive():
            return
        self._teardown_worker()

        parent_conn, child_conn = self._ctx.Pipe()
        proc = self._ctx.Process(
            target=_worker,
            args=(child_conn, self._config, self._solver_factory),
            daemon=True,
        )
        proc.start()
        child_conn.close()

        # The worker signals readiness only after its indexes are loaded. Failing to build the
        # solver is fatal and must not be silently retried on every request. A worker that dies
        # in its constructor closes the pipe instead of answering, which surfaces as EOF on
        # recv() — report that as the startup failure it is rather than leaking an EOFError.
        ready = False
        detail = "timed out after 120s"
        try:
            if parent_conn.poll(120.0):
                status, payload = parent_conn.recv()
                ready = status == "ready"
                detail = payload
        except EOFError:
            detail = "worker exited before signalling readiness"

        if not ready:
            if proc.is_alive():
                proc.kill()
            proc.join()
            parent_conn.close()
            raise RuntimeError(
                f"Plate solver worker failed to start: {detail} (exit code {proc.exitcode})"
            )

        self._proc = proc
        self._conn = parent_conn

    def _teardown_worker(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        if self._proc is not None:
            if self._proc.is_alive():
                self._proc.kill()
            self._proc.join()
            self._proc = None

    def solve(self, peaks_xy: Iterable[Iterable[float]], **kwargs) -> SolveResult:
        with self._lock:
            self._ensure_worker()
            assert self._conn is not None

            # Normalise to plain lists: the request crosses a pipe, so it has to pickle, and
            # callers may hand us numpy rows.
            peaks = [[float(x), float(y)] for x, y in peaks_xy]

            try:
                self._conn.send((peaks, kwargs))
            except (BrokenPipeError, OSError) as exc:
                self._teardown_worker()
                raise RuntimeError(f"Plate solver worker died before the solve started: {exc}") from exc

            if not self._conn.poll(self._deadline_seconds):
                # The worker is wedged inside the C solver and will never come back on its own.
                self._teardown_worker()
                raise SolveDeadlineExceeded(
                    f"Solve exceeded the {self._deadline_seconds:.0f}s deadline"
                )

            try:
                status, payload = self._conn.recv()
            except (EOFError, OSError) as exc:
                self._teardown_worker()
                raise RuntimeError(f"Plate solver worker died mid-solve: {exc}") from exc

        if status == "error":
            raise RuntimeError(f"Plate solver worker raised: {payload}")
        return payload

    def close(self) -> None:
        with self._lock:
            if self._conn is not None and self._proc is not None and self._proc.is_alive():
                try:
                    self._conn.send(None)
                    self._proc.join(5.0)
                except (BrokenPipeError, OSError):
                    pass
            self._teardown_worker()
