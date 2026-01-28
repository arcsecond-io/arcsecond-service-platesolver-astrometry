from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import astrometry


@dataclass
class SolveResult:
    has_match: bool
    center_ra_deg: float | None = None
    center_dec_deg: float | None = None
    scale_arcsec_per_pixel: float | None = None
    wcs_header: dict | None = None


class AstrometryServiceSolver:
    def __init__(self, cache_dir: str, scales: set[int]):
        self.cache_dir = cache_dir
        self.scales = scales

        self._solver = astrometry.Solver(
            astrometry.series_5200.index_files(
                cache_directory=self.cache_dir,
                scales=self.scales,
            )
        )

    def close(self):
        self._solver.close()

    def solve(
            self,
            peaks_xy: Iterable[Iterable[float]],
            *,
            ra_deg: float | None = None,
            dec_deg: float | None = None,
            radius_deg: float | None = None,
            lower_arcsec_per_pixel: float | None = None,
            upper_arcsec_per_pixel: float | None = None,
    ) -> SolveResult:
        # size_hint = None
        # if lower_arcsec_per_pixel and upper_arcsec_per_pixel:
        #     size_hint = astrometry.SizeHint(
        #         lower_arcsec_per_pixel=lower_arcsec_per_pixel,
        #         upper_arcsec_per_pixel=upper_arcsec_per_pixel,
        #     )
        #
        # position_hint = None
        # if ra_deg is not None and dec_deg is not None and radius_deg is not None:
        #     position_hint = astrometry.PositionHint(
        #         ra_deg=ra_deg,
        #         dec_deg=dec_deg,
        #         radius_deg=radius_deg,
        #     )

        sol = self._solver.solve(
            stars=list(peaks_xy),
            size_hint=None,
            position_hint=None,
            solution_parameters=astrometry.SolutionParameters(),
        )

        if not sol or not sol.has_match():
            return SolveResult(has_match=False)

        bm = sol.best_match()
        wcs = bm.astropy_wcs()
        # ship a plain header dict (portable over JSON)
        header = dict(wcs.to_header())

        return SolveResult(
            has_match=True,
            center_ra_deg=bm.center_ra_deg,
            center_dec_deg=bm.center_dec_deg,
            scale_arcsec_per_pixel=bm.scale_arcsec_per_pixel,
            wcs_header=header,
        )
