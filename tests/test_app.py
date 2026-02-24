from src.app import ListingCandidate, evaluate_listing, rank_listings


def test_evaluate_listing_uses_roi_engine_and_picks_best_path():
    listing = ListingCandidate(
        title="MacBook Pro A1990",
        item_id="item-1",
        purchase_price=200,
        sale_price_whole=400,
        sale_price_parts=500,
        shipping_cost=20,
    )

    evaluated = evaluate_listing(listing)

    assert evaluated.best_path == "parts"
    assert evaluated.roi_whole.reason == "ok"
    assert evaluated.roi_parts.reason == "ok"
    assert evaluated.roi_best == evaluated.roi_parts
    assert evaluated.total_cost == 220


def test_rank_listings_orders_by_best_profit_and_handles_missing_prices():
    listings = [
        ListingCandidate(
            title="Candidate A",
            item_id="a",
            purchase_price=200,
            sale_price_whole=350,
            sale_price_parts=380,
        ),
        ListingCandidate(
            title="Candidate B",
            item_id="b",
            purchase_price=200,
            sale_price_whole=420,
            sale_price_parts=390,
        ),
        ListingCandidate(
            title="Candidate C",
            item_id="c",
            purchase_price=200,
            sale_price_whole=None,
            sale_price_parts=None,
        ),
    ]

    ranked = rank_listings(listings)

    assert [item.item_id for item in ranked] == ["b", "a", "c"]
    assert ranked[0].best_path in {"whole", "parts"}
    assert ranked[-1].best_path == "none"
    assert ranked[-1].roi_best.reason.startswith("none_computable:")


def test_rank_listings_is_deterministic():
    listings = [
        ListingCandidate(
            title="Deterministic",
            item_id="det-1",
            purchase_price=250,
            sale_price_whole=500,
            sale_price_parts=450,
            shipping_cost=15,
            extra_costs=10,
        ),
        ListingCandidate(
            title="Deterministic 2",
            item_id="det-2",
            purchase_price=250,
            sale_price_whole=480,
            sale_price_parts=None,
            shipping_cost=15,
            extra_costs=10,
        ),
    ]

    first = rank_listings(listings)
    second = rank_listings(listings)

    assert first == second
