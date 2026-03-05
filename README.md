# Arcsecond Service: Platesolver (astrometry)

This repository provides a FastAPI plate-solving service for Arcsecond, based on [astrometry.net](https://astrometry.net) indexes and Neuromorphics Systems' [astrometry](https://github.com/neuromorphicsystems/astrometry) Python package.

## Run with Docker

```bash
docker run --rm \
  -p 127.0.0.1:8900:8900 \
  -v arcsecond_astrometry_cache:/data/astrometry \
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
4. Point the compiler include path to the compatibility header shipped in this repo.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
$env:CL="/I$PWD\compat\windows\include /FI$PWD\compat\windows\include\astrometry_msvc_compat.h $env:CL"
python -m pip install --upgrade pip
python -m pip install .
python -m arcsecond_service_platesolver.main
```

If install still fails, capture the first compiler error after this shim; there may be additional POSIX headers/macros required by the upstream `astrometry` source build.

## Configuration

- `ASTROMETRY_CACHE_DIR`: explicit cache directory path (highest priority).
- `ASTROMETRY_DATA_ROOT`: root directory used to create `astrometry_cache` under it.
- `HOST`: bind host (default `0.0.0.0`).
- `PORT`: bind port (default `8900`).
- `LOG_LEVEL`: Uvicorn log level (default `info`).

Default cache path behavior:
- If `ASTROMETRY_CACHE_DIR` is set, it is used directly.
- On Windows, defaults to `%LOCALAPPDATA%\Arcsecond\astrometry_cache` (or `%APPDATA%` fallback).
- On Unix-like systems, prefers `/data/astrometry_cache` when writable, otherwise falls back to `$XDG_CACHE_HOME/arcsecond/astrometry_cache` or `~/.cache/arcsecond/astrometry_cache`.
- If the selected location is not writable, falls back to the OS temp directory.
