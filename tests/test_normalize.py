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
