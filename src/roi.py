"""Deterministic ROI engine for resale path comparison."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.config import DEFAULT_FIXED_FEE, DEFAULT_PAYMENT_FEE_RATE, DEFAULT_PLATFORM_FEE_RATE


@dataclass(frozen=True)
class ROIResult:
    sale_price: float | None
    revenue_net: float | None
    total_cost: float
    profit: float | None
    roi_pct: float | None
    reason: str


@dataclass(frozen=True)
class CompareResult:
    best_path: Literal["whole", "parts", "none"]
    whole: ROIResult
    parts: ROIResult
    best: ROIResult


def net_revenue(
    sale_price: float,
    platform_fee_rate: float = DEFAULT_PLATFORM_FEE_RATE,
    payment_fee_rate: float = DEFAULT_PAYMENT_FEE_RATE,
    fixed_fee: float = DEFAULT_FIXED_FEE,
) -> float:
    """Compute post-fee revenue from a sale price."""
    fee_rate = platform_fee_rate + payment_fee_rate
    return sale_price - (sale_price * fee_rate) - fixed_fee


def compute_roi(
    purchase_price: float,
    sale_price: float | None,
    shipping_cost: float = 0.0,
    extra_costs: float = 0.0,
    platform_fee_rate: float = DEFAULT_PLATFORM_FEE_RATE,
    payment_fee_rate: float = DEFAULT_PAYMENT_FEE_RATE,
    fixed_fee: float = DEFAULT_FIXED_FEE,
) -> ROIResult:
    """Compute ROI for one sale estimate path."""
    if purchase_price <= 0:
        raise ValueError("purchase_price must be > 0")

    total_cost = purchase_price + shipping_cost + extra_costs

    if sale_price is None:
        return ROIResult(
            sale_price=None,
            revenue_net=None,
            total_cost=total_cost,
            profit=None,
            roi_pct=None,
            reason="sale_price_missing",
        )

    revenue = net_revenue(
        sale_price=sale_price,
        platform_fee_rate=platform_fee_rate,
        payment_fee_rate=payment_fee_rate,
        fixed_fee=fixed_fee,
    )
    profit = revenue - total_cost
    roi_pct = (profit / total_cost) * 100

    return ROIResult(
        sale_price=sale_price,
        revenue_net=revenue,
        total_cost=total_cost,
        profit=profit,
        roi_pct=roi_pct,
        reason="ok",
    )


def compare_whole_vs_parts(
    purchase_price: float,
    sale_price_whole: float | None,
    sale_price_parts: float | None,
    shipping_cost: float = 0.0,
    extra_costs: float = 0.0,
    platform_fee_rate: float = DEFAULT_PLATFORM_FEE_RATE,
    payment_fee_rate: float = DEFAULT_PAYMENT_FEE_RATE,
    fixed_fee: float = DEFAULT_FIXED_FEE,
) -> CompareResult:
    """Compare whole-unit resale against part-out and choose the best path."""
    whole = compute_roi(
        purchase_price=purchase_price,
        sale_price=sale_price_whole,
        shipping_cost=shipping_cost,
        extra_costs=extra_costs,
        platform_fee_rate=platform_fee_rate,
        payment_fee_rate=payment_fee_rate,
        fixed_fee=fixed_fee,
    )
    parts = compute_roi(
        purchase_price=purchase_price,
        sale_price=sale_price_parts,
        shipping_cost=shipping_cost,
        extra_costs=extra_costs,
        platform_fee_rate=platform_fee_rate,
        payment_fee_rate=payment_fee_rate,
        fixed_fee=fixed_fee,
    )

    whole_ok = whole.profit is not None
    parts_ok = parts.profit is not None

    if whole_ok and parts_ok:
        assert whole.profit is not None and parts.profit is not None
        if parts.profit > whole.profit:
            return CompareResult(best_path="parts", whole=whole, parts=parts, best=parts)
        if whole.profit > parts.profit:
            return CompareResult(best_path="whole", whole=whole, parts=parts, best=whole)

        assert whole.roi_pct is not None and parts.roi_pct is not None
        if parts.roi_pct > whole.roi_pct:
            return CompareResult(best_path="parts", whole=whole, parts=parts, best=parts)
        return CompareResult(best_path="whole", whole=whole, parts=parts, best=whole)

    if whole_ok:
        return CompareResult(best_path="whole", whole=whole, parts=parts, best=whole)
    if parts_ok:
        return CompareResult(best_path="parts", whole=whole, parts=parts, best=parts)

    best = ROIResult(
        sale_price=None,
        revenue_net=None,
        total_cost=whole.total_cost,
        profit=None,
        roi_pct=None,
        reason=f"none_computable:{whole.reason}|{parts.reason}",
    )
    return CompareResult(best_path="none", whole=whole, parts=parts, best=best)
