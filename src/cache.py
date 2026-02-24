"""Search cache contracts and deterministic cache-wrapper behavior."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from src.config import DEFAULT_CACHE_TTL_SECONDS
from src.ebay_client import EbayClient, ListingRecord, SearchRequest


@dataclass(frozen=True)
class CacheEntry:
    key: str
    value: list[dict[str, Any]]
    fetched_at_epoch: float


class SearchCache(Protocol):
    def get(self, key: str) -> CacheEntry | None:
        """Return cached entry for key, if present."""

    def put(self, key: str, value: Sequence[Mapping[str, Any]], fetched_at_epoch: float) -> CacheEntry:
        """Persist a cache entry and return the stored entry."""


class InMemorySearchCache:
    """Simple in-memory cache implementing the SearchCache contract."""

    def __init__(self) -> None:
        self._entries: dict[str, CacheEntry] = {}

    def get(self, key: str) -> CacheEntry | None:
        return self._entries.get(key)

    def put(self, key: str, value: Sequence[Mapping[str, Any]], fetched_at_epoch: float) -> CacheEntry:
        entry = CacheEntry(
            key=key,
            value=[dict(row) for row in value],
            fetched_at_epoch=fetched_at_epoch,
        )
        self._entries[key] = entry
        return entry


class FileSearchCache:
    """JSON file-backed cache implementing the SearchCache contract."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def get(self, key: str) -> CacheEntry | None:
        entries = self._load_entries()
        return entries.get(key)

    def put(self, key: str, value: Sequence[Mapping[str, Any]], fetched_at_epoch: float) -> CacheEntry:
        entries = self._load_entries()
        entry = CacheEntry(
            key=key,
            value=[dict(row) for row in value],
            fetched_at_epoch=fetched_at_epoch,
        )
        entries[key] = entry
        self._save_entries(entries)
        return entry

    def _load_entries(self) -> dict[str, CacheEntry]:
        if not self._path.exists():
            return {}

        raw = self._path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}

        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("cache file must contain a JSON object")

        entries: dict[str, CacheEntry] = {}
        for cache_key, row in payload.items():
            if not isinstance(row, dict):
                continue
            if "value" not in row or "fetched_at_epoch" not in row:
                continue
            entries[cache_key] = CacheEntry(
                key=cache_key,
                value=[dict(item) for item in row["value"]],
                fetched_at_epoch=float(row["fetched_at_epoch"]),
            )
        return entries

    def _save_entries(self, entries: Mapping[str, CacheEntry]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            key: {
                "key": entry.key,
                "value": entry.value,
                "fetched_at_epoch": entry.fetched_at_epoch,
            }
            for key, entry in sorted(entries.items())
        }
        self._path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def build_search_cache_key(request: SearchRequest) -> str:
    """Build a stable cache key from canonicalized search parameters."""
    normalized = request.normalized()
    payload = {
        "query": normalized.query,
        "condition": normalized.condition,
        "min_price": normalized.min_price,
        "max_price": normalized.max_price,
        "keywords": list(normalized.keywords),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"search:{digest}"


def is_cache_entry_fresh(entry: CacheEntry, now_epoch: float, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> bool:
    """Return whether an entry is still valid for the configured TTL."""
    age = now_epoch - entry.fetched_at_epoch
    return age <= ttl_seconds


class CachedEbayClient:
    """EbayClient wrapper honoring cache contracts before hitting the inner client."""

    def __init__(
        self,
        client: EbayClient,
        cache: SearchCache,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        now_epoch_fn: Callable[[], float] | None = None,
    ) -> None:
        self._client = client
        self._cache = cache
        self._ttl_seconds = ttl_seconds
        self._now_epoch_fn = now_epoch_fn or _default_now_epoch

    def search(self, request: SearchRequest) -> list[ListingRecord]:
        key = build_search_cache_key(request)
        now = self._now_epoch_fn()
        cached = self._cache.get(key)
        if cached and is_cache_entry_fresh(cached, now_epoch=now, ttl_seconds=self._ttl_seconds):
            return [_listing_from_mapping(row) for row in cached.value]

        rows = [asdict(item) for item in self._client.search(request)]
        self._cache.put(key=key, value=rows, fetched_at_epoch=now)
        return [_listing_from_mapping(row) for row in rows]


def _listing_from_mapping(row: Mapping[str, Any]) -> ListingRecord:
    return ListingRecord(
        title=str(row["title"]),
        item_id=str(row["item_id"]),
        price=float(row["price"]),
        shipping=float(row["shipping"]) if row.get("shipping") is not None else None,
        condition_raw=str(row["condition_raw"]) if row.get("condition_raw") is not None else None,
        url=str(row["url"]) if row.get("url") is not None else None,
        sale_price_whole=float(row["sale_price_whole"]) if row.get("sale_price_whole") is not None else None,
        sale_price_parts=float(row["sale_price_parts"]) if row.get("sale_price_parts") is not None else None,
    )


def _default_now_epoch() -> float:
    import time

    return time.time()
