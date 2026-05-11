from __future__ import annotations

import logging
import os
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
    series_scales = _resolve_series_scales()

    log.info("Astrometry index dir: %s", ASTROMETRY_INDEX_DIR)
    for series, scales in series_scales.items():
        log.info("  series_%s scales: %s", series, sorted(scales) if scales else "(disabled)")

    _SOLVER = AstrometryServiceSolver(SolverConfig(cache_dir=ASTROMETRY_INDEX_DIR, series_scales=series_scales))

    try:
        yield
    finally:
        if _SOLVER is not None:
            _SOLVER.close()
            _SOLVER = None


app = FastAPI(title="Arcsecond Plate Solver (Astrometry)", version="0.1.0", lifespan=_lifespan)


@app.get("/health")
def health():
    return {"ok": True, "solver_ready": _SOLVER is not None}


@app.post("/platesolve", response_model=PlateSolveResponse)
def platesolve(req: PlateSolveRequest):
    if _SOLVER is None:
        raise HTTPException(status_code=503, detail="Solver not initialised")

    if len(req.peaks_xy) < 10:
        return PlateSolveResponse(status="no_match")

    res = _SOLVER.solve(
        req.peaks_xy,
        ra_deg=req.ra_deg,
        dec_deg=req.dec_deg,
        radius_deg=req.radius_deg,
        lower_arcsec_per_pixel=req.lower_arcsec_per_pixel,
        upper_arcsec_per_pixel=req.upper_arcsec_per_pixel,
    )

    if not res.has_match:
        return PlateSolveResponse(status="no_match")

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
