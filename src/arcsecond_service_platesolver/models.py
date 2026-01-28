from __future__ import annotations

from typing import Literal, Optional, List

from pydantic import BaseModel, Field


class PlateSolveRequest(BaseModel):
    peaks_xy: List[List[float]] = Field(..., description="List of [x, y] star centroids in pixel coordinates.")
    scales: Optional[List[int]] = Field(default=[6], description="Astrometry index scales to use (e.g. [6]).")
    cache_dir: Optional[str] = Field(default=None, description="Override solver cache dir (index files).")

    # Optional hints (add when you want)
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
