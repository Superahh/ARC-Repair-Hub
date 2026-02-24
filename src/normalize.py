"""Deterministic condition normalization and risk scoring helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConditionNormalization:
    raw: str | None
    normalized: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RiskAssessment:
    score: int
    reasons: tuple[str, ...]


_CONDITION_PATTERNS: dict[str, tuple[str, ...]] = {
    "for_parts": ("for parts", "not working", "as is", "untested"),
    "used": ("used", "pre-owned", "preowned", "fair", "good"),
    "new": ("brand new", "new", "sealed", "unopened"),
    "open_box": ("open box", "open-box", "like new"),
    "refurbished": ("refurbished", "renewed"),
}


def normalize_condition(raw_condition: str | None, title: str = "") -> ConditionNormalization:
    """Normalize listing condition from raw condition and title text."""
    raw_text = (raw_condition or "").strip()
    title_text = title.strip()

    raw_matches = _classify_condition(raw_text.lower())
    title_matches = _classify_condition(title_text.lower())

    if raw_text and raw_matches and title_matches and raw_matches.isdisjoint(title_matches):
        return ConditionNormalization(
            raw=raw_condition,
            normalized="ambiguous",
            reasons=("condition_conflict_title_vs_raw",),
        )

    matches = raw_matches | title_matches
    if not matches:
        if not raw_text:
            return ConditionNormalization(
                raw=raw_condition,
                normalized="unknown",
                reasons=("condition_missing",),
            )
        return ConditionNormalization(
            raw=raw_condition,
            normalized="unknown",
            reasons=("condition_unrecognized",),
        )

    if len(matches) > 1:
        return ConditionNormalization(
            raw=raw_condition,
            normalized="ambiguous",
            reasons=("condition_ambiguous",),
        )

    normalized = next(iter(matches))
    return ConditionNormalization(raw=raw_condition, normalized=normalized, reasons=("ok",))


def assess_risk(
    title: str,
    condition: ConditionNormalization,
    purchase_price: float,
    sale_price_whole: float | None,
    sale_price_parts: float | None,
    sale_prices_estimated: bool = False,
    shipping_missing: bool = False,
) -> RiskAssessment:
    """Compute a deterministic risk score (0-100) and reason tags."""
    score = 0
    reasons: list[str] = []
    title_lower = title.strip().lower()

    if not title.strip():
        score += 10
        reasons.append("title_missing")

    if condition.normalized == "unknown":
        score += 25
        reasons.append("condition_unknown")
    if condition.normalized == "ambiguous":
        score += 40
        reasons.append("condition_ambiguous")
        if "condition_conflict_title_vs_raw" in condition.reasons:
            score += 10
            reasons.append("condition_conflict_title_vs_raw")

    if shipping_missing:
        score += 10
        reasons.append("shipping_missing")

    if sale_prices_estimated:
        score += 20
        reasons.append("sale_prices_estimated")

    if any(
        pattern in title_lower
        for pattern in ("read description", "see description", "unknown", "??", "as-is", "as is")
    ):
        score += 15
        reasons.append("listing_data_messy")

    if sale_price_whole is None and sale_price_parts is None:
        score += 45
        reasons.append("sale_prices_missing")
    elif sale_price_whole is None or sale_price_parts is None:
        score += 15
        reasons.append("sale_prices_partial")

    prices = [price for price in (sale_price_whole, sale_price_parts) if price is not None]
    if len(prices) == 2:
        high = max(prices)
        low = min(prices)
        if low > 0 and (high / low) >= 2.0:
            score += 20
            reasons.append("path_price_divergence")

    if purchase_price > 0 and prices:
        max_sale = max(prices)
        ratio = max_sale / purchase_price
        if ratio >= 3.0:
            score += 15
            reasons.append("price_outlier_high")
        if ratio <= 0.6:
            score += 15
            reasons.append("price_outlier_low")

    if not reasons:
        reasons.append("ok")

    return RiskAssessment(score=min(score, 100), reasons=tuple(reasons))


def _classify_condition(text: str) -> set[str]:
    matches: set[str] = set()
    for normalized, patterns in _CONDITION_PATTERNS.items():
        if any(pattern in text for pattern in patterns):
            matches.add(normalized)
    return matches
