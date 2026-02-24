import json

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
