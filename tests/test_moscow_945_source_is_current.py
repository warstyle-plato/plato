from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_verified_945_card_points_at_the_2118_amendment_source() -> None:
    rows = json.loads((ROOT / "data/normatives/registry.json").read_text(encoding="utf-8"))
    item = next(row for row in rows if row["id"] == "moscow-945-pp")

    assert item["status"] == "verified"
    assert "2118-ПП" in item["latest_amendment"]
    assert "945-ppS1092025.pdf" not in item["source_url"]
    assert "2118" in item["source_url"]

    pack = ROOT / item["source_pack"]
    assert pack.exists()
    text = pack.read_text(encoding="utf-8")
    assert "05.08.2026" in text
    assert "2118-ПП" in text
    assert "945-ppS1092025.pdf" in text
