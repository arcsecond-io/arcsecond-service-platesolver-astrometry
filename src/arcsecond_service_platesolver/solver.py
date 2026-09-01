from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

import astrometry


# Default scale sets per index series. See `astrometry.series_<NAME>.scale_to_sizes` for sizes.
# Sized to keep disk footprint around ~10 GB for varied 30 cm-class setups while covering the
# customer scenarios that motivated this work (M67 at 0.5°, M13 ~0.5°-1°, GC 2MASS at 1° IR).
DEFAULT_SERIES_SCALES: dict[str, set[int]] = {
    # Optical (Tycho-2 + Gaia-DR2 LITE) — primary, narrow-to-mid FOV.
    "5200": {2, 3, 4, 5, 6},   # ~9.3 GB total: covers ~0.2°-3° FOVs.
    # Optical (Tycho-2) — wider fields, much smaller files.
    "4100": {7, 8, 9, 10, 11},  # ~330 MB total: covers ~1°-12° FOVs.
    # 2MASS NIR — required for galactic-plane / dust-extincted targets where Gaia/Tycho are sparse.
    "4200": {6, 7, 8},          # ~550 MB total: 1°-5° FOVs in IR.
}


@dataclass
class SolveResult:
    has_match: bool
    center_ra_deg: float | None = None
    center_dec_deg: float | None = None
    scale_arcsec_per_pixel: float | None = None
    wcs_header: dict | None = None


@dataclass
class SolverConfig:
    cache_dir: str
    series_scales: Mapping[str, set[int]] = field(default_factory=lambda: dict(DEFAULT_SERIES_SCALES))


class AstrometryServiceSolver:
    def __init__(self, config: SolverConfig):
        self.config = config

        index_files: list = []
        for series_name, scales in config.series_scales.items():
            if not scales:
                continue
            series = getattr(astrometry, f"series_{series_name}", None)
            if series is None:
                raise ValueError(f"Unknown astrometry series: {series_name!r}")
            index_files.extend(
                series.index_files(cache_directory=config.cache_dir, scales=set(scales))
            )

        if not index_files:
            raise ValueError(
                "No astrometry index files configured — set at least one ARCSECOND_PLATESOLVER_SCALES_* env var."
            )

        self._solver = astrometry.Solver(index_files)

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
        # Hints dramatically shrink the solver's search space and rescue marginal cases like a
        # short amateur exposure with ~15 detected stars: with no hints astrometry tries every
        # scale and every position in every loaded index, and a 15-star quad pattern doesn't
        # carry enough signal to win that lottery. With hints it converges in milliseconds.
        size_hint = None
        if lower_arcsec_per_pixel and upper_arcsec_per_pixel:
            size_hint = astrometry.SizeHint(
                lower_arcsec_per_pixel=lower_arcsec_per_pixel,
                upper_arcsec_per_pixel=upper_arcsec_per_pixel,
            )

        position_hint = None
        if ra_deg is not None and dec_deg is not None and radius_deg is not None:
            position_hint = astrometry.PositionHint(
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                radius_deg=radius_deg,
            )

        sol = self._solver.solve(
            stars=list(peaks_xy),
            size_hint=size_hint,
            position_hint=position_hint,
            solution_parameters=astrometry.SolutionParameters(
                # Return the first solution instead of combing the rest of the search cone for
                # more. By default the solver keeps going after it has the answer and tunes up
                # (SIP-fits) every further match it accepts, so a rich, well-exposed field is
                # *slower* than a poor one: a clean 50-star frame measured here accumulated 169
                # matches in 40.0s, against 0.23s to stop at the first — same centre and scale
                # to five decimals. That is the real source of the 37s and 47s solves seen in
                # the field; pointing error costs almost nothing by comparison (a 2 deg offset
                # moved a 39.9s solve to 39.1s).
                #
                # Safe because a match is only accepted above output_logodds_threshold (21, i.e.
                # odds of 1e9 to 1), and stopping at the first acceptance is what astrometry.net
                # own solve-field does.
                logodds_callback=lambda _: astrometry.Action.STOP,
            ),
        )

        if not sol or not sol.has_match():
            return SolveResult(has_match=False)

        bm = sol.best_match()
        wcs = bm.astropy_wcs()
        header = dict(wcs.to_header())

        return SolveResult(
            has_match=True,
            center_ra_deg=bm.center_ra_deg,
            center_dec_deg=bm.center_dec_deg,
            scale_arcsec_per_pixel=bm.scale_arcsec_per_pixel,
            wcs_header=header,
        )
