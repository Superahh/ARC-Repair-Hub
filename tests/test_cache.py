from src.cache import (
    CachedEbayClient,
    InMemorySearchCache,
    build_search_cache_key,
    is_cache_entry_fresh,
)
from src.ebay_client import ListingRecord, SearchRequest, StubEbayClient


def test_build_search_cache_key_is_stable_for_equivalent_requests():
    first = SearchRequest(
        query=" A1990 ",
        condition="Used",
        min_price=100,
        max_price=500,
        keywords=("battery", "logic board"),
    )
    second = SearchRequest(
        query="a1990",
        condition=" used ",
        min_price=100,
        max_price=500,
        keywords=("logic board", "battery"),
    )

    assert build_search_cache_key(first) == build_search_cache_key(second)


def test_is_cache_entry_fresh_respects_ttl():
    cache = InMemorySearchCache()
    key = "search:key"
    cache.put(key=key, value=[{"item_id": "1"}], fetched_at_epoch=100.0)
    entry = cache.get(key)
    assert entry is not None

    assert is_cache_entry_fresh(entry, now_epoch=130.0, ttl_seconds=30)
    assert not is_cache_entry_fresh(entry, now_epoch=131.0, ttl_seconds=30)


def test_cached_ebay_client_hits_cache_within_ttl():
    inner = StubEbayClient(
        [ListingRecord(title="MacBook Pro A1990", item_id="1", price=200.0, condition_raw="Used")]
    )
    cache = InMemorySearchCache()
    now = {"value": 1000.0}

    client = CachedEbayClient(
        client=inner,
        cache=cache,
        ttl_seconds=60,
        now_epoch_fn=lambda: now["value"],
    )
    request = SearchRequest(query="A1990")

    first = client.search(request)
    second = client.search(request)

    assert [item.item_id for item in first] == ["1"]
    assert [item.item_id for item in second] == ["1"]
    assert len(inner.calls) == 1


def test_cached_ebay_client_refreshes_after_ttl():
    inner = StubEbayClient(
        [ListingRecord(title="MacBook Pro A1990", item_id="1", price=200.0, condition_raw="Used")]
    )
    cache = InMemorySearchCache()
    now = {"value": 1000.0}

    client = CachedEbayClient(
        client=inner,
        cache=cache,
        ttl_seconds=60,
        now_epoch_fn=lambda: now["value"],
    )
    request = SearchRequest(query="A1990")

    client.search(request)
    now["value"] = 1061.0
    client.search(request)

    assert len(inner.calls) == 2
