from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, HTTPException

from .models import PlateSolveRequest, PlateSolveResponse
from .solver import DEFAULT_SERIES_SCALES, AstrometryServiceSolver, SolverConfig

log = logging.getLogger("arcsecond.platesolver")

# Indexes are baked into the image at this fixed path by download_indexes.py.
# There is intentionally no env-var override: a misconfigured path is how the
# container ends up downloading 10 GB at startup instead of using what's already there.
ASTROMETRY_INDEX_DIR = "/opt/astrometry"

# Single long-lived solver instance, built once at startup. astrometry.Solver.solve() is thread-safe.
_SOLVER: AstrometryServiceSolver | None = None


def _configure_logging() -> None:
    """Wire the `arcsecond.platesolver` logger to stderr at LOG_LEVEL (default INFO).

    Uvicorn does not propagate non-uvicorn loggers by default, so `log.info(...)`
    calls in this module are silently dropped without this setup. Operators rely
    on these lines to see request / result / timing in `docker logs`, so it's
    not optional. Use stderr because that's where stdout buffering quirks bite
    least in containerised Python.
    """
    level_name = os.environ.get("LOG_LEVEL", "info").upper()
    level = getattr(logging, level_name, logging.INFO)
    # `force=True` overrides any prior basicConfig done by uvicorn so we win
    # the handler configuration race regardless of import order.
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    # Keep uvicorn's access log at WARNING — it duplicates information we now log
    # at the application level (one informative line per request), and at INFO it
    # buries the per-request platesolver output.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def _resolve_series_scales() -> dict[str, set[int]]:
    """Read ARCSECOND_PLATESOLVER_SCALES_<SERIES> env vars, falling back to DEFAULT_SERIES_SCALES.

    Setting a series env var to the empty string skips that series entirely (e.g. to drop the
    2MASS index files when you only image at high galactic latitude).
    """
    resolved: dict[str, set[int]] = {}
    for series_name, default_scales in DEFAULT_SERIES_SCALES.items():
        env_key = f"ARCSECOND_PLATESOLVER_SCALES_{series_name}"
        raw = os.environ.get(env_key)
        if raw is None:
            resolved[series_name] = set(default_scales)
            continue
        raw = raw.strip()
        if not raw:
            # Explicitly empty -> skip this series.
            resolved[series_name] = set()
            continue
        try:
            resolved[series_name] = {int(s) for s in raw.split(",") if s.strip()}
        except ValueError as exc:
            raise ValueError(
                f"{env_key} must be a comma-separated list of integers (got {raw!r}): {exc}"
            ) from exc
    return resolved


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    global _SOLVER
    _configure_logging()
    series_scales = _resolve_series_scales()

    log.info("startup: astrometry index dir = %s", ASTROMETRY_INDEX_DIR)
    for series, scales in series_scales.items():
        log.info("startup: series_%s scales = %s", series, sorted(scales) if scales else "(disabled)")

    _SOLVER = AstrometryServiceSolver(SolverConfig(cache_dir=ASTROMETRY_INDEX_DIR, series_scales=series_scales))
    log.info("startup: solver ready")

    try:
        yield
    finally:
        if _SOLVER is not None:
            _SOLVER.close()
            _SOLVER = None
        log.info("shutdown: solver closed")


app = FastAPI(title="Arcsecond Plate Solver (Astrometry)", version="0.1.0", lifespan=_lifespan)


@app.get("/health")
def health():
    return {"ok": True, "solver_ready": _SOLVER is not None}


def _summarise_request(req: PlateSolveRequest) -> str:
    """One-line summary of an incoming request for the request log.

    Includes peak count, peak coordinate bounds (cheap orientation/coordinate-system
    sanity at a glance), and both hints. None values are rendered as `-` to keep
    the line scannable.
    """
    n = len(req.peaks_xy)
    if n:
        xs = [p[0] for p in req.peaks_xy]
        ys = [p[1] for p in req.peaks_xy]
        bounds = f"x=[{min(xs):.0f},{max(xs):.0f}] y=[{min(ys):.0f},{max(ys):.0f}]"
    else:
        bounds = "x=[] y=[]"

    def _f(v):
        return "-" if v is None else f"{v:.4f}"

    return (
        f"peaks={n} {bounds} "
        f"pos=(ra={_f(req.ra_deg)},dec={_f(req.dec_deg)},r={_f(req.radius_deg)}) "
        f"scale=[{_f(req.lower_arcsec_per_pixel)},{_f(req.upper_arcsec_per_pixel)}]"
    )


@app.post("/platesolve", response_model=PlateSolveResponse)
def platesolve(req: PlateSolveRequest):
    """Plate solve a list of star peaks.

    Logging contract (operator-visible at INFO):
      `request  <summary>`           — one line per incoming POST
      `result   match    …`          — one line per successful solve, with elapsed time
      `result   no_match reason=…`   — one line per failed solve, with the reason category
                                       (peaks_too_few / solver_no_match / solver_returned_none)
    The match line includes the solved RA/Dec/scale so a `grep result.*match` in
    the docker logs gives a usable per-call audit trail.
    """
    if _SOLVER is None:
        log.error("request rejected: solver not initialised")
        raise HTTPException(status_code=503, detail="Solver not initialised")

    log.info("request  %s", _summarise_request(req))

    started = time.monotonic()
    n = len(req.peaks_xy)
    if n < 10:
        elapsed_ms = (time.monotonic() - started) * 1000.0
        log.info("result   no_match elapsed=%.1fms reason=peaks_too_few (n=%d)", elapsed_ms, n)
        return PlateSolveResponse(status="no_match")

    try:
        res = _SOLVER.solve(
            req.peaks_xy,
            ra_deg=req.ra_deg,
            dec_deg=req.dec_deg,
            radius_deg=req.radius_deg,
            lower_arcsec_per_pixel=req.lower_arcsec_per_pixel,
            upper_arcsec_per_pixel=req.upper_arcsec_per_pixel,
        )
    except Exception:
        elapsed_ms = (time.monotonic() - started) * 1000.0
        # The traceback is the diagnostic value here — emit the full one at ERROR
        # so we can see what blew up without having to ask the operator to
        # restart with DEBUG. Re-raise as 500 so the client sees an error rather
        # than a misleading no_match.
        log.exception("result   error    elapsed=%.1fms", elapsed_ms)
        raise HTTPException(status_code=500, detail="Solver raised") from None

    elapsed_ms = (time.monotonic() - started) * 1000.0
    if not res.has_match:
        log.info("result   no_match elapsed=%.1fms reason=solver_no_match", elapsed_ms)
        return PlateSolveResponse(status="no_match")

    log.info(
        "result   match    elapsed=%.1fms scale=%.4f ra=%.4f dec=%.4f",
        elapsed_ms,
        res.scale_arcsec_per_pixel,
        res.center_ra_deg,
        res.center_dec_deg,
    )
    return PlateSolveResponse(
        status="match",
        center_ra_deg=res.center_ra_deg,
        center_dec_deg=res.center_dec_deg,
        scale_arcsec_per_pixel=res.scale_arcsec_per_pixel,
        wcs_header=res.wcs_header,
    )


def run():
    uvicorn.run(
        "arcsecond_service_platesolver.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8900")),
        log_level=os.environ.get("LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    run()
