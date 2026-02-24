import json

from src.app import main, search_records


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
