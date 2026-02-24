import io
import json
from email.message import Message
from urllib.error import HTTPError

import pytest

from src.ebay_client import (
    EbayAPIError,
    OAuthClientCredentialsTokenProvider,
    RealEbayClient,
    SearchRequest,
    StaticAccessTokenProvider,
)


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_oauth_provider_fetches_and_caches_token(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        assert request.full_url.endswith("/identity/v1/oauth2/token")
        body = request.data.decode("utf-8")
        assert "grant_type=client_credentials" in body
        return _FakeResponse({"access_token": "token-1", "expires_in": 120})

    monkeypatch.setattr("src.ebay_client.urlopen", fake_urlopen)

    now = {"value": 1000.0}
    provider = OAuthClientCredentialsTokenProvider(
        client_id="client-id",
        client_secret="client-secret",
        now_epoch_fn=lambda: now["value"],
    )

    first = provider.get_access_token()
    second = provider.get_access_token()

    assert first == "token-1"
    assert second == "token-1"
    assert calls["count"] == 1


def test_real_client_search_maps_and_filters_response(monkeypatch):
    def fake_urlopen(request, timeout):
        assert request.full_url.startswith("https://api.ebay.com/buy/browse/v1/item_summary/search")
        assert "q=a1990+battery" in request.full_url
        assert request.headers["Authorization"] == "Bearer static-token"
        return _FakeResponse(
            {
                "itemSummaries": [
                    {
                        "itemId": "2",
                        "title": "MacBook Pro A1990 logic board used",
                        "price": {"value": "220"},
                        "shippingOptions": [{"shippingCost": {"value": "15.0"}}],
                        "condition": "Used",
                        "itemWebUrl": "https://example.com/2",
                    },
                    {
                        "itemId": "1",
                        "title": "MacBook Pro A1990 battery used",
                        "price": {"value": "180"},
                        "shippingOptions": [{"shippingCost": {"value": "12.0"}}],
                        "condition": "Used",
                        "itemWebUrl": "https://example.com/1",
                    },
                    {
                        "itemId": "3",
                        "title": "MacBook Pro A1990 battery for parts",
                        "price": {"value": "140"},
                        "condition": "For parts",
                    },
                ]
            }
        )

    monkeypatch.setattr("src.ebay_client.urlopen", fake_urlopen)
    client = RealEbayClient(token_provider=StaticAccessTokenProvider("static-token"))
    results = client.search(
        SearchRequest(query="A1990", condition="used", min_price=150, keywords=("battery",))
    )

    assert [item.item_id for item in results] == ["1"]
    assert results[0].shipping == 12.0
    assert results[0].url == "https://example.com/1"


def test_real_client_wraps_http_errors(monkeypatch):
    def fake_urlopen(request, timeout):
        raise HTTPError(
            url=request.full_url,
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=io.BytesIO(b"{\"error\":\"server_error\"}"),
        )

    monkeypatch.setattr("src.ebay_client.urlopen", fake_urlopen)
    client = RealEbayClient(token_provider=StaticAccessTokenProvider("static-token"))

    with pytest.raises(EbayAPIError):
        client.search(SearchRequest(query="A1990"))


def test_real_client_from_env_prefers_static_token(monkeypatch):
    monkeypatch.setenv("EBAY_ACCESS_TOKEN", "env-token")
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)

    def fake_urlopen(request, timeout):
        assert request.headers["Authorization"] == "Bearer env-token"
        return _FakeResponse({"itemSummaries": []})

    monkeypatch.setattr("src.ebay_client.urlopen", fake_urlopen)
    client = RealEbayClient.from_env()
    results = client.search(SearchRequest(query="A1990"))

    assert results == []


def test_real_client_retries_on_429_then_succeeds(monkeypatch):
    calls = {"count": 0}
    sleep_calls: list[float] = []

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            headers = Message()
            headers["Retry-After"] = "1"
            raise HTTPError(
                url=request.full_url,
                code=429,
                msg="Too Many Requests",
                hdrs=headers,
                fp=io.BytesIO(b"{\"error\":\"rate_limited\"}"),
            )
        return _FakeResponse(
            {
                "itemSummaries": [
                    {
                        "itemId": "1",
                        "title": "MacBook Pro A1990 battery used",
                        "price": {"value": "180"},
                        "condition": "Used",
                    }
                ]
            }
        )

    monkeypatch.setattr("src.ebay_client.urlopen", fake_urlopen)
    client = RealEbayClient(
        token_provider=StaticAccessTokenProvider("static-token"),
        max_retries=1,
        sleep_fn=lambda seconds: sleep_calls.append(seconds),
    )
    results = client.search(SearchRequest(query="A1990", keywords=("battery",)))

    assert [item.item_id for item in results] == ["1"]
    assert calls["count"] == 2
    assert sleep_calls == [1.0]


def test_real_client_raises_after_retry_exhausted(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        raise HTTPError(
            url=request.full_url,
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(b"{\"error\":\"service_unavailable\"}"),
        )

    monkeypatch.setattr("src.ebay_client.urlopen", fake_urlopen)
    client = RealEbayClient(
        token_provider=StaticAccessTokenProvider("static-token"),
        max_retries=1,
        sleep_fn=lambda seconds: None,
    )

    with pytest.raises(EbayAPIError) as exc_info:
        client.search(SearchRequest(query="A1990"))

    assert calls["count"] == 2
    assert exc_info.value.status_code == 503
    assert exc_info.value.retryable is True
