"""eBay client interfaces and deterministic local stub implementations."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_EBAY_SCOPE = "https://api.ebay.com/oauth/api_scope/buy.browse"
DEFAULT_EBAY_MARKETPLACE_ID = "EBAY_US"
DEFAULT_EBAY_TIMEOUT_SECONDS = 10.0
DEFAULT_EBAY_MAX_RETRIES = 1

_TOKEN_URL_PROD = "https://api.ebay.com/identity/v1/oauth2/token"
_TOKEN_URL_SANDBOX = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
_BROWSE_SEARCH_URL_PROD = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_BROWSE_SEARCH_URL_SANDBOX = "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search"


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
    sale_price_whole: float | None = None
    sale_price_parts: float | None = None


class EbayClient(Protocol):
    def search(self, request: SearchRequest) -> list[ListingRecord]:
        """Fetch listings matching the request."""


class AccessTokenProvider(Protocol):
    def get_access_token(self) -> str:
        """Return a bearer token suitable for eBay API calls."""


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


class EbayAuthError(RuntimeError):
    """Raised when eBay auth/token acquisition fails."""


class EbayAPIError(RuntimeError):
    """Raised when eBay browse API requests fail."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        self.retryable = retryable


@dataclass(frozen=True)
class StaticAccessTokenProvider:
    token: str

    def get_access_token(self) -> str:
        normalized = self.token.strip()
        if not normalized:
            raise EbayAuthError("EBAY_ACCESS_TOKEN is empty")
        return normalized


class OAuthClientCredentialsTokenProvider:
    """Client credentials token provider with in-memory token caching."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        scope: str = DEFAULT_EBAY_SCOPE,
        sandbox: bool = False,
        timeout_seconds: float = DEFAULT_EBAY_TIMEOUT_SECONDS,
        now_epoch_fn: Callable[[], float] | None = None,
    ) -> None:
        self._client_id = client_id.strip()
        self._client_secret = client_secret.strip()
        self._scope = scope.strip()
        self._sandbox = sandbox
        self._timeout_seconds = timeout_seconds
        self._now_epoch_fn = now_epoch_fn or _default_now_epoch

        self._cached_token: str | None = None
        self._expires_at_epoch: float = 0.0

        if not self._client_id or not self._client_secret:
            raise EbayAuthError("eBay client credentials are required")

    def get_access_token(self) -> str:
        now = self._now_epoch_fn()
        if self._cached_token and now < (self._expires_at_epoch - 30):
            return self._cached_token

        token, expires_in = self._fetch_token()
        self._cached_token = token
        self._expires_at_epoch = now + max(float(expires_in), 0.0)
        return token

    def _fetch_token(self) -> tuple[str, float]:
        token_url = _TOKEN_URL_SANDBOX if self._sandbox else _TOKEN_URL_PROD
        auth_value = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode("utf-8")).decode("ascii")
        body = urlencode({"grant_type": "client_credentials", "scope": self._scope}).encode("utf-8")
        request = Request(
            token_url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Basic {auth_value}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )

        payload = _request_json(request=request, timeout_seconds=self._timeout_seconds, error_cls=EbayAuthError)
        token = str(payload.get("access_token", "")).strip()
        expires_in = float(payload.get("expires_in", 0))
        if not token:
            raise EbayAuthError("eBay token response missing access_token")
        return token, expires_in


class RealEbayClient:
    """HTTP eBay Browse API client using OAuth bearer tokens."""

    def __init__(
        self,
        token_provider: AccessTokenProvider,
        marketplace_id: str = DEFAULT_EBAY_MARKETPLACE_ID,
        sandbox: bool = False,
        timeout_seconds: float = DEFAULT_EBAY_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_EBAY_MAX_RETRIES,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self._token_provider = token_provider
        self._marketplace_id = marketplace_id.strip() or DEFAULT_EBAY_MARKETPLACE_ID
        self._sandbox = sandbox
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, int(max_retries))
        self._sleep_fn = sleep_fn or _default_sleep

    @classmethod
    def from_env(
        cls,
        *,
        sandbox: bool | None = None,
        marketplace_id: str | None = None,
        timeout_seconds: float = DEFAULT_EBAY_TIMEOUT_SECONDS,
        max_retries: int | None = None,
    ) -> RealEbayClient:
        resolved_sandbox = _env_truthy("EBAY_USE_SANDBOX") if sandbox is None else sandbox
        resolved_marketplace = marketplace_id or os.getenv("EBAY_MARKETPLACE_ID", DEFAULT_EBAY_MARKETPLACE_ID)
        resolved_retries = max_retries
        if resolved_retries is None:
            raw = os.getenv("EBAY_MAX_RETRIES", "").strip()
            resolved_retries = int(raw) if raw else DEFAULT_EBAY_MAX_RETRIES

        static_token = os.getenv("EBAY_ACCESS_TOKEN", "").strip()
        if static_token:
            provider: AccessTokenProvider = StaticAccessTokenProvider(token=static_token)
        else:
            client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
            client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()
            scope = os.getenv("EBAY_SCOPE", DEFAULT_EBAY_SCOPE).strip() or DEFAULT_EBAY_SCOPE
            if not client_id or not client_secret:
                raise EbayAuthError(
                    "Missing eBay auth config. Set EBAY_ACCESS_TOKEN or both EBAY_CLIENT_ID and EBAY_CLIENT_SECRET."
                )
            provider = OAuthClientCredentialsTokenProvider(
                client_id=client_id,
                client_secret=client_secret,
                scope=scope,
                sandbox=resolved_sandbox,
                timeout_seconds=timeout_seconds,
            )

        return cls(
            token_provider=provider,
            marketplace_id=resolved_marketplace,
            sandbox=resolved_sandbox,
            timeout_seconds=timeout_seconds,
            max_retries=resolved_retries,
        )

    def search(self, request: SearchRequest) -> list[ListingRecord]:
        normalized = request.normalized()
        payload: dict[str, Any] | None = None
        for attempt in range(self._max_retries + 1):
            try:
                payload = self._search_once(normalized)
                break
            except EbayAPIError as exc:
                if attempt >= self._max_retries or not exc.retryable:
                    raise
                delay = _retry_delay_seconds(exc, attempt)
                self._sleep_fn(delay)

        assert payload is not None
        item_summaries = payload.get("itemSummaries", [])
        if not isinstance(item_summaries, list):
            raise EbayAPIError("Unexpected eBay response: itemSummaries is not a list")

        mapped: list[ListingRecord] = []
        for item in item_summaries:
            if not isinstance(item, dict):
                continue
            record = _listing_record_from_item(item)
            if record is None:
                continue
            mapped.append(record)

        filtered = _filter_records(mapped, normalized)
        return sorted(filtered, key=lambda item: (item.item_id, item.title))

    def _search_once(self, normalized: SearchRequest) -> dict[str, Any]:
        browse_url = _BROWSE_SEARCH_URL_SANDBOX if self._sandbox else _BROWSE_SEARCH_URL_PROD
        query_parts = [normalized.query, *normalized.keywords]
        query_text = " ".join(part for part in query_parts if part).strip()
        params = {"q": query_text}
        url = f"{browse_url}?{urlencode(params)}"

        token = self._token_provider.get_access_token()
        api_request = Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "X-EBAY-C-MARKETPLACE-ID": self._marketplace_id,
            },
        )
        return _request_json(request=api_request, timeout_seconds=self._timeout_seconds, error_cls=EbayAPIError)


def _listing_record_from_item(item: dict[str, Any]) -> ListingRecord | None:
    url = str(item.get("itemWebUrl") or "").strip()
    item_id = str(item.get("itemId") or item.get("legacyItemId") or "").strip()
    if not item_id and url:
        item_id = f"url:{url}"
    title = str(item.get("title") or "").strip()
    price = _extract_money_value(item.get("price"))

    if not item_id or not title or price is None:
        return None

    shipping = _extract_shipping_value(item.get("shippingOptions"))
    condition = str(item.get("condition")) if item.get("condition") is not None else None
    normalized_url = url if url else None

    return ListingRecord(
        title=title,
        item_id=item_id,
        price=price,
        shipping=shipping,
        condition_raw=condition,
        url=normalized_url,
    )


def _extract_money_value(value: Any) -> float | None:
    if not isinstance(value, dict):
        return None
    amount = value.get("value")
    if amount is None:
        return None
    try:
        return float(amount)
    except (TypeError, ValueError):
        return None


def _extract_shipping_value(options: Any) -> float | None:
    if not isinstance(options, list):
        return None
    for option in options:
        if not isinstance(option, dict):
            continue
        shipping = _extract_money_value(option.get("shippingCost"))
        if shipping is not None:
            return shipping
    return None


def _filter_records(records: Sequence[ListingRecord], request: SearchRequest) -> list[ListingRecord]:
    query = request.query
    condition = request.condition
    min_price = request.min_price
    max_price = request.max_price
    keywords = request.keywords

    filtered: list[ListingRecord] = []
    for record in records:
        title_lower = record.title.lower()
        if query and query not in title_lower:
            continue

        if condition and condition not in (record.condition_raw or "").lower():
            continue

        if min_price is not None and record.price < min_price:
            continue

        if max_price is not None and record.price > max_price:
            continue

        if keywords and not all(keyword in title_lower for keyword in keywords):
            continue

        filtered.append(record)

    return filtered


def _request_json(request: Request, timeout_seconds: float, error_cls: type[RuntimeError]) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        body = _extract_http_error_body(exc)
        message = f"HTTP {exc.code} from {request.full_url}: {body}"
        if error_cls is EbayAPIError:
            retry_after = _parse_retry_after(exc.headers.get("Retry-After")) if exc.headers else None
            raise EbayAPIError(
                message,
                status_code=exc.code,
                retry_after_seconds=retry_after,
                retryable=_is_retryable_status(exc.code),
            ) from exc
        raise error_cls(message) from exc
    except URLError as exc:
        message = f"Network error calling {request.full_url}: {exc.reason}"
        if error_cls is EbayAPIError:
            raise EbayAPIError(message, retryable=True) from exc
        raise error_cls(message) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise error_cls(f"Invalid JSON response from {request.full_url}") from exc

    if not isinstance(payload, dict):
        raise error_cls(f"Unexpected JSON response shape from {request.full_url}")
    return payload


def _extract_http_error_body(exc: HTTPError) -> str:
    try:
        if exc.fp is None:
            return exc.reason
        body = exc.fp.read().decode("utf-8", errors="replace").strip()
        return body or str(exc.reason)
    except Exception:
        return str(exc.reason)


def _env_truthy(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _default_now_epoch() -> float:
    import time

    return time.time()


def _default_sleep(seconds: float) -> None:
    import time

    time.sleep(max(seconds, 0.0))


def _retry_delay_seconds(error: EbayAPIError, attempt: int) -> float:
    if error.retry_after_seconds is not None and error.retry_after_seconds > 0:
        return error.retry_after_seconds
    # exponential backoff: 1s, 2s, 4s...
    return float(2**attempt)


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {429, 500, 502, 503, 504}


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


class EbayClientNotConfigured:
    """Placeholder for a future real eBay API client implementation."""

    def search(self, request: SearchRequest) -> list[ListingRecord]:
        raise NotImplementedError("Real eBay client is not configured yet.")
