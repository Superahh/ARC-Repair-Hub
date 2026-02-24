"""Search orchestration using eBay client, cache contract, and local storage."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Sequence

from src.cache import (
    DEFAULT_CACHE_TTL_SECONDS,
    SearchCache,
    build_search_cache_key,
    is_cache_entry_fresh,
)
from src.ebay_client import EbayClient, ListingRecord, SearchRequest
from src.storage import append_results


@dataclass(frozen=True)
class SearchRunResult:
    request: SearchRequest
    records: list[ListingRecord]
    source: Literal["fresh", "cache", "cache_fallback", "empty"]
    warning: str | None
    persisted_rows: int


def search_and_store(
    client: EbayClient,
    cache: SearchCache,
    storage_path: str | Path,
    query: str,
    condition: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    keywords: Sequence[str] = (),
    now_epoch: float = 0.0,
    ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> SearchRunResult:
    """Run a listing search with cache-aware and failure-safe behavior."""
    request = SearchRequest(
        query=query,
        condition=condition,
        min_price=min_price,
        max_price=max_price,
        keywords=tuple(keywords),
    )
    key = build_search_cache_key(request)
    cached_entry = cache.get(key)

    warning: str | None = None
    source: Literal["fresh", "cache", "cache_fallback", "empty"]

    if cached_entry and is_cache_entry_fresh(cached_entry, now_epoch=now_epoch, ttl_seconds=ttl_seconds):
        records = [_record_from_dict(row) for row in cached_entry.value]
        source = "cache"
    else:
        try:
            records = client.search(request)
            cache.put(
                key=key,
                value=[asdict(record) for record in records],
                fetched_at_epoch=now_epoch,
            )
            source = "fresh"
        except Exception as exc:  # pragma: no cover - explicit fallback path tests cover this.
            if cached_entry:
                records = [_record_from_dict(row) for row in cached_entry.value]
                source = "cache_fallback"
                warning = f"api_failed_using_cache:{exc.__class__.__name__}"
            else:
                records = []
                source = "empty"
                warning = f"api_failed_no_cache:{exc.__class__.__name__}"

    rows = [_record_to_storage_row(record) for record in records]
    merged = append_results(storage_path, rows) if rows else []

    return SearchRunResult(
        request=request,
        records=records,
        source=source,
        warning=warning,
        persisted_rows=len(merged),
    )


def _record_to_storage_row(record: ListingRecord) -> dict[str, object]:
    return {
        "title": record.title,
        "item_id": record.item_id,
        "price": record.price,
        "shipping": record.shipping if record.shipping is not None else 0.0,
        "condition_raw": record.condition_raw,
        "url": record.url,
    }


def _record_from_dict(data: dict[str, object]) -> ListingRecord:
    shipping = data.get("shipping")
    return ListingRecord(
        title=str(data["title"]),
        item_id=str(data["item_id"]),
        price=float(data["price"]),
        shipping=float(shipping) if shipping is not None else None,
        condition_raw=str(data["condition_raw"]) if data.get("condition_raw") is not None else None,
        url=str(data["url"]) if data.get("url") is not None else None,
    )
