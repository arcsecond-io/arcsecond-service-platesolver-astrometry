#!/usr/bin/env python3
"""Pre-download astrometry index files into CACHE_DIR.

Used during `docker build` to bake indexes into the image.
Can also be run standalone to pre-populate a local cache.
"""
import os
import astrometry

CACHE_DIR = os.environ.get("ASTROMETRY_CACHE_DIR", "/data/astrometry")
SERIES_SCALES: dict[str, set[int]] = {
    "5200": {2, 3, 4, 5, 6},
    "4100": {7, 8, 9, 10, 11},
    "4200": {6, 7, 8},
}

os.makedirs(CACHE_DIR, exist_ok=True)
for series_name, scales in SERIES_SCALES.items():
    series = getattr(astrometry, f"series_{series_name}")
    print(f"Downloading series_{series_name} scales {sorted(scales)} → {CACHE_DIR}", flush=True)
    series.index_files(cache_directory=CACHE_DIR, scales=scales)
    print(f"series_{series_name} done.", flush=True)
print("All indexes ready.", flush=True)
