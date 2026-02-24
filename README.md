# ARC Reseller Radar

Local-first sourcing assistant for evaluating resale opportunities with deterministic ROI math.

## Requirements

- Python 3.11+ (project target)
- `pytest`

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -U pip pytest
```

## Run

Evaluate local records:

```bash
.venv/bin/python -m src.app search "A1990" --input data/listings.json
```

Evaluate via stub eBay client + persistent cache:

```bash
.venv/bin/python -m src.app search "A1990" \
  --market-data data/market_listings.json \
  --cache-path data/search_cache.json \
  --storage-path data/raw_results.json
```

Optional:

- `--output <path>` to save evaluated rows
- `--now-epoch <float>` to fix clock values for deterministic cache tests

## Test

```bash
.venv/bin/python -m pytest -q
```

## Sample Output

See `/Users/tonio/Desktop/ARC Reseller Radar/docs/sample_output.json`.
