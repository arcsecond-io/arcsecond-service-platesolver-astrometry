from __future__ import annotations

import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, HTTPException

from .models import PlateSolveRequest, PlateSolveResponse
from .solver import DEFAULT_SERIES_SCALES, AstrometryServiceSolver, SolverConfig

log = logging.getLogger("arcsecond.platesolver")

# Single long-lived solver instance, built once at startup. astrometry.Solver.solve() is thread-safe.
_SOLVER: AstrometryServiceSolver | None = None


def _resolve_cache_dir() -> str:
    cache_dir_override = os.environ.get("ASTROMETRY_CACHE_DIR")
    if cache_dir_override:
        cache_dir = Path(cache_dir_override)
    else:
        data_root_override = os.environ.get("ASTROMETRY_DATA_ROOT")
        if data_root_override:
            data_root = Path(data_root_override)
        elif os.name == "nt":
            local_appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
            if local_appdata:
                data_root = Path(local_appdata) / "Arcsecond"
            else:
                data_root = Path.home() / "AppData" / "Local" / "Arcsecond"
        else:
            default_root = Path("/data")
            if default_root.exists() and os.access(default_root, os.W_OK):
                data_root = default_root
            else:
                xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
                if xdg_cache_home:
                    data_root = Path(xdg_cache_home) / "arcsecond"
                else:
                    data_root = Path.home() / ".cache" / "arcsecond"
        cache_dir = data_root / "astrometry_cache"

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        cache_dir = Path(tempfile.gettempdir()) / "arcsecond" / "astrometry_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        log.warning("Falling back to temporary cache directory: %s", cache_dir)

    return str(cache_dir)


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
    cache_dir = _resolve_cache_dir()
    series_scales = _resolve_series_scales()

    log.info("Astrometry cache dir: %s", cache_dir)
    for series, scales in series_scales.items():
        log.info("  series_%s scales: %s", series, sorted(scales) if scales else "(disabled)")

    # Build the solver up front. The astrometry package downloads any missing index files into
    # the cache here — first run can take a while (multi-GB for the default scales).
    _SOLVER = AstrometryServiceSolver(SolverConfig(cache_dir=cache_dir, series_scales=series_scales))

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
