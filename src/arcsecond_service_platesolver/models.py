from __future__ import annotations

from typing import Literal, Optional, List

from pydantic import BaseModel, Field


class PlateSolveRequest(BaseModel):
    peaks_xy: List[List[float]] = Field(..., description="List of [x, y] star centroids in pixel coordinates.")
    # Deprecated: kept for backward compatibility with old clients. Ignored by the server —
    # the index scales are now configured via ARCSECOND_PLATESOLVER_SCALES_<SERIES> env vars
    # and a single solver is built once at startup, so per-request scale selection is no longer
    # meaningful. New clients should omit this field.
    scales: Optional[List[int]] = Field(
        default=None,
        description="DEPRECATED — ignored. Configure scales server-side via env vars.",
        deprecated=True,
    )

    # Optional hints — pass them whenever you have any prior pointing or scale information,
    # they shrink the search space drastically and rescue marginal cases.
    ra_deg: Optional[float] = None
    dec_deg: Optional[float] = None
    radius_deg: Optional[float] = None
    lower_arcsec_per_pixel: Optional[float] = None
    upper_arcsec_per_pixel: Optional[float] = None


class PlateSolveResponse(BaseModel):
    status: Literal["match", "no_match"]
    center_ra_deg: Optional[float] = None
    center_dec_deg: Optional[float] = None
    scale_arcsec_per_pixel: Optional[float] = None
    wcs_header: Optional[dict] = None
