import json

import pytest

from src.storage import (
    append_results,
    dedupe_key_for_listing,
    load_results,
    merge_deduped,
    save_results,
)


def test_load_results_missing_file_returns_empty_list(tmp_path):
    path = tmp_path / "results.json"
    assert load_results(path) == []


def test_dedupe_key_prefers_item_id_then_url():
    assert dedupe_key_for_listing({"item_id": "abc-123"}) == "item_id:abc-123"
    assert dedupe_key_for_listing({"url": "https://example.com/item/1"}) == "url:https://example.com/item/1"


def test_dedupe_key_requires_item_id_or_url():
    with pytest.raises(ValueError):
        dedupe_key_for_listing({"title": "Missing identifiers"})


def test_merge_deduped_overwrites_duplicate_item_id_and_keeps_unique():
    existing = [
        {"item_id": "1", "title": "Old one"},
        {"item_id": "2", "title": "Two"},
    ]
    incoming = [
        {"item_id": "1", "title": "Updated one"},
        {"item_id": "3", "title": "Three"},
    ]

    merged = merge_deduped(existing=existing, incoming=incoming)

    assert len(merged) == 3
    assert merged[0]["item_id"] == "1"
    assert merged[0]["title"] == "Updated one"
    assert merged[1]["item_id"] == "2"
    assert merged[2]["item_id"] == "3"
    assert all("dedupe_key" in item for item in merged)


def test_merge_deduped_uses_url_when_item_id_missing():
    existing = [{"url": "https://example.com/item/1", "title": "Old"}]
    incoming = [{"url": "https://example.com/item/1", "title": "New"}]

    merged = merge_deduped(existing=existing, incoming=incoming)

    assert len(merged) == 1
    assert merged[0]["title"] == "New"
    assert merged[0]["dedupe_key"] == "url:https://example.com/item/1"


def test_save_and_append_results_round_trip(tmp_path):
    path = tmp_path / "data" / "results.json"
    base = [{"item_id": "1", "title": "One"}]
    save_results(path, base)

    merged = append_results(
        path,
        [
            {"item_id": "1", "title": "One updated"},
            {"item_id": "2", "title": "Two"},
        ],
    )
    reloaded = load_results(path)

    assert merged == reloaded
    assert [item["item_id"] for item in reloaded] == ["1", "2"]
    assert reloaded[0]["title"] == "One updated"
    assert all("dedupe_key" in item for item in reloaded)

    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, list)
