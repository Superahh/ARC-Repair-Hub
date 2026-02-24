"""eBay client interfaces and deterministic local stub implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class SearchRequest:
    query: str
    condition: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    keywords: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("query must not be empty")

    def normalized(self) -> SearchRequest:
        """Return a canonicalized request used for deterministic cache keys."""
        normalized_keywords = tuple(
            sorted(keyword.strip().lower() for keyword in self.keywords if keyword.strip())
        )
        condition = self.condition.strip().lower() if self.condition else None
        return SearchRequest(
            query=self.query.strip().lower(),
            condition=condition,
            min_price=self.min_price,
            max_price=self.max_price,
            keywords=normalized_keywords,
        )


@dataclass(frozen=True)
class ListingRecord:
    title: str
    item_id: str
    price: float
    shipping: float | None = None
    condition_raw: str | None = None
    url: str | None = None


class EbayClient(Protocol):
    def search(self, request: SearchRequest) -> list[ListingRecord]:
        """Fetch listings matching the request."""


class StubEbayClient:
    """Deterministic in-memory eBay client used for tests and local dev."""

    def __init__(self, listings: Sequence[ListingRecord]) -> None:
        self._listings = list(listings)
        self.calls: list[SearchRequest] = []

    def search(self, request: SearchRequest) -> list[ListingRecord]:
        self.calls.append(request)
        normalized = request.normalized()
        query = normalized.query
        condition = normalized.condition
        min_price = normalized.min_price
        max_price = normalized.max_price
        keywords = normalized.keywords

        results = []
        for listing in self._listings:
            title_lower = listing.title.lower()
            if query not in title_lower:
                continue

            if condition:
                listing_condition = (listing.condition_raw or "").lower()
                if condition not in listing_condition:
                    continue

            if min_price is not None and listing.price < min_price:
                continue

            if max_price is not None and listing.price > max_price:
                continue

            if keywords and not all(keyword in title_lower for keyword in keywords):
                continue

            results.append(listing)

        return sorted(results, key=lambda item: (item.item_id, item.title))


class EbayClientNotConfigured:
    """Placeholder for a future real eBay API client implementation."""

    def search(self, request: SearchRequest) -> list[ListingRecord]:
        raise NotImplementedError("Real eBay client is not configured yet.")
