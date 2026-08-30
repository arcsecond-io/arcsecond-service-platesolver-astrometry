# Arcsecond Service: Platesolver (astrometry)

This repository provides a FastAPI plate-solving service for Arcsecond, based
on [astrometry.net](https://astrometry.net) indexes and Neuromorphics
Systems' [astrometry](https://github.com/neuromorphicsystems/astrometry) Python package.

Astrometry index files (~10 GB) are baked into the Docker image at build time
under `/opt/astrometry`. No downloads occur at container startup.

## Run with Docker

```bash
docker run --rm \
  -p 127.0.0.1:8900:8900 \
  arcsecond-service-platesolver-astrometry:latest
```

## Run Natively (Linux/macOS)

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
python -m arcsecond_service_platesolver.main
```

## Run Natively (Windows)

1. Install Python 3.12+.
2. Install Microsoft C++ Build Tools (Desktop development with C++).
3. Install Rust (`rustup`), because `astrometry` may need a local native build when no matching wheel is available.
4. This project pins Windows installs to a Windows-compatible astrometry fork commit from `arcsecond-io/astrometry`.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
python -m arcsecond_service_platesolver.main
```

## Configuration

- `HOST`: bind host (default `0.0.0.0`).
- `PORT`: bind port (default `8900`).
- `LOG_LEVEL`: Uvicorn log level (default `info`).
- `ARCSECOND_PLATESOLVER_SCALES_5200`: comma-separated scale numbers for the 5200 series (default `2,3,4,5,6`).
- `ARCSECOND_PLATESOLVER_SCALES_4100`: comma-separated scale numbers for the 4100 series (default `7,8,9,10,11`).
- `ARCSECOND_PLATESOLVER_SCALES_4200`: comma-separated scale numbers for the 4200 series (default `6,7,8`). Set to empty string to disable a series entirely.
- `ARCSECOND_PLATESOLVER_SOLVE_DEADLINE_SECONDS`: wall-clock ceiling on a single solve (default `50`). Set to `0` or an empty string to disable. Keep it below the calling client's HTTP timeout (the Arcsecond backend uses 60s) so a hopeless field returns a clean `no_match` instead of timing out the connection.

### Solve deadline

A blind or badly-hinted solve can run indefinitely: `astrometry` has no timeout parameter, and
its only early-exit hook (`logodds_callback`) fires when a match is *found* — a hopeless 50-star
field was measured running 70s while calling it zero times. The service therefore runs solves in
a dedicated worker process and kills it when the deadline passes, which is the only mechanism
that actually bounds the C solver. The request then returns `{"status": "no_match"}` and logs
`reason=deadline`. The worker is respawned on the next request (~0.7s cold start against the
full index set, since indexes are mmapped rather than read).

One consequence: solves are serialised. A solve is CPU-bound, and single-flight keeps the kill
unambiguous — it can never destroy a concurrent request's in-flight solve.
