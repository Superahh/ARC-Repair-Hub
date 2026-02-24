# ARC Reseller Radar

Local-first sourcing assistant for evaluating resale opportunities with deterministic ROI math.

## Requirements

- Python 3.11+ (project target)
- `pytest`

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements.txt
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

Evaluate via live eBay Browse API (real adapter):

```bash
export EBAY_CLIENT_ID="..."
export EBAY_CLIENT_SECRET="..."
# optional: export EBAY_USE_SANDBOX=1
# optional: export EBAY_MAX_RETRIES=1

.venv/bin/python -m src.app search "A1990" \
  --use-ebay-api \
  --cache-path data/search_cache.json \
  --storage-path data/raw_results.json
```

Or put credentials in `.env` (auto-loaded by CLI):

```bash
cat > .env <<'ENV'
EBAY_CLIENT_ID=your_client_id
EBAY_CLIENT_SECRET=your_client_secret
ENV
```

Run a one-call auth/search smoke diagnostic:

```bash
.venv/bin/python -m src.app ebay-smoke --query "A1990"
```

Optional:

- `--output <path>` to save evaluated rows
- `--now-epoch <float>` to fix clock values for deterministic cache tests
- `--condition`, `--min-price`, `--max-price`, `--keyword`
- `--ebay-sandbox` (when `--use-ebay-api`)
- `--env-file <path>` to load env vars from a custom file
- `--purchase-price-override <float>` to force a single buy price for ROI evaluation

## Test

```bash
.venv/bin/python -m pytest -q
```

## Sample Output

See `/Users/tonio/Desktop/ARC Reseller Radar/docs/sample_output.json`.
