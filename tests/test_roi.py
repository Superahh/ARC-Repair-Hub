import pytest

from src.roi import compare_whole_vs_parts, compute_roi


def test_positive_roi_case_prefers_parts():
    result = compare_whole_vs_parts(
        purchase_price=200,
        sale_price_whole=400,
        sale_price_parts=500,
        shipping_cost=20,
    )

    assert result.whole.reason == "ok"
    assert result.parts.reason == "ok"
    assert result.whole.profit is not None
    assert result.parts.profit is not None
    assert result.best_path == "parts"
    assert result.best == result.parts


def test_negative_roi_case():
    result = compute_roi(
        purchase_price=300,
        sale_price=250,
    )

    assert result.profit is not None
    assert result.roi_pct is not None
    assert result.profit < 0
    assert result.roi_pct < 0


def test_missing_sale_price():
    result = compute_roi(
        purchase_price=200,
        sale_price=None,
    )

    assert result.roi_pct is None
    assert result.reason == "sale_price_missing"


def test_purchase_price_validation():
    with pytest.raises(ValueError):
        compute_roi(
            purchase_price=0,
            sale_price=200,
        )


def test_determinism_and_rounding_sanity():
    first = compute_roi(
        purchase_price=200,
        sale_price=400,
        shipping_cost=20,
        extra_costs=10,
    )
    second = compute_roi(
        purchase_price=200,
        sale_price=400,
        shipping_cost=20,
        extra_costs=10,
    )

    assert first == second
    assert first.revenue_net == pytest.approx(335.7)
    assert first.total_cost == pytest.approx(230.0)
    assert first.profit == pytest.approx(105.7)
    assert first.roi_pct == pytest.approx((105.7 / 230.0) * 100)
