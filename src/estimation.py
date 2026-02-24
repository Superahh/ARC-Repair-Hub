"""Deterministic sale-price estimation helpers."""

from __future__ import annotations

from typing import Final

_FOR_PARTS_MARKERS: Final[tuple[str, ...]] = ("for parts", "not working", "as-is", "as is", "untested")
_USED_MARKERS: Final[tuple[str, ...]] = ("used", "pre-owned", "preowned")
_NEWISH_MARKERS: Final[tuple[str, ...]] = ("new", "open box", "open-box", "refurbished", "renewed")


def estimate_sale_prices(
    purchase_price: float,
    condition_raw: str | None = None,
    title: str = "",
) -> tuple[float, float]:
    """Estimate (whole, parts) sale prices from purchase and listing context."""
    text = f"{(condition_raw or '').lower()} {title.lower()}"

    if any(marker in text for marker in _FOR_PARTS_MARKERS):
        whole_multiplier = 1.35
        parts_multiplier = 1.60
    elif any(marker in text for marker in _USED_MARKERS):
        whole_multiplier = 1.60
        parts_multiplier = 1.85
    elif any(marker in text for marker in _NEWISH_MARKERS):
        whole_multiplier = 1.40
        parts_multiplier = 1.50
    else:
        whole_multiplier = 1.50
        parts_multiplier = 1.75

    sale_whole = round(purchase_price * whole_multiplier, 2)
    sale_parts = round(purchase_price * parts_multiplier, 2)
    return sale_whole, sale_parts
