from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI

from .models import PlateSolveRequest, PlateSolveResponse
from .solver import AstrometryServiceSolver

app = FastAPI(title="Arcsecond Plate Solver (Astrometry)", version="0.1.0")

# Single long-lived solver instance (solve is thread-safe).
_SOLVER: AstrometryServiceSolver | None = None


def _get_solver(req: PlateSolveRequest) -> AstrometryServiceSolver:
    global _SOLVER

    cache_dir = req.cache_dir or os.environ.get("ASTROMETRY_CACHE_DIR", "/data/astrometry")
    scales = set(req.scales or [6])

    if _SOLVER is None or _SOLVER.cache_dir != cache_dir or _SOLVER.scales != scales:
        if _SOLVER is not None:
            _SOLVER.close()
        _SOLVER = AstrometryServiceSolver(cache_dir=cache_dir, scales=scales)

    return _SOLVER


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/platesolve", response_model=PlateSolveResponse)
def platesolve(req: PlateSolveRequest):
    if len(req.peaks_xy) < 10:
        return PlateSolveResponse(status="no_match")

    solver = _get_solver(req)
    res = solver.solve(
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
