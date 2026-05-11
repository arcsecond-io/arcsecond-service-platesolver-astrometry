#!/usr/bin/env python3
"""Pre-download astrometry index files into the image.

Used during `docker build` to bake indexes into the image at ASTROMETRY_INDEX_DIR.
Can also be run standalone to pre-populate a local cache.
"""
import os
import astrometry

# Must match ASTROMETRY_INDEX_DIR in main.py.
INDEX_DIR = "/opt/astrometry"

SERIES_SCALES: dict[str, set[int]] = {
    "5200": {2, 3, 4, 5, 6},
    "4100": {7, 8, 9, 10, 11},
    "4200": {6, 7, 8},
}

os.makedirs(INDEX_DIR, exist_ok=True)
for series_name, scales in SERIES_SCALES.items():
    series = getattr(astrometry, f"series_{series_name}")
    print(f"Downloading series_{series_name} scales {sorted(scales)} → {INDEX_DIR}", flush=True)
    series.index_files(cache_directory=INDEX_DIR, scales=scales)
    print(f"series_{series_name} done.", flush=True)
print("All indexes ready.", flush=True)
