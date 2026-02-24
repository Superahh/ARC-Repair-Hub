import json
import os

from src.app import main, search_records
from src.ebay_client import ListingRecord


def test_search_records_filters_query_and_ranks_results():
    records = [
        {
            "title": "MacBook Pro A1990 used",
            "item_id": "b",
            "price": 200,
            "sale_price_whole": 420,
            "sale_price_parts": 390,
            "condition": "Used",
        },
        {
            "title": "MacBook Pro A1990 for parts",
            "item_id": "a",
            "price": 200,
            "sale_price_whole": 350,
            "sale_price_parts": 380,
            "condition": "For parts",
        },
        {
            "title": "ThinkPad X1",
            "item_id": "x",
            "price": 150,
            "sale_price_whole": 300,
            "sale_price_parts": 320,
            "condition": "Used",
        },
    ]

    rows = search_records("A1990", records)

    assert [row["item_id"] for row in rows] == ["b", "a"]
    assert rows[0]["source"] == "local"
    assert rows[0]["dedupe_key"] == "item_id:b"
    assert rows[0]["ROI_best"]["profit"] is not None


def test_main_search_reads_input_and_writes_output(tmp_path, capsys):
    input_path = tmp_path / "listings.json"
    output_path = tmp_path / "ranked.json"
    input_rows = [
        {
            "title": "MacBook Pro A1990 used",
            "item_id": "b",
            "price": 200,
            "sale_price_whole": 420,
            "sale_price_parts": 390,
            "condition": "Used",
        }
    ]
    input_path.write_text(json.dumps(input_rows), encoding="utf-8")

    exit_code = main(
        [
            "search",
            "A1990",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ]
    )
    stdout = capsys.readouterr().out

    assert exit_code == 0
    payload = json.loads(stdout)
    assert payload[0]["item_id"] == "b"
    assert output_path.exists()


def test_main_search_missing_input_file_returns_empty_json(capsys):
    exit_code = main(["search", "A1990", "--input", "missing_file.json"])
    stdout = capsys.readouterr().out

    assert exit_code == 0
    assert json.loads(stdout) == []


def test_main_search_market_data_mode_uses_file_cache(tmp_path, capsys):
    market_path = tmp_path / "market.json"
    cache_path = tmp_path / "cache.json"
    storage_path = tmp_path / "raw_results.json"

    market_rows = [
        {
            "title": "MacBook Pro A1990 used",
            "item_id": "seed-1",
            "price": 200,
            "sale_price_whole": 420,
            "sale_price_parts": 390,
            "condition_raw": "Used",
        }
    ]
    market_path.write_text(json.dumps(market_rows), encoding="utf-8")

    first_exit = main(
        [
            "search",
            "A1990",
            "--market-data",
            str(market_path),
            "--cache-path",
            str(cache_path),
            "--storage-path",
            str(storage_path),
            "--now-epoch",
            "1000",
        ]
    )
    first_stdout = capsys.readouterr().out
    first_payload = json.loads(first_stdout)

    market_rows[0]["item_id"] = "seed-2"
    market_path.write_text(json.dumps(market_rows), encoding="utf-8")

    second_exit = main(
        [
            "search",
            "A1990",
            "--market-data",
            str(market_path),
            "--cache-path",
            str(cache_path),
            "--storage-path",
            str(storage_path),
            "--now-epoch",
            "1001",
        ]
    )
    second_stdout = capsys.readouterr().out
    second_payload = json.loads(second_stdout)

    assert first_exit == 0
    assert second_exit == 0
    assert first_payload[0]["source"] == "fresh"
    assert first_payload[0]["item_id"] == "seed-1"
    assert first_payload[0]["timestamp"] == 1000.0
    assert second_payload[0]["source"] == "cache"
    assert second_payload[0]["item_id"] == "seed-1"
    assert second_payload[0]["timestamp"] == 1000.0
    persisted = json.loads(storage_path.read_text(encoding="utf-8"))
    assert len(persisted) == 1
    assert persisted[0]["item_id"] == "seed-1"


def test_main_search_use_ebay_api_mode(monkeypatch, tmp_path, capsys):
    class _FakeRealClient:
        def __init__(self) -> None:
            self.calls = 0

        def search(self, request):
            self.calls += 1
            return [
                ListingRecord(
                    title="MacBook Pro A1990 used",
                    item_id="live-1",
                    price=200.0,
                    shipping=20.0,
                    condition_raw="Used",
                    sale_price_whole=420.0,
                    sale_price_parts=500.0,
                )
            ]

    fake_client = _FakeRealClient()
    monkeypatch.setenv("EBAY_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr("src.app.RealEbayClient.from_env", lambda sandbox=False: fake_client)

    exit_code = main(
        [
            "search",
            "A1990",
            "--use-ebay-api",
            "--cache-path",
            str(tmp_path / "cache.json"),
            "--storage-path",
            str(tmp_path / "raw.json"),
            "--now-epoch",
            "1000",
        ]
    )
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)

    assert exit_code == 0
    assert fake_client.calls == 1
    assert payload[0]["item_id"] == "live-1"
    assert payload[0]["source"] == "fresh"


def test_main_ebay_smoke_success(monkeypatch, capsys):
    class _FakeRealClient:
        def search(self, request):
            return [
                ListingRecord(
                    title="MacBook Pro A1990 used",
                    item_id="smoke-1",
                    price=200.0,
                    condition_raw="Used",
                )
            ]

    monkeypatch.setenv("EBAY_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr("src.app.RealEbayClient.from_env", lambda sandbox=False: _FakeRealClient())

    exit_code = main(["ebay-smoke", "--query", "A1990"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["query"] == "A1990"
    assert payload["result_count"] == 1
    assert payload["sample_item_id"] == "smoke-1"
    assert payload["error"] is None


def test_main_ebay_smoke_failure(monkeypatch, capsys):
    class _BrokenClient:
        def search(self, request):
            raise RuntimeError("boom")

    monkeypatch.setenv("EBAY_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr("src.app.RealEbayClient.from_env", lambda sandbox=False: _BrokenClient())

    exit_code = main(["ebay-smoke"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["query"] == "A1990"
    assert payload["result_count"] == 0
    assert "RuntimeError: boom" in payload["error"]


def test_main_search_use_ebay_api_loads_env_file(monkeypatch, tmp_path, capsys):
    env_path = tmp_path / ".env"
    env_path.write_text("EBAY_ACCESS_TOKEN=from_env_file\n", encoding="utf-8")
    monkeypatch.delenv("EBAY_ACCESS_TOKEN", raising=False)

    class _FakeRealClient:
        def __init__(self) -> None:
            self.calls = 0

        def search(self, request):
            self.calls += 1
            return [
                ListingRecord(
                    title="MacBook Pro A1990 used",
                    item_id="env-1",
                    price=200.0,
                    condition_raw="Used",
                )
            ]

    fake_client = _FakeRealClient()

    def fake_from_env(sandbox=False):
        assert sandbox is False
        assert os.getenv("EBAY_ACCESS_TOKEN") == "from_env_file"
        return fake_client

    monkeypatch.setattr("src.app.RealEbayClient.from_env", fake_from_env)

    exit_code = main(
        [
            "search",
            "A1990",
            "--use-ebay-api",
            "--env-file",
            str(env_path),
            "--cache-path",
            str(tmp_path / "cache.json"),
            "--storage-path",
            str(tmp_path / "raw.json"),
            "--now-epoch",
            "1000",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert fake_client.calls == 1
    assert payload[0]["item_id"] == "env-1"


def test_main_search_use_ebay_api_missing_credentials_fails_preflight(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("EBAY_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)

    def should_not_be_called(*args, **kwargs):
        raise AssertionError("RealEbayClient.from_env should not be called when preflight fails")

    monkeypatch.setattr("src.app.RealEbayClient.from_env", should_not_be_called)

    exit_code = main(
        [
            "search",
            "A1990",
            "--use-ebay-api",
            "--env-file",
            str(tmp_path / "missing.env"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["command"] == "search"
    assert payload["auth_mode"] == "unknown"
    assert "Missing eBay credentials" in payload["error"]


def test_main_ebay_smoke_missing_credentials_fails_preflight(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("EBAY_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)

    def should_not_be_called(*args, **kwargs):
        raise AssertionError("RealEbayClient.from_env should not be called when preflight fails")

    monkeypatch.setattr("src.app.RealEbayClient.from_env", should_not_be_called)

    exit_code = main(
        [
            "ebay-smoke",
            "--env-file",
            str(tmp_path / "missing.env"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["auth_mode"] == "unknown"
    assert "Missing eBay credentials" in payload["error"]


def test_main_search_use_ebay_api_falls_back_to_cache_on_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("EBAY_ACCESS_TOKEN", "test-token")

    class _HealthyClient:
        def search(self, request):
            return [
                ListingRecord(
                    title="MacBook Pro A1990 used",
                    item_id="cache-1",
                    price=200.0,
                    shipping=20.0,
                    condition_raw="Used",
                    sale_price_whole=420.0,
                    sale_price_parts=500.0,
                )
            ]

    class _BrokenClient:
        def search(self, request):
            raise RuntimeError("api down")

    clients = [_HealthyClient(), _BrokenClient()]
    monkeypatch.setattr("src.app.RealEbayClient.from_env", lambda sandbox=False: clients.pop(0))

    cache_path = tmp_path / "cache.json"
    storage_path = tmp_path / "raw.json"

    first_exit = main(
        [
            "search",
            "A1990",
            "--use-ebay-api",
            "--cache-path",
            str(cache_path),
            "--storage-path",
            str(storage_path),
            "--now-epoch",
            "1000",
        ]
    )
    first_payload = json.loads(capsys.readouterr().out)

    second_exit = main(
        [
            "search",
            "A1990",
            "--use-ebay-api",
            "--cache-path",
            str(cache_path),
            "--storage-path",
            str(storage_path),
            "--now-epoch",
            "2000",
        ]
    )
    second_payload = json.loads(capsys.readouterr().out)

    assert first_exit == 0
    assert second_exit == 0
    assert first_payload[0]["source"] == "fresh"
    assert second_payload[0]["source"] == "cache_fallback"
    assert second_payload[0]["item_id"] == "cache-1"
    assert second_payload[0]["warning"] == "api_failed_using_cache:RuntimeError"
    assert second_payload[0]["timestamp"] == 1000.0


def test_main_search_use_ebay_api_no_cache_and_failure_returns_empty(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("EBAY_ACCESS_TOKEN", "test-token")

    class _BrokenClient:
        def search(self, request):
            raise RuntimeError("api down")

    monkeypatch.setattr("src.app.RealEbayClient.from_env", lambda sandbox=False: _BrokenClient())

    exit_code = main(
        [
            "search",
            "A1990",
            "--use-ebay-api",
            "--cache-path",
            str(tmp_path / "cache.json"),
            "--storage-path",
            str(tmp_path / "raw.json"),
            "--now-epoch",
            "1000",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload == []


def test_main_search_purchase_price_override_applies_to_local_input(tmp_path, capsys):
    input_path = tmp_path / "listings.json"
    input_rows = [
        {
            "title": "MacBook Pro A1990 used",
            "item_id": "ovr-1",
            "price": 200,
            "sale_price_whole": 420,
            "sale_price_parts": 390,
            "condition": "Used",
        }
    ]
    input_path.write_text(json.dumps(input_rows), encoding="utf-8")

    exit_code = main(
        [
            "search",
            "A1990",
            "--input",
            str(input_path),
            "--purchase-price-override",
            "300",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload[0]["item_id"] == "ovr-1"
    assert payload[0]["price"] == 300.0
    assert payload[0]["ROI_best"]["total_cost"] == 300.0


def test_main_search_purchase_price_override_rejects_non_positive(capsys):
    exit_code = main(
        [
            "search",
            "A1990",
            "--purchase-price-override",
            "0",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["command"] == "search"
    assert "purchase_price_override must be greater than 0" in payload["error"]
