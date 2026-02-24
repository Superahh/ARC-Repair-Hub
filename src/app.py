"""Application-layer listing evaluation built on the ROI engine."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from src.normalize import assess_risk, normalize_condition
from src.roi import ROIResult, compare_whole_vs_parts
from src.storage import dedupe_key_for_listing, save_results


@dataclass(frozen=True)
class ListingCandidate:
    title: str
    item_id: str
    purchase_price: float
    sale_price_whole: float | None
    sale_price_parts: float | None
    condition_raw: str | None = None
    shipping_cost: float = 0.0
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
    platform_fee_rate: float = 0.13,
    payment_fee_rate: float = 0.03,
    fixed_fee: float = 0.30,
) -> EvaluatedListing:
    """Evaluate one listing against whole-unit and part-out resale paths."""
    condition = normalize_condition(raw_condition=listing.condition_raw, title=listing.title)
    risk = assess_risk(
        title=listing.title,
        condition=condition,
        purchase_price=listing.purchase_price,
        sale_price_whole=listing.sale_price_whole,
        sale_price_parts=listing.sale_price_parts,
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
    platform_fee_rate: float = 0.13,
    payment_fee_rate: float = 0.03,
    fixed_fee: float = 0.30,
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


def search_records(query: str, records: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    """Filter records by query, evaluate ROI paths, and return ranked output rows."""
    query_lower = query.lower().strip()
    candidates: list[ListingCandidate] = []

    for index, record in enumerate(records):
        title = str(record.get("title", ""))
        if query_lower and query_lower not in title.lower():
            continue

        try:
            candidates.append(_candidate_from_record(record, index))
        except ValueError:
            continue

    ranked = rank_listings(candidates)
    return [_evaluated_to_output_row(listing) for listing in ranked]


def _sort_key(listing: EvaluatedListing) -> tuple[int, float, float, str]:
    best = listing.roi_best
    if best.profit is None:
        return (1, float("inf"), float("inf"), listing.item_id)

    roi = best.roi_pct if best.roi_pct is not None else float("-inf")
    return (0, -best.profit, -roi, listing.item_id)


def _candidate_from_record(record: dict[str, object], index: int) -> ListingCandidate:
    title = str(record.get("title", ""))
    item_id = str(record.get("item_id") or record.get("id") or record.get("url") or f"row-{index}")
    purchase_price = _to_float(record.get("purchase_price", record.get("price")), default=None)
    if purchase_price is None:
        raise ValueError("record missing purchase_price/price")

    return ListingCandidate(
        title=title,
        item_id=item_id,
        purchase_price=purchase_price,
        sale_price_whole=_to_float(record.get("sale_price_whole"), default=None),
        sale_price_parts=_to_float(record.get("sale_price_parts"), default=None),
        condition_raw=_to_optional_str(record.get("condition_raw", record.get("condition"))),
        shipping_cost=_to_float(record.get("shipping_cost", record.get("shipping")), default=0.0) or 0.0,
        extra_costs=_to_float(record.get("extra_costs"), default=0.0) or 0.0,
    )


def _evaluated_to_output_row(listing: EvaluatedListing) -> dict[str, object]:
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
        "source": "local",
        "timestamp": None,
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reseller Radar local search evaluator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search", help="Evaluate local listing records")
    search_parser.add_argument("query", help="Search text to match against listing title")
    search_parser.add_argument(
        "--input",
        default="data/listings.json",
        help="Path to local JSON listings file (default: data/listings.json)",
    )
    search_parser.add_argument(
        "--output",
        default=None,
        help="Optional output JSON path to save evaluated rows",
    )

    args = parser.parse_args(argv)

    if args.command == "search":
        rows = search_records(query=args.query, records=_load_records(args.input))
        if args.output:
            save_results(args.output, rows)
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0

    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
