"""Application-layer listing evaluation built on the ROI engine."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from src.cache import FileSearchCache
from src.config import (
    DEFAULT_CACHE_PATH,
    DEFAULT_FIXED_FEE,
    DEFAULT_LISTINGS_INPUT_PATH,
    DEFAULT_PAYMENT_FEE_RATE,
    DEFAULT_PLATFORM_FEE_RATE,
    DEFAULT_RAW_RESULTS_PATH,
)
from src.estimation import estimate_sale_prices
from src.ebay_client import ListingRecord, RealEbayClient, SearchRequest, StubEbayClient
from src.normalize import assess_risk, normalize_condition
from src.roi import ROIResult, compare_whole_vs_parts
from src.search_service import search_and_store
from src.storage import dedupe_key_for_listing, save_results

DEFAULT_ENV_FILE_PATH = ".env"


@dataclass(frozen=True)
class ListingCandidate:
    title: str
    item_id: str
    purchase_price: float
    sale_price_whole: float | None
    sale_price_parts: float | None
    sale_prices_estimated: bool = False
    condition_raw: str | None = None
    shipping_cost: float = 0.0
    shipping_missing: bool = False
    extra_costs: float = 0.0


@dataclass(frozen=True)
class EvaluatedListing:
    title: str
    item_id: str
    condition_raw: str | None
    condition_normalized: str
    purchase_price: float
    shipping_cost: float
    total_cost: float
    risk_score: int
    risk_reasons: tuple[str, ...]
    roi_whole: ROIResult
    roi_parts: ROIResult
    roi_best: ROIResult
    best_path: Literal["whole", "parts", "none"]


def evaluate_listing(
    listing: ListingCandidate,
    platform_fee_rate: float = DEFAULT_PLATFORM_FEE_RATE,
    payment_fee_rate: float = DEFAULT_PAYMENT_FEE_RATE,
    fixed_fee: float = DEFAULT_FIXED_FEE,
) -> EvaluatedListing:
    """Evaluate one listing against whole-unit and part-out resale paths."""
    condition = normalize_condition(raw_condition=listing.condition_raw, title=listing.title)
    risk = assess_risk(
        title=listing.title,
        condition=condition,
        purchase_price=listing.purchase_price,
        sale_price_whole=listing.sale_price_whole,
        sale_price_parts=listing.sale_price_parts,
        sale_prices_estimated=listing.sale_prices_estimated,
        shipping_missing=listing.shipping_missing,
    )
    comparison = compare_whole_vs_parts(
        purchase_price=listing.purchase_price,
        sale_price_whole=listing.sale_price_whole,
        sale_price_parts=listing.sale_price_parts,
        shipping_cost=listing.shipping_cost,
        extra_costs=listing.extra_costs,
        platform_fee_rate=platform_fee_rate,
        payment_fee_rate=payment_fee_rate,
        fixed_fee=fixed_fee,
    )

    return EvaluatedListing(
        title=listing.title,
        item_id=listing.item_id,
        condition_raw=listing.condition_raw,
        condition_normalized=condition.normalized,
        purchase_price=listing.purchase_price,
        shipping_cost=listing.shipping_cost,
        total_cost=comparison.best.total_cost,
        risk_score=risk.score,
        risk_reasons=risk.reasons,
        roi_whole=comparison.whole,
        roi_parts=comparison.parts,
        roi_best=comparison.best,
        best_path=comparison.best_path,
    )


def rank_listings(
    listings: Sequence[ListingCandidate],
    platform_fee_rate: float = DEFAULT_PLATFORM_FEE_RATE,
    payment_fee_rate: float = DEFAULT_PAYMENT_FEE_RATE,
    fixed_fee: float = DEFAULT_FIXED_FEE,
) -> list[EvaluatedListing]:
    """Evaluate and rank listings by best computable ROI opportunity."""
    evaluated = [
        evaluate_listing(
            listing=listing,
            platform_fee_rate=platform_fee_rate,
            payment_fee_rate=payment_fee_rate,
            fixed_fee=fixed_fee,
        )
        for listing in listings
    ]
    return sorted(evaluated, key=_sort_key)


def search_records(
    query: str,
    records: Sequence[dict[str, object]],
    source: str = "local",
    warning: str | None = None,
    timestamp: float | None = None,
    purchase_price_override: float | None = None,
    condition: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    keywords: Sequence[str] = (),
) -> list[dict[str, object]]:
    """Filter records by query, evaluate ROI paths, and return ranked output rows."""
    query_lower = query.lower().strip()
    condition_filter = condition.strip().lower() if condition else None
    keyword_filters = tuple(keyword.strip().lower() for keyword in keywords if keyword.strip())
    candidates: list[ListingCandidate] = []

    for index, record in enumerate(records):
        title = str(record.get("title", ""))
        title_lower = title.lower()
        if query_lower and query_lower not in title_lower:
            continue

        try:
            candidate = _candidate_from_record(record, index, purchase_price_override)
        except ValueError:
            continue

        if condition_filter:
            record_condition = str(record.get("condition_raw", record.get("condition")) or "").lower()
            if condition_filter not in record_condition:
                continue

        if min_price is not None and candidate.purchase_price < min_price:
            continue
        if max_price is not None and candidate.purchase_price > max_price:
            continue

        if keyword_filters and not all(keyword in title_lower for keyword in keyword_filters):
            continue

        candidates.append(candidate)

    ranked = rank_listings(candidates)
    return [
        _evaluated_to_output_row(listing, source=source, warning=warning, timestamp=timestamp)
        for listing in ranked
    ]


def _sort_key(listing: EvaluatedListing) -> tuple[int, float, float, str]:
    best = listing.roi_best
    if best.profit is None:
        return (1, float("inf"), float("inf"), listing.item_id)

    roi = best.roi_pct if best.roi_pct is not None else float("-inf")
    return (0, -best.profit, -roi, listing.item_id)


def _candidate_from_record(
    record: dict[str, object],
    index: int,
    purchase_price_override: float | None = None,
) -> ListingCandidate:
    title = str(record.get("title", ""))
    item_id = str(record.get("item_id") or record.get("id") or record.get("url") or f"row-{index}")
    if purchase_price_override is not None:
        purchase_price = purchase_price_override
    else:
        purchase_price = _to_float(record.get("purchase_price", record.get("price")), default=None)
    if purchase_price is None:
        raise ValueError("record missing purchase_price/price")

    condition_raw = _to_optional_str(record.get("condition_raw", record.get("condition")))
    sale_price_whole = _to_float(record.get("sale_price_whole"), default=None)
    sale_price_parts = _to_float(record.get("sale_price_parts"), default=None)
    sale_prices_estimated = False
    if sale_price_whole is None or sale_price_parts is None:
        estimated_whole, estimated_parts = estimate_sale_prices(
            purchase_price=purchase_price,
            condition_raw=condition_raw,
            title=title,
        )
        sale_price_whole = estimated_whole if sale_price_whole is None else sale_price_whole
        sale_price_parts = estimated_parts if sale_price_parts is None else sale_price_parts
        sale_prices_estimated = True

    shipping_raw = record.get("shipping_cost", record.get("shipping"))
    shipping_missing = shipping_raw is None

    return ListingCandidate(
        title=title,
        item_id=item_id,
        purchase_price=purchase_price,
        sale_price_whole=sale_price_whole,
        sale_price_parts=sale_price_parts,
        sale_prices_estimated=sale_prices_estimated,
        condition_raw=condition_raw,
        shipping_cost=_to_float(shipping_raw, default=0.0) or 0.0,
        shipping_missing=shipping_missing,
        extra_costs=_to_float(record.get("extra_costs"), default=0.0) or 0.0,
    )


def _evaluated_to_output_row(
    listing: EvaluatedListing,
    source: str = "local",
    warning: str | None = None,
    timestamp: float | None = None,
) -> dict[str, object]:
    return {
        "title": listing.title,
        "item_id": listing.item_id,
        "price": listing.purchase_price,
        "shipping": listing.shipping_cost,
        "condition_raw": listing.condition_raw,
        "condition_normalized": listing.condition_normalized,
        "ROI_whole": _roi_to_row(listing.roi_whole),
        "ROI_parts": _roi_to_row(listing.roi_parts),
        "ROI_best": _roi_to_row(listing.roi_best),
        "best_path": listing.best_path,
        "risk_score": listing.risk_score,
        "reason_tags": list(listing.risk_reasons),
        "source": source,
        "warning": warning,
        "timestamp": timestamp,
        "dedupe_key": dedupe_key_for_listing({"item_id": listing.item_id}),
    }


def _roi_to_row(result: ROIResult) -> dict[str, float | None | str]:
    return {
        "sale_price": result.sale_price,
        "revenue_net": result.revenue_net,
        "total_cost": result.total_cost,
        "profit": result.profit,
        "roi_pct": result.roi_pct,
        "reason": result.reason,
    }


def _to_float(value: object, default: float | None) -> float | None:
    if value is None:
        return default
    return float(value)


def _to_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _load_records(path: str | Path) -> list[dict[str, object]]:
    input_path = Path(path)
    if not input_path.exists():
        return []

    raw_data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(raw_data, list):
        raise ValueError("input JSON must be a list of records")
    return [dict(item) for item in raw_data]


def _load_listing_records(path: str | Path) -> list[ListingRecord]:
    rows = _load_records(path)
    records: list[ListingRecord] = []
    for row in rows:
        records.append(
            ListingRecord(
                title=str(row["title"]),
                item_id=str(row["item_id"]),
                price=float(row["price"]),
                shipping=_to_float(row.get("shipping"), default=None),
                condition_raw=_to_optional_str(row.get("condition_raw", row.get("condition"))),
                url=_to_optional_str(row.get("url")),
                sale_price_whole=_to_float(row.get("sale_price_whole"), default=None),
                sale_price_parts=_to_float(row.get("sale_price_parts"), default=None),
            )
        )
    return records


def _listing_records_to_rows(records: Sequence[ListingRecord]) -> list[dict[str, object]]:
    return [
        {
            "title": item.title,
            "item_id": item.item_id,
            "price": item.price,
            "shipping": item.shipping,
            "condition_raw": item.condition_raw,
            "url": item.url,
            "sale_price_whole": item.sale_price_whole,
            "sale_price_parts": item.sale_price_parts,
        }
        for item in records
    ]


def _build_search_output(
    rows: list[dict[str, object]],
    *,
    query: str,
    source: str,
    warning: str | None,
    timestamp: float | None,
    include_meta: bool = False,
) -> list[dict[str, object]] | dict[str, object]:
    """Return list output by default, with an optional diagnostic envelope."""
    should_envelope = include_meta or (not rows and warning is not None)
    if not should_envelope:
        return rows

    return {
        "ok": warning is None,
        "query": query,
        "count": len(rows),
        "source": source,
        "warning": warning,
        "timestamp": timestamp,
        "rows": rows,
    }


def run_ebay_smoke(
    query: str,
    sandbox: bool,
    condition: str | None,
    min_price: float | None,
    max_price: float | None,
    keywords: Sequence[str],
) -> tuple[dict[str, object], int]:
    auth_mode = _detect_ebay_auth_mode()
    try:
        client = RealEbayClient.from_env(sandbox=sandbox)
        records = client.search(
            SearchRequest(
                query=query,
                condition=condition,
                min_price=min_price,
                max_price=max_price,
                keywords=tuple(keywords),
            )
        )
    except Exception as exc:
        payload = {
            "ok": False,
            "query": query,
            "sandbox": sandbox,
            "auth_mode": auth_mode,
            "result_count": 0,
            "sample_item_id": None,
            "sample_title": None,
            "error": f"{exc.__class__.__name__}: {exc}",
        }
        return payload, 1

    sample = records[0] if records else None
    payload = {
        "ok": True,
        "query": query,
        "sandbox": sandbox,
        "auth_mode": auth_mode,
        "result_count": len(records),
        "sample_item_id": sample.item_id if sample else None,
        "sample_title": sample.title if sample else None,
        "error": None,
    }
    return payload, 0


def _detect_ebay_auth_mode() -> str:
    if os.getenv("EBAY_ACCESS_TOKEN", "").strip():
        return "access_token"
    if os.getenv("EBAY_CLIENT_ID", "").strip() and os.getenv("EBAY_CLIENT_SECRET", "").strip():
        return "oauth_client_credentials"
    return "unknown"


def load_env_file(path: str | Path = DEFAULT_ENV_FILE_PATH, override: bool = False) -> dict[str, str]:
    """Load KEY=VALUE pairs from a .env-style file into os.environ."""
    env_path = Path(path)
    if not env_path.exists():
        return {}

    loaded: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        if not override and key in os.environ:
            continue

        os.environ[key] = value
        loaded[key] = value

    return loaded


def validate_ebay_credentials() -> str | None:
    """Return an actionable preflight error if eBay auth configuration is missing."""
    if os.getenv("EBAY_ACCESS_TOKEN", "").strip():
        return None

    missing: list[str] = []
    if not os.getenv("EBAY_CLIENT_ID", "").strip():
        missing.append("EBAY_CLIENT_ID")
    if not os.getenv("EBAY_CLIENT_SECRET", "").strip():
        missing.append("EBAY_CLIENT_SECRET")

    if not missing:
        return None

    joined = ", ".join(missing)
    return (
        "Missing eBay credentials. Set EBAY_ACCESS_TOKEN or both EBAY_CLIENT_ID "
        f"and EBAY_CLIENT_SECRET. Missing: {joined}."
    )


def validate_purchase_price_override(value: float | None) -> str | None:
    if value is None:
        return None
    if value <= 0:
        return "purchase_price_override must be greater than 0."
    return None


def has_ebay_credentials() -> bool:
    return _detect_ebay_auth_mode() != "unknown"


def _resolve_search_mode(
    use_ebay_api: bool,
    market_data_path: str | None,
    input_explicit: bool,
    credentials_available: bool,
) -> Literal["live", "market", "local"]:
    if market_data_path:
        return "market"
    if use_ebay_api:
        return "live"
    if input_explicit:
        return "local"
    if credentials_available:
        return "live"
    return "local"


def _arg_provided(argv: Sequence[str], flag: str) -> bool:
    for token in argv:
        if token == flag or token.startswith(f"{flag}="):
            return True
    return False


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description="Reseller Radar local search evaluator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search", help="Evaluate local listing records")
    search_parser.add_argument("query", help="Search text to match against listing title")
    search_parser.add_argument(
        "--input",
        default=DEFAULT_LISTINGS_INPUT_PATH,
        help=f"Path to local JSON listings file (default: {DEFAULT_LISTINGS_INPUT_PATH})",
    )
    search_parser.add_argument(
        "--output",
        default=None,
        help="Optional output JSON path to save evaluated rows",
    )
    search_parser.add_argument(
        "--market-data",
        default=None,
        help="Optional JSON catalog used by the stub eBay client",
    )
    search_parser.add_argument(
        "--cache-path",
        default=DEFAULT_CACHE_PATH,
        help="Cache file path for eBay search caching",
    )
    search_parser.add_argument(
        "--storage-path",
        default=DEFAULT_RAW_RESULTS_PATH,
        help="Storage file path for raw searched rows",
    )
    search_parser.add_argument(
        "--now-epoch",
        type=float,
        default=None,
        help="Optional fixed clock for deterministic cache behavior",
    )
    search_parser.add_argument(
        "--use-ebay-api",
        action="store_true",
        help="Use live eBay Browse API instead of local input/market-data",
    )
    search_parser.add_argument(
        "--ebay-sandbox",
        action="store_true",
        help="Use eBay sandbox endpoints when --use-ebay-api is enabled",
    )
    search_parser.add_argument("--condition", default=None, help="Optional condition filter")
    search_parser.add_argument("--min-price", type=float, default=None, help="Optional min purchase price")
    search_parser.add_argument("--max-price", type=float, default=None, help="Optional max purchase price")
    search_parser.add_argument(
        "--keyword",
        dest="keywords",
        action="append",
        default=[],
        help="Optional keyword filter; repeat flag for multiple keywords",
    )
    search_parser.add_argument(
        "--purchase-price-override",
        type=float,
        default=None,
        help="Optional override purchase price applied to all evaluated listings",
    )
    search_parser.add_argument(
        "--include-meta",
        action="store_true",
        help="Wrap search output with metadata (query/source/warning/timestamp/count)",
    )
    search_parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_FILE_PATH,
        help=f"Optional .env file path (default: {DEFAULT_ENV_FILE_PATH})",
    )
    smoke_parser = subparsers.add_parser("ebay-smoke", help="Run one eBay auth/search smoke check")
    smoke_parser.add_argument("--query", default="A1990", help="Smoke query (default: A1990)")
    smoke_parser.add_argument(
        "--ebay-sandbox",
        action="store_true",
        help="Use eBay sandbox endpoints for smoke check",
    )
    smoke_parser.add_argument("--condition", default=None, help="Optional condition filter")
    smoke_parser.add_argument("--min-price", type=float, default=None, help="Optional min purchase price")
    smoke_parser.add_argument("--max-price", type=float, default=None, help="Optional max purchase price")
    smoke_parser.add_argument(
        "--keyword",
        dest="keywords",
        action="append",
        default=[],
        help="Optional keyword filter; repeat flag for multiple keywords",
    )
    smoke_parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_FILE_PATH,
        help=f"Optional .env file path (default: {DEFAULT_ENV_FILE_PATH})",
    )

    args = parser.parse_args(argv_list)
    load_env_file(args.env_file)

    if args.command == "search":
        override_error = validate_purchase_price_override(args.purchase_price_override)
        if override_error:
            payload = {
                "ok": False,
                "command": "search",
                "query": args.query,
                "error": override_error,
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 1

        search_mode = _resolve_search_mode(
            use_ebay_api=args.use_ebay_api,
            market_data_path=args.market_data,
            input_explicit=_arg_provided(argv_list, "--input"),
            credentials_available=has_ebay_credentials(),
        )

        output_source = "local"
        output_warning: str | None = None
        output_timestamp: float | None = None

        if search_mode == "live":
            preflight_error = validate_ebay_credentials()
            if preflight_error:
                payload = {
                    "ok": False,
                    "command": "search",
                    "query": args.query,
                    "auth_mode": _detect_ebay_auth_mode(),
                    "error": preflight_error,
                }
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 1

            run = search_and_store(
                client=RealEbayClient.from_env(sandbox=args.ebay_sandbox),
                cache=FileSearchCache(args.cache_path),
                storage_path=args.storage_path,
                query=args.query,
                condition=args.condition,
                min_price=args.min_price,
                max_price=args.max_price,
                keywords=tuple(args.keywords),
                now_epoch=args.now_epoch,
            )
            rows = search_records(
                query="",
                records=_listing_records_to_rows(run.records),
                source=run.source,
                warning=run.warning,
                timestamp=run.fetched_at_epoch,
                purchase_price_override=args.purchase_price_override,
            )
            output_source = run.source
            output_warning = run.warning
            output_timestamp = run.fetched_at_epoch
        elif search_mode == "market":
            run = search_and_store(
                client=StubEbayClient(_load_listing_records(args.market_data)),
                cache=FileSearchCache(args.cache_path),
                storage_path=args.storage_path,
                query=args.query,
                condition=args.condition,
                min_price=args.min_price,
                max_price=args.max_price,
                keywords=tuple(args.keywords),
                now_epoch=args.now_epoch,
            )
            rows = search_records(
                query="",
                records=_listing_records_to_rows(run.records),
                source=run.source,
                warning=run.warning,
                timestamp=run.fetched_at_epoch,
                purchase_price_override=args.purchase_price_override,
            )
            output_source = run.source
            output_warning = run.warning
            output_timestamp = run.fetched_at_epoch
        else:
            rows = search_records(
                query=args.query,
                records=_load_records(args.input),
                purchase_price_override=args.purchase_price_override,
                condition=args.condition,
                min_price=args.min_price,
                max_price=args.max_price,
                keywords=tuple(args.keywords),
            )
            output_source = "local"
            output_warning = None
            output_timestamp = None

        if args.output:
            save_results(args.output, rows)
        payload = _build_search_output(
            rows,
            query=args.query,
            source=output_source,
            warning=output_warning,
            timestamp=output_timestamp,
            include_meta=args.include_meta,
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "ebay-smoke":
        preflight_error = validate_ebay_credentials()
        if preflight_error:
            payload = {
                "ok": False,
                "query": args.query,
                "sandbox": args.ebay_sandbox,
                "auth_mode": _detect_ebay_auth_mode(),
                "result_count": 0,
                "sample_item_id": None,
                "sample_title": None,
                "error": preflight_error,
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 1

        payload, exit_code = run_ebay_smoke(
            query=args.query,
            sandbox=args.ebay_sandbox,
            condition=args.condition,
            min_price=args.min_price,
            max_price=args.max_price,
            keywords=tuple(args.keywords),
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return exit_code

    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
