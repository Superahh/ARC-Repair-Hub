"""Local JSON storage helpers with deterministic dedupe behavior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping


def dedupe_key_for_listing(listing: Mapping[str, Any]) -> str:
    """Build a stable dedupe key from item_id or URL."""
    item_id = listing.get("item_id")
    if item_id:
        return f"item_id:{item_id}"

    url = listing.get("url")
    if url:
        return f"url:{url}"

    raise ValueError("listing must include item_id or url")


def load_results(path: str | Path) -> list[dict[str, Any]]:
    """Load listing results from JSON; missing files return an empty list."""
    file_path = Path(path)
    if not file_path.exists():
        return []

    raw_text = file_path.read_text(encoding="utf-8").strip()
    if not raw_text:
        return []

    data = json.loads(raw_text)
    if not isinstance(data, list):
        raise ValueError("results file must contain a JSON list")

    return [dict(item) for item in data]


def save_results(path: str | Path, listings: Iterable[Mapping[str, Any]]) -> None:
    """Save listings to JSON, ensuring each item has a dedupe_key."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    normalized = [_with_dedupe_key(listing) for listing in listings]
    file_path.write_text(
        json.dumps(normalized, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def append_results(path: str | Path, incoming: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Append incoming listings into storage while deduping by dedupe_key."""
    existing = load_results(path)
    merged = merge_deduped(existing=existing, incoming=incoming)
    save_results(path, merged)
    return merged


def merge_deduped(
    existing: Iterable[Mapping[str, Any]],
    incoming: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge two listing sets; incoming entries overwrite existing duplicates."""
    merged: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}

    for listing in existing:
        normalized = _with_dedupe_key(listing)
        key = normalized["dedupe_key"]
        index_by_key[key] = len(merged)
        merged.append(normalized)

    for listing in incoming:
        normalized = _with_dedupe_key(listing)
        key = normalized["dedupe_key"]
        if key in index_by_key:
            merged[index_by_key[key]] = normalized
            continue
        index_by_key[key] = len(merged)
        merged.append(normalized)

    return merged


def _with_dedupe_key(listing: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(listing)
    if not normalized.get("dedupe_key"):
        normalized["dedupe_key"] = dedupe_key_for_listing(normalized)
    return normalized
