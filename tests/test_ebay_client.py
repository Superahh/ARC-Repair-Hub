import pytest

from src.ebay_client import ListingRecord, SearchRequest, StubEbayClient


def test_search_request_requires_non_empty_query():
    with pytest.raises(ValueError):
        SearchRequest(query="   ")


def test_search_request_normalization_is_deterministic():
    request = SearchRequest(
        query="  A1990  ",
        condition="  Used ",
        min_price=100,
        max_price=500,
        keywords=("Logic Board", "  Battery", "logic board"),
    )

    normalized = request.normalized()

    assert normalized.query == "a1990"
    assert normalized.condition == "used"
    assert normalized.keywords == ("battery", "logic board")


def test_stub_ebay_client_filters_and_sorts_results():
    client = StubEbayClient(
        [
            ListingRecord(
                title="MacBook Pro A1990 logic board used",
                item_id="2",
                price=220.0,
                condition_raw="Used",
            ),
            ListingRecord(
                title="MacBook Pro A1990 battery used",
                item_id="1",
                price=180.0,
                condition_raw="Used",
            ),
            ListingRecord(
                title="ThinkPad X1 battery used",
                item_id="3",
                price=120.0,
                condition_raw="Used",
            ),
        ]
    )

    results = client.search(
        SearchRequest(
            query="A1990",
            condition="used",
            min_price=150,
            keywords=("battery",),
        )
    )

    assert [item.item_id for item in results] == ["1"]
    assert len(client.calls) == 1
