from src.estimation import estimate_sale_prices


def test_estimate_sale_prices_used_profile():
    whole, parts = estimate_sale_prices(
        purchase_price=200,
        condition_raw="Used",
        title="MacBook Pro A1990 used",
    )

    assert whole == 320.0
    assert parts == 370.0


def test_estimate_sale_prices_for_parts_profile():
    whole, parts = estimate_sale_prices(
        purchase_price=200,
        condition_raw="For parts",
        title="MacBook Pro A1990 for parts",
    )

    assert whole == 270.0
    assert parts == 320.0
