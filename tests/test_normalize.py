from src.normalize import assess_risk, normalize_condition


def test_normalize_condition_simple_used():
    condition = normalize_condition(raw_condition="Used", title="MacBook Pro A1990")

    assert condition.normalized == "used"
    assert condition.reasons == ("ok",)


def test_normalize_condition_detects_conflict_between_title_and_raw():
    condition = normalize_condition(
        raw_condition="Used",
        title="MacBook Pro A1990 for parts",
    )

    assert condition.normalized == "ambiguous"
    assert condition.reasons == ("condition_conflict_title_vs_raw",)


def test_assess_risk_for_missing_sale_prices():
    condition = normalize_condition(raw_condition=None, title="Laptop listing")
    risk = assess_risk(
        title="Laptop listing",
        condition=condition,
        purchase_price=200,
        sale_price_whole=None,
        sale_price_parts=None,
    )

    assert risk.score == 70
    assert risk.reasons == ("condition_unknown", "sale_prices_missing")


def test_assess_risk_detects_divergence_and_outlier():
    condition = normalize_condition(raw_condition="Used", title="Clean used listing")
    risk = assess_risk(
        title="Clean used listing",
        condition=condition,
        purchase_price=200,
        sale_price_whole=700,
        sale_price_parts=300,
    )

    assert risk.score == 35
    assert risk.reasons == ("path_price_divergence", "price_outlier_high")


def test_assess_risk_flags_conflict_messy_title_and_missing_shipping():
    condition = normalize_condition(
        raw_condition="Used",
        title="MacBook Pro A1990 for parts ?? read description",
    )
    risk = assess_risk(
        title="MacBook Pro A1990 for parts ?? read description",
        condition=condition,
        purchase_price=200,
        sale_price_whole=320,
        sale_price_parts=300,
        shipping_missing=True,
    )

    assert risk.score == 75
    assert risk.reasons == (
        "condition_ambiguous",
        "condition_conflict_title_vs_raw",
        "shipping_missing",
        "listing_data_messy",
    )


def test_assess_risk_flags_estimated_sale_prices():
    condition = normalize_condition(raw_condition="Used", title="MacBook Pro A1990 used")
    risk = assess_risk(
        title="MacBook Pro A1990 used",
        condition=condition,
        purchase_price=200,
        sale_price_whole=320,
        sale_price_parts=370,
        sale_prices_estimated=True,
    )

    assert risk.score == 20
    assert risk.reasons == ("sale_prices_estimated",)
