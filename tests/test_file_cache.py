from src.cache import CachedEbayClient, FileSearchCache
from src.ebay_client import ListingRecord, SearchRequest, StubEbayClient


def test_file_search_cache_persists_across_instances(tmp_path):
    path = tmp_path / "cache" / "search_cache.json"
    cache_a = FileSearchCache(path)
    cache_a.put(
        key="search:key-1",
        value=[{"item_id": "1", "title": "MacBook Pro A1990", "price": 200.0}],
        fetched_at_epoch=1000.0,
    )

    cache_b = FileSearchCache(path)
    entry = cache_b.get("search:key-1")

    assert entry is not None
    assert entry.key == "search:key-1"
    assert entry.fetched_at_epoch == 1000.0
    assert entry.value[0]["item_id"] == "1"


def test_file_search_cache_returns_none_for_missing_key(tmp_path):
    cache = FileSearchCache(tmp_path / "cache.json")
    assert cache.get("search:missing") is None


def test_cached_client_uses_file_cache_after_restart(tmp_path):
    cache_path = tmp_path / "cache" / "search_cache.json"
    request = SearchRequest(query="A1990")

    first_inner = StubEbayClient(
        [ListingRecord(title="MacBook Pro A1990", item_id="1", price=200.0, condition_raw="Used")]
    )
    first_client = CachedEbayClient(
        client=first_inner,
        cache=FileSearchCache(cache_path),
        ttl_seconds=60,
        now_epoch_fn=lambda: 1000.0,
    )
    first_results = first_client.search(request)

    second_inner = StubEbayClient(
        [ListingRecord(title="MacBook Pro A1990", item_id="2", price=300.0, condition_raw="Used")]
    )
    second_client = CachedEbayClient(
        client=second_inner,
        cache=FileSearchCache(cache_path),
        ttl_seconds=60,
        now_epoch_fn=lambda: 1010.0,
    )
    second_results = second_client.search(request)

    assert [item.item_id for item in first_results] == ["1"]
    assert [item.item_id for item in second_results] == ["1"]
    assert len(first_inner.calls) == 1
    assert len(second_inner.calls) == 0
