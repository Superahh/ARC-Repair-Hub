"""Application-layer listing evaluation built on the ROI engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from src.roi import ROIResult, compare_whole_vs_parts


@dataclass(frozen=True)
class ListingCandidate:
    title: str
    item_id: str
    purchase_price: float
    sale_price_whole: float | None
    sale_price_parts: float | None
    shipping_cost: float = 0.0
    extra_costs: float = 0.0


@dataclass(frozen=True)
class EvaluatedListing:
    title: str
    item_id: str
    purchase_price: float
    shipping_cost: float
    total_cost: float
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
        purchase_price=listing.purchase_price,
        shipping_cost=listing.shipping_cost,
        total_cost=comparison.best.total_cost,
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


def _sort_key(listing: EvaluatedListing) -> tuple[int, float, float, str]:
    best = listing.roi_best
    if best.profit is None:
        return (1, float("inf"), float("inf"), listing.item_id)

    roi = best.roi_pct if best.roi_pct is not None else float("-inf")
    return (0, -best.profit, -roi, listing.item_id)
