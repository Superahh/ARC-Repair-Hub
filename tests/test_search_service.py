from src.cache import InMemorySearchCache
from src.ebay_client import ListingRecord, SearchRequest, StubEbayClient
from src.search_service import search_and_store
from src.storage import load_results


class FailingClient:
    def search(self, request: SearchRequest) -> list[ListingRecord]:
        raise RuntimeError("upstream down")


def test_search_and_store_fetches_fresh_and_persists(tmp_path):
    client = StubEbayClient(
        [
            ListingRecord(
                title="MacBook Pro A1990",
                item_id="1",
                price=220.0,
                shipping=15.0,
                condition_raw="Used",
            )
        ]
    )
    cache = InMemorySearchCache()
    path = tmp_path / "results.json"

    result = search_and_store(
        client=client,
        cache=cache,
        storage_path=path,
        query="A1990",
        now_epoch=1000.0,
        ttl_seconds=60,
    )

    assert result.source == "fresh"
    assert result.warning is None
    assert len(result.records) == 1
    assert result.persisted_rows == 1
    assert len(client.calls) == 1
    assert load_results(path)[0]["item_id"] == "1"


def test_search_and_store_uses_cache_when_fresh_and_avoids_extra_call(tmp_path):
    client = StubEbayClient(
        [ListingRecord(title="MacBook Pro A1990", item_id="1", price=220.0, condition_raw="Used")]
    )
    cache = InMemorySearchCache()
    path = tmp_path / "results.json"

    first = search_and_store(
        client=client,
        cache=cache,
        storage_path=path,
        query="A1990",
        now_epoch=1000.0,
        ttl_seconds=60,
    )
    second = search_and_store(
        client=client,
        cache=cache,
        storage_path=path,
        query="A1990",
        now_epoch=1005.0,
        ttl_seconds=60,
    )

    assert first.source == "fresh"
    assert second.source == "cache"
    assert len(client.calls) == 1
    assert second.persisted_rows == 1
    stored = load_results(path)
    assert len(stored) == 1
    assert stored[0]["item_id"] == "1"


def test_search_and_store_falls_back_to_cached_on_client_failure(tmp_path):
    seed_client = StubEbayClient(
        [ListingRecord(title="MacBook Pro A1990", item_id="1", price=220.0, condition_raw="Used")]
    )
    cache = InMemorySearchCache()
    path = tmp_path / "results.json"

    seeded = search_and_store(
        client=seed_client,
        cache=cache,
        storage_path=path,
        query="A1990",
        now_epoch=1000.0,
        ttl_seconds=60,
    )
    assert seeded.source == "fresh"

    failed = search_and_store(
        client=FailingClient(),
        cache=cache,
        storage_path=path,
        query="A1990",
        now_epoch=1100.0,
        ttl_seconds=60,
    )

    assert failed.source == "cache_fallback"
    assert failed.warning == "api_failed_using_cache:RuntimeError"
    assert len(failed.records) == 1
    assert failed.persisted_rows == 1


def test_search_and_store_returns_empty_when_no_cache_and_client_fails(tmp_path):
    cache = InMemorySearchCache()
    path = tmp_path / "results.json"

    result = search_and_store(
        client=FailingClient(),
        cache=cache,
        storage_path=path,
        query="A1990",
        now_epoch=1000.0,
        ttl_seconds=60,
    )

    assert result.source == "empty"
    assert result.warning == "api_failed_no_cache:RuntimeError"
    assert result.records == []
    assert result.persisted_rows == 0
